"""Employee import: fields, preview validation, job submission, job status and failure report (B6).

Validation never writes anything (contract: "must not persist anything"). Starting an import only
stores the job; the rows are imported by the background worker (app/worker.py, see
import_job_runner.py), which re-validates every row at import time.
"""

from __future__ import annotations

import csv
import io
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationFailedError
from app.models.import_job_model import EmployeeImportJob
from app.schemas.import_schema import (
    ImportFieldOut,
    ImportJobOut,
    ImportRowIn,
    ImportRowResultOut,
    ImportValidationOut,
    JobFailureOut,
    JobSummaryOut,
    ProgressOut,
    ValidationSummaryOut,
)
from app.services.audit_service import AuditService
from app.services.employee_support import Caller, References
from app.services.import_rows import RowChecker, field_definitions

TERMINAL = ("succeeded", "failed", "cancelled")


def check_rows_request(rows: list[ImportRowIn]) -> None:
    limit = get_settings().import_max_rows
    if not rows:
        raise ValidationFailedError(details=[{"field": "rows", "message": "Send at least one row."}])
    if len(rows) > limit:
        raise ValidationFailedError(f"At most {limit} rows can be imported at once.", details=[{"field": "rows", "message": f"At most {limit} rows can be imported at once."}])
    numbers = [r.row_number for r in rows]
    if len(set(numbers)) != len(numbers):
        raise ValidationFailedError(details=[{"field": "rows", "message": "Each row needs a different rowNumber."}])


def job_out(job: EmployeeImportJob) -> ImportJobOut:
    done = job.status in TERMINAL
    return ImportJobOut(
        id=str(job.id),
        status=job.status,
        progress=ProgressOut(processed=job.processed, total=job.total),
        # Counts are shown for every finished job, including one that stopped part-way, so the outcome is never hidden.
        summary=JobSummaryOut(created=job.created_count, skipped=job.skipped_count, failed=job.failed_count) if done else None,
        failures=[JobFailureOut(row_number=f["rowNumber"], messages=f["messages"]) for f in job.failures],
        created_at=job.created_at,
        finished_at=job.finished_at,
        error=job.error,
    )


def principal_snapshot(caller: Caller) -> dict:
    p = caller.principal
    return {"user_id": p.user_id, "name": p.name, "permissions": sorted(p.permissions), "roles": sorted(p.roles), "employee_id": p.employee_id}


class EmployeeImportService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.audit = AuditService(session)

    async def fields(self) -> list[ImportFieldOut]:
        return field_definitions(self.caller, await References.load(self.session))

    async def validate(self, rows: list[ImportRowIn]) -> ImportValidationOut:
        check_rows_request(rows)
        checker = RowChecker(self.session, self.caller, await References.load(self.session))
        results = []
        for row in sorted(rows, key=lambda r: r.row_number):
            outcome = await checker.check(row)
            results.append(ImportRowResultOut(row_number=outcome.row_number, status=outcome.status, messages=outcome.messages))
        await self.session.rollback()  # nothing is ever written by validation
        counts = {s: sum(1 for r in results if r.status == s) for s in ("valid", "warning", "duplicate", "error")}
        return ImportValidationOut(rows=results, summary=ValidationSummaryOut(total=len(results), **counts))

    async def start(self, rows: list[ImportRowIn], skip_duplicates: bool) -> ImportJobOut:
        check_rows_request(rows)
        ordered = sorted(rows, key=lambda r: r.row_number)
        job = EmployeeImportJob(
            status="queued", skip_duplicates=skip_duplicates, principal=principal_snapshot(self.caller),
            rows=[{"rowNumber": r.row_number, "values": r.values} for r in ordered], total=len(ordered), processed=0,
            created_count=0, skipped_count=0, failed_count=0, failures=[],
        )
        self.session.add(job)
        await self.session.flush()
        self.audit.record(
            module="Employees", action="employee_import.started", summary=f"Employee import of {len(ordered)} row(s) queued", entity_type="employee_import_job", entity_id=job.id,
            changes=[{"field": "rows", "before": None, "after": str(len(ordered))}, {"field": "skipDuplicates", "before": None, "after": str(skip_duplicates)}],
        )
        await self.session.commit()
        return job_out(job)

    async def _own_job(self, job_id: uuid.UUID) -> EmployeeImportJob:
        job = await self.session.scalar(select(EmployeeImportJob).where(EmployeeImportJob.id == job_id, EmployeeImportJob.created_by == self.caller.principal.actor_uuid))
        if job is None:
            raise NotFoundError()  # another user's job looks like a missing one
        return job

    async def job(self, job_id: uuid.UUID) -> ImportJobOut:
        return job_out(await self._own_job(job_id))

    async def failure_report(self, job_id: uuid.UUID) -> tuple[bytes, str]:
        """CSV of failed and skipped rows. Cells that could start a spreadsheet formula are neutralised."""
        job = await self._own_job(job_id)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Row", "Messages"])
        for f in job.failures:
            writer.writerow([str(f["rowNumber"]), safe_cell(" | ".join(f["messages"]))])
        self.audit.record(module="Employees", action="employee_import.report_downloaded", summary="Employee import failure report downloaded", entity_type="employee_import_job", entity_id=job.id)
        await self.session.commit()
        return ("﻿" + buffer.getvalue()).encode("utf-8"), f"employee-import-{str(job.id)[:8]}-failures.csv"


def safe_cell(value: str) -> str:
    """Prefixes values a spreadsheet would treat as a formula (CSV injection)."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value
