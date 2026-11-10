"""Attendance period locks: dates whose attendance can no longer change (a finalized payroll period).

The payroll module will create these when it finalizes a period. Until then HR with hr.payroll:approve
records them here. Locks cannot be removed through the API (a finalized period stays final).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_model import AttendanceLockPeriod
from app.schemas.attendance_schema import LockIn, LockOut
from app.services.attendance.jobs import store_days
from app.services.audit_service import AuditService
from app.services.employee_support import company_today, parse_date
from app.models.employee_model import Employee
from app.utils.validation import FieldErrors


def _out(r: AttendanceLockPeriod) -> LockOut:
    return LockOut(id=str(r.id), from_date=r.from_date.isoformat(), to_date=r.to_date.isoformat(), reason=r.reason, created_at=r.created_at, created_by=r.created_by_name)


class LockService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list(self) -> list[LockOut]:
        return [_out(r) for r in (await self.session.scalars(select(AttendanceLockPeriod).order_by(AttendanceLockPeriod.from_date.desc()))).all()]

    async def create(self, data: LockIn) -> LockOut:
        err = FieldErrors()
        dates = []
        for field, raw in (("fromDate", data.from_date), ("toDate", data.to_date)):
            try:
                d = parse_date(raw)
            except ValueError:
                d = None
            if d is None:
                err.add(field, "Enter the date as YYYY-MM-DD.")
            dates.append(d)
        start, end = dates
        if start and end and end < start:
            err.add("toDate", "The end date must be on or after the start date.")
        if end and end >= company_today():
            err.add("toDate", "Only finished days can be locked.")
        err.raise_if_any()
        # Freeze the current results first: locked dates are read from these stored records.
        employees = list((await self.session.scalars(select(Employee).where(Employee.joining_date <= end))).all())
        await store_days(self.session, employees, start, end)
        lock = AttendanceLockPeriod(from_date=start, to_date=end, reason=data.reason.strip())
        self.session.add(lock)
        await self.session.flush()
        AuditService(self.session).record(module="Attendance", action="attendance_period.locked", summary=f"Attendance locked from {start.isoformat()} to {end.isoformat()}: {lock.reason}", entity_type="attendance_lock_period", entity_id=lock.id)
        await self.session.commit()
        return _out(lock)
