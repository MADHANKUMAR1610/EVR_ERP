"""Runs an employee import job (called by the worker, app/worker.py).

Transaction strategy (documented in docs/MODULE_4_DECISIONS.md):
- Rows are processed in file order, in batches of IMPORT_BATCH_SIZE.
- Each row is inserted inside its own SAVEPOINT. A row that fails validation, or hits a database
  constraint (for example an employee with the same code created meanwhile by someone else), is
  rolled back alone and recorded in `failures` with its reasons. It never affects the other rows.
- Each batch is committed in ONE transaction together with the job's progress and counts, so the
  stored counts always match what is in the database.
- If the worker stops part-way, the batches already committed stay (and are reported); another
  worker resumes after the last committed row once the heartbeat is stale. No row is imported twice.
- If processing fails unexpectedly, the job ends as "failed" with the counts so far and a message
  saying how many employees were created, so a partial import is never silent.
- No row is ever skipped silently: duplicates skipped by request (skipDuplicates) are listed in
  `failures` with "Skipped:" and counted as skipped.
"""

from __future__ import annotations

import logging
import uuid

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import SYSTEM_ACTOR_ID, SYSTEM_ACTOR_NAME, Principal
from app.database.audit_listener import acting_as
from app.database.base import utcnow
from app.models.import_job_model import EmployeeImportJob
from app.schemas.import_schema import ImportRowIn
from app.services.audit_service import AuditService
from app.services.employee_support import References, caller_context
from app.services.import_rows import RowChecker

logger = logging.getLogger("hrms.import")


async def claim_next_job(session: AsyncSession, worker_id: str) -> uuid.UUID | None:
    """Takes the oldest queued job, or a running job whose worker stopped sending heartbeats."""
    stale = get_settings().worker_stale_seconds
    candidate = (
        select(EmployeeImportJob.id)
        .where((EmployeeImportJob.status == "queued") | ((EmployeeImportJob.status == "running") & (EmployeeImportJob.heartbeat_at < utcnow() - _seconds(stale))))
        .order_by(EmployeeImportJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    now = utcnow()
    job_id = await session.scalar(
        update(EmployeeImportJob)
        .where(EmployeeImportJob.id == candidate)
        .values(status="running", worker_id=worker_id, heartbeat_at=now, started_at=func.coalesce(EmployeeImportJob.started_at, now),
                updated_at=now, updated_by=SYSTEM_ACTOR_ID, updated_by_name=SYSTEM_ACTOR_NAME, version=EmployeeImportJob.version + 1)
        .returning(EmployeeImportJob.id)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return job_id


def _seconds(n: int) -> timedelta:
    return timedelta(seconds=n)


async def run_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    job = await session.get(EmployeeImportJob, job_id, populate_existing=True)
    if job is None or job.status != "running":
        return
    p = job.principal
    principal = Principal(user_id=p["user_id"], name=p["name"], permissions=frozenset(p["permissions"]), roles=frozenset(p["roles"]), employee_id=p.get("employee_id"))
    batch_size = get_settings().import_batch_size
    with acting_as(principal):  # rows are created as the job owner, within the owner's organizational scope
        try:
            if job.started_at is None:
                job.started_at = utcnow()
            caller = await caller_context(session, principal)
            refs = await References.load(session)
            checker = RowChecker(session, caller, refs)
            rows = [ImportRowIn(row_number=r["rowNumber"], values=r["values"]) for r in (job.rows or [])]
            # Duplicates within the file: rows already processed in an earlier run are known to the checker.
            for row in rows[: job.processed]:
                checker.remember(row)
            failures = list(job.failures)
            counts = {"created": job.created_count, "skipped": job.skipped_count, "failed": job.failed_count}
            for start in range(job.processed, len(rows), batch_size):
                for row in rows[start : start + batch_size]:
                    outcome = await _import_row(session, job, checker, refs, row, failures)
                    counts[outcome] += 1
                # Progress, counts and failures are written with the batch's employees, in one transaction.
                job.processed = min(start + batch_size, len(rows))
                job.created_count, job.skipped_count, job.failed_count = counts["created"], counts["skipped"], counts["failed"]
                job.failures = list(failures)
                job.heartbeat_at = utcnow()
                await session.commit()
            job.status = "succeeded"
            job.finished_at = utcnow()
            job.rows = None  # personal data is kept only while needed
            AuditService(session).record(
                module="Employees", action="employee_import.completed", summary=f"Employee import finished: {job.created_count} created, {job.skipped_count} skipped, {job.failed_count} failed",
                entity_type="employee_import_job", entity_id=job.id,
            )
            await session.commit()
        except Exception:
            logger.exception("employee import job %s stopped", job_id)
            await session.rollback()
            await _fail(session, job_id)


async def _import_row(session: AsyncSession, job: EmployeeImportJob, checker: RowChecker, refs: References, row: ImportRowIn, failures: list[dict]) -> str:
    """Imports one row inside its own savepoint. Returns "created", "skipped" or "failed"."""
    outcome = await checker.check(row)
    if outcome.errors:
        reasons = [m.message for m in outcome.errors]
        if outcome.duplicate_only and job.skip_duplicates:
            failures.append({"rowNumber": row.row_number, "messages": [f"Skipped: {r}" for r in reasons]})
            return "skipped"
        failures.append({"rowNumber": row.row_number, "messages": reasons})
        return "failed"
    try:
        async with session.begin_nested():
            await checker.employees.insert_planned(outcome.plan, refs, imported_by_job=str(job.id))
    except IntegrityError:
        failures.append({"rowNumber": row.row_number, "messages": ["Another employee with the same Employee ID, email or attendance ID was saved while this import was running."]})
        return "failed"
    return "created"


async def _fail(session: AsyncSession, job_id: uuid.UUID) -> None:
    job = await session.get(EmployeeImportJob, job_id, populate_existing=True)
    if job is None:
        return
    with acting_as(Principal(user_id=str(SYSTEM_ACTOR_ID), name=SYSTEM_ACTOR_NAME, permissions=frozenset({"*"}))):
        job.status = "failed"
        job.finished_at = utcnow()
        job.rows = None
        job.error = (
            f"The import stopped unexpectedly after {job.processed} of {job.total} rows. {job.created_count} employee(s) were created and are kept; "
            f"the remaining {job.total - job.processed} row(s) were not imported. Import them again in a new file."
        )
        AuditService(session).record(module="Employees", action="employee_import.failed", summary=job.error, entity_type="employee_import_job", entity_id=job.id, result="failure")
        await session.commit()
