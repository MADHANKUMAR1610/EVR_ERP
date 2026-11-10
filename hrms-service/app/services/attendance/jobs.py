"""Background jobs for attendance (generic `background_job` queue, run by the worker).

Types:
- `attendance.recalculate` {employeeIds, from, to}: refreshes stored day records (attendance_day) for
  finished, unlocked days, after a back-dated shift assignment or an approved correction.
- `attendance.close_day` {date}: stores the day records of all employees for a finished day
  (scheduled by the worker for yesterday, once per day).
- `workflow.escalate`: escalates overdue approval steps (scheduled by the worker, at most hourly).
- `shift.sync_current`: copies the assignment in force today to employee.shift_id (daily).
Module 6 (leave):
- `leave.escalate`: leave reminders and escalations (every 15 minutes);
- `leave.accrue`: accrual and carry-forward of the leave policies HR entered (daily);
- `notifications.deliver`: delivers the notification outbox to Platform (every 5 minutes, once configured).
`workflow.escalate` also escalates overtime requests (G5 process `overtime`).
Same mechanics as import jobs: FOR UPDATE SKIP LOCKED, heartbeat, stale take-over.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.context import SYSTEM_ACTOR_ID, SYSTEM_ACTOR_NAME, SYSTEM_PRINCIPAL
from app.database.audit_listener import acting_as
from app.database.base import utcnow
from app.models.attendance_model import AttendanceDay, BackgroundJob, ShiftAssignment
from app.models.employee_model import Employee

logger = logging.getLogger("hrms.jobs")


async def enqueue(session: AsyncSession, job_type: str, payload: dict, *, dedupe_key: str | None = None) -> None:
    """Queues a job (in the caller's transaction). A job with the same dedupe key is queued only once."""
    stmt = insert(BackgroundJob).values(
        id=uuid.uuid4(), type=job_type, payload=payload, dedupe_key=dedupe_key, status="queued", attempts=0, version=1,
        created_by=SYSTEM_ACTOR_ID, created_by_name=SYSTEM_ACTOR_NAME, updated_by=SYSTEM_ACTOR_ID, updated_by_name=SYSTEM_ACTOR_NAME,
    )
    if dedupe_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"])
    await session.execute(stmt)


async def enqueue_recalculation(session: AsyncSession, employee_ids: list[uuid.UUID], start: date, end: date, *, reason: str) -> None:
    await enqueue(session, "attendance.recalculate", {"employeeIds": [str(e) for e in employee_ids], "from": start.isoformat(), "to": end.isoformat(), "reason": reason})


async def claim_background_job(session: AsyncSession, worker_id: str) -> uuid.UUID | None:
    stale = timedelta(seconds=get_settings().worker_stale_seconds)
    now = utcnow()
    candidate = (
        select(BackgroundJob.id)
        .where((BackgroundJob.status == "queued") | ((BackgroundJob.status == "running") & (BackgroundJob.heartbeat_at < now - stale)))
        .order_by(BackgroundJob.created_at).limit(1).with_for_update(skip_locked=True).scalar_subquery()
    )
    job_id = await session.scalar(
        update(BackgroundJob).where(BackgroundJob.id == candidate)
        .values(status="running", worker_id=worker_id, heartbeat_at=now, started_at=func.coalesce(BackgroundJob.started_at, now), attempts=BackgroundJob.attempts + 1,
                updated_at=now, updated_by=SYSTEM_ACTOR_ID, updated_by_name=SYSTEM_ACTOR_NAME, version=BackgroundJob.version + 1)
        .returning(BackgroundJob.id).execution_options(synchronize_session=False)
    )
    await session.commit()
    return job_id


async def store_days(session: AsyncSession, employees: list[Employee], start: date, end: date) -> int:
    """Writes the calculated records of finished, unlocked days (upsert). Returns the number written."""
    from app.services.attendance.attendance_data import AttendanceData, company_tz, locked_dates

    today = datetime.now(UTC).astimezone(company_tz()).date()
    end = min(end, today - timedelta(days=1))
    if end < start or not employees:
        return 0
    locks = await locked_dates(session, start, end)
    computed = await AttendanceData(session).compute(employees, start, end)
    now = utcnow()
    written = 0
    for e in employees:
        for d, r in computed[e.id].days.items():
            if d in locks:
                continue
            values = dict(
                status=r.status, shift_id=uuid.UUID(r.shift.id) if r.shift else None, first_in=r.first_in, last_out=r.last_out, worked_minutes=r.worked_minutes,
                late_minutes=r.late_minutes, early_exit_minutes=r.early_exit_minutes, overtime_minutes=r.overtime_minutes, beyond_shift_minutes=r.beyond_shift_minutes,
                exceptions=r.exceptions, warnings=r.warnings, corrected=r.corrected, calculated_at=now, updated_at=now, updated_by=SYSTEM_ACTOR_ID, updated_by_name=SYSTEM_ACTOR_NAME,
            )
            stmt = insert(AttendanceDay).values(id=uuid.uuid4(), employee_id=e.id, date=d, created_by=SYSTEM_ACTOR_ID, created_by_name=SYSTEM_ACTOR_NAME, **values)
            await session.execute(stmt.on_conflict_do_update(index_elements=["employee_id", "date"], set_=values))
            written += 1
    return written


async def sync_current_shifts(session: AsyncSession) -> int:
    """employee.shift_id follows the assignment in force today (future-dated assignments start on their date)."""
    from app.services.attendance.attendance_data import company_tz

    today = datetime.now(UTC).astimezone(company_tz()).date()
    latest = (
        select(ShiftAssignment.employee_id, ShiftAssignment.shift_id)
        .where(ShiftAssignment.effective_from <= today)
        .distinct(ShiftAssignment.employee_id)
        .order_by(ShiftAssignment.employee_id, ShiftAssignment.effective_from.desc())
    )
    changed = 0
    for employee_id, shift_id in (await session.execute(latest)).all():
        employee = await session.get(Employee, employee_id)
        if employee.shift_id != shift_id:
            employee.shift_id = shift_id
            changed += 1
    return changed


async def run_background_job(session: AsyncSession, job_id: uuid.UUID) -> None:
    from app.services.attendance.correction_service import escalate_overdue
    from app.services.leave.balance_service import run_accrual
    from app.services.leave.notifications import deliver_pending
    from app.services.leave.request_service import escalate_leave
    from app.services.leave.short_request_service import escalate_overtime

    job = await session.get(BackgroundJob, job_id, populate_existing=True)
    if job is None or job.status != "running":
        return
    with acting_as(SYSTEM_PRINCIPAL):
        try:
            p = job.payload
            if job.type == "attendance.recalculate":
                ids = [uuid.UUID(x) for x in p["employeeIds"]]
                employees = list((await session.scalars(select(Employee).where(Employee.id.in_(ids)))).all())
                result = {"daysStored": await store_days(session, employees, date.fromisoformat(p["from"]), date.fromisoformat(p["to"]))}
            elif job.type == "attendance.close_day":
                day = date.fromisoformat(p["date"])
                employees = list((await session.scalars(select(Employee).where(Employee.joining_date <= day))).all())
                result = {"daysStored": await store_days(session, employees, day, day)}
            elif job.type == "workflow.escalate":
                result = {"escalated": await escalate_overdue(session), "overtimeEscalated": await escalate_overtime(session)}
            elif job.type == "leave.escalate":
                result = await escalate_leave(session)
            elif job.type == "leave.accrue":
                result = await run_accrual(session)
            elif job.type == "notifications.deliver":
                result = await deliver_pending(session)
            elif job.type == "shift.sync_current":
                result = {"employeesUpdated": await sync_current_shifts(session)}
            else:
                raise ValueError(f"unknown job type {job.type}")
            job = await session.get(BackgroundJob, job_id)
            job.status, job.result, job.finished_at = "succeeded", result, utcnow()
            await session.commit()
        except Exception as exc:  # noqa: BLE001 - recorded on the job
            logger.exception("background job %s (%s) failed", job_id, job.type)
            await session.rollback()
            job = await session.get(BackgroundJob, job_id, populate_existing=True)
            job.status, job.error, job.finished_at = "failed", f"{type(exc).__name__}: {exc}"[:2000], utcnow()
            await session.commit()


async def schedule_periodic(session: AsyncSession) -> None:
    """Queues the scheduled jobs that are due (idempotent through their dedupe keys)."""
    from app.services.attendance.attendance_data import company_tz

    now = datetime.now(UTC).astimezone(company_tz())
    yesterday = now.date() - timedelta(days=1)
    await enqueue(session, "attendance.close_day", {"date": yesterday.isoformat()}, dedupe_key=f"close-day:{yesterday.isoformat()}")
    await enqueue(session, "shift.sync_current", {}, dedupe_key=f"shift-sync:{now.date().isoformat()}")
    await enqueue(session, "workflow.escalate", {}, dedupe_key=f"escalate:{now.strftime('%Y-%m-%dT%H')}")
    await enqueue(session, "leave.escalate", {}, dedupe_key=f"leave-escalate:{now.strftime('%Y-%m-%dT%H')}:{now.minute // 15}")
    await enqueue(session, "leave.accrue", {}, dedupe_key=f"leave-accrue:{now.date().isoformat()}")
    from app.models.leave_model import NotificationOutbox
    from app.services.leave.notifications import delivery_configured

    if delivery_configured() and await session.scalar(select(NotificationOutbox.id).where(NotificationOutbox.status == "pending").limit(1)):
        await enqueue(session, "notifications.deliver", {}, dedupe_key=f"notify:{now.strftime('%Y-%m-%dT%H')}:{now.minute // 5}")
    await session.commit()
