"""The leave calendar: weekly offs, holidays, leave years and deadlines.

- Weekly offs are the non-working days of the employee's assigned shift on each date (Module 5
  shift assignments). Without a shift, the company working days (COMPANY_WORKING_DAYS, L18) are
  used. If those are not configured either, nothing is guessed: the date counts as a working
  day and a warning says so.
- Holidays are company-wide (no location) or for one work location (owner decision 4). An
  employee gets the company-wide holidays plus those of their own work location.
- The leave year starts in the month of the G6 setting `leaveYearStartMonth` (empty: January, L6).
  A leave year is named by the calendar year it starts in.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.employee_model import Employee
from app.models.leave_model import Holiday
from app.services.attendance.attendance_data import AttendanceData, company_tz, daterange
from app.services.attendance.policy_service import policy_values_on
from app.services.employee_support import company_today

NO_CALENDAR_WARNING = "No shift is assigned for some of these dates and the company working days are not configured, so weekly offs could not be excluded."


def holiday_clause(location_id: uuid.UUID | None):
    """Holidays that apply to an employee at `location_id` (company-wide plus their location's)."""
    if location_id is None:
        return Holiday.work_location_id.is_(None)
    return or_(Holiday.work_location_id.is_(None), Holiday.work_location_id == location_id)


async def holidays_between(session: AsyncSession, location_id: uuid.UUID | None, start: date, end: date) -> dict[date, Holiday]:
    rows = (await session.scalars(select(Holiday).where(Holiday.date >= start, Holiday.date <= end, holiday_clause(location_id)))).all()
    out: dict[date, Holiday] = {}
    for h in rows:
        # A location's own holiday on the same date as a company-wide one: show the location's name.
        if h.date not in out or h.work_location_id is not None:
            out[h.date] = h
    return out


async def leave_year_start_month(session: AsyncSession) -> int:
    value = (await policy_values_on(session, company_today())).get("leave", "leaveYearStartMonth")
    return int(value) if value else 1


def leave_year_of(day: date, start_month: int) -> int:
    return day.year if day.month >= start_month else day.year - 1


def leave_year_bounds(year: int, start_month: int) -> tuple[date, date]:
    start = date(year, start_month, 1)
    end = date(year + 1, start_month, 1) - timedelta(days=1)
    return start, end


@dataclass
class RangeDays:
    charged: list[date] = field(default_factory=list)
    excluded: list[tuple[date, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class LeaveCalendar:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.attendance = AttendanceData(session)

    async def range_days(self, employee: Employee, start: date, end: date, *, count_offs: bool) -> RangeDays:
        """Splits [start, end] into charged dates and excluded weekly offs / holidays."""
        out = RangeDays()
        holidays = await holidays_between(self.session, employee.work_location_id, start, end)
        assignments = await self.attendance.assignments([employee.id])
        company_days = get_settings().company_working_days
        unknown = False
        for d in daterange(start, end):
            shift = await self.attendance.shift_for(employee.id, d, assignments)
            if shift is not None:
                off = d.isoweekday() not in shift.working_days
            elif company_days:
                off = d.isoweekday() not in company_days
            else:
                off, unknown = False, True
            reason = None
            if d in holidays:
                reason = f"Holiday: {holidays[d].name}"
            elif off:
                reason = "Weekly off"
            if reason and not count_offs:
                out.excluded.append((d, reason))
            else:
                out.charged.append(d)
        if unknown:
            out.warnings.append(NO_CALENDAR_WARNING)
        return out

    async def deadline(self, start: datetime, after: int, unit: str, location_id: uuid.UUID | None) -> datetime:
        """Escalation deadline. `working_days` skips non-working company days and holidays (company
        time zone); the deadline keeps the submission's time of day."""
        if unit == "hours":
            return start + timedelta(hours=after)
        if unit == "days":
            return start + timedelta(days=after)
        working = get_settings().company_working_days
        if not working:  # refused when the workflow is saved; only if the setting was removed later
            return start + timedelta(days=after)
        tz = company_tz()
        local = start.astimezone(tz)
        day = local.date()
        holidays = await holidays_between(self.session, location_id, day, day + timedelta(days=after * 7 + 60))
        remaining = after
        while remaining > 0:
            day += timedelta(days=1)
            if day.isoweekday() in working and day not in holidays:
                remaining -= 1
        return datetime.combine(day, local.timetz())
