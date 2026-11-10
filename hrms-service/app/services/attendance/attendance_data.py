"""Loads everything the calculator needs, in bulk, for a set of employees and dates.

Reads always calculate from the current data (punches, approved corrections, shift assignments, HR
settings), so every screen shows the same result. Exception: dates inside a locked period
(finalized payroll) use the stored day record, so they never change after locking.
"""

from __future__ import annotations

import uuid
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.attendance_model import AttendanceCorrection, AttendanceDay, AttendanceDevice, AttendanceEvent, AttendanceLockPeriod, PolicySetting, ShiftAssignment
from app.models.employee_model import Employee, EmployeeHistory
from app.models.reference_data_model import EmployeeStatus
from app.models.shift_model import Shift
from app.services.attendance.calculator import DayResult, Punch, Settings, ShiftInfo, apply_correction, apply_leave_and_holiday, calculate_day


def company_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().company_time_zone)


def shift_info(s: Shift) -> ShiftInfo:
    return ShiftInfo(str(s.id), s.code, s.name, s.start_time, s.end_time, s.overnight, s.break_minutes, s.grace_minutes, tuple(s.working_days))


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


class PolicyTimeline:
    """Policy values by date, from all policy_setting rows (few rows; loaded once)."""

    def __init__(self, rows: list[PolicySetting]):
        self.by_area: dict[str, list[tuple[date, dict]]] = defaultdict(list)
        for r in sorted(rows, key=lambda r: r.effective_from):
            self.by_area[r.area].append((r.effective_from, r.values))

    def values(self, area: str, on: date) -> dict:
        rows = self.by_area.get(area, [])
        i = bisect_right([d for d, _ in rows], on)
        return rows[i - 1][1] if i else {}

    def settings(self, on: date) -> Settings:
        a, o = self.values("attendance", on), self.values("overtime", on)
        return Settings(
            deduct_break=a.get("deductBreak") is True, half_day_below=a.get("halfDayBelowMinutes"), absent_below=a.get("absentBelowMinutes"),
            calculate_overtime=o.get("calculateOvertime") is True, ot_minimum=o.get("minimumMinutes"), ot_rounding=o.get("roundingMinutes"), ot_cap=o.get("maxMinutesPerDay"),
        )


async def load_policies(session: AsyncSession) -> PolicyTimeline:
    return PolicyTimeline(list((await session.scalars(select(PolicySetting))).all()))


async def locked_dates(session: AsyncSession, start: date, end: date) -> set[date]:
    rows = (await session.scalars(select(AttendanceLockPeriod).where(AttendanceLockPeriod.from_date <= end, AttendanceLockPeriod.to_date >= start))).all()
    return {d for r in rows for d in daterange(max(r.from_date, start), min(r.to_date, end))}


async def is_locked(session: AsyncSession, start: date, end: date) -> bool:
    return bool(await locked_dates(session, start, end))


@dataclass
class EmployeeDays:
    employee: Employee
    days: dict[date, DayResult]


class AttendanceData:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.tz = company_tz()
        self.shifts: dict[uuid.UUID, Shift] = {}

    async def _shifts(self) -> dict[uuid.UUID, Shift]:
        if not self.shifts:
            self.shifts = {s.id: s for s in (await self.session.scalars(select(Shift))).all()}
        return self.shifts

    async def assignments(self, employee_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[tuple[date, uuid.UUID]]]:
        out: dict[uuid.UUID, list[tuple[date, uuid.UUID]]] = defaultdict(list)
        if employee_ids:
            rows = (await self.session.execute(select(ShiftAssignment.employee_id, ShiftAssignment.effective_from, ShiftAssignment.shift_id).where(ShiftAssignment.employee_id.in_(employee_ids)).order_by(ShiftAssignment.effective_from))).all()
            for emp, eff, sid in rows:
                out[emp].append((eff, sid))
        return out

    async def shift_for(self, employee_id: uuid.UUID, on: date, assignments: dict | None = None) -> ShiftInfo | None:
        assignments = assignments if assignments is not None else await self.assignments([employee_id])
        rows = assignments.get(employee_id, [])
        i = bisect_right([d for d, _ in rows], on)
        if not i:
            return None
        shift = (await self._shifts()).get(rows[i - 1][1])
        return shift_info(shift) if shift else None

    async def exit_dates(self, employees: list[Employee]) -> dict[uuid.UUID, date]:
        """Effective date of the move into a status marked "employment ended", for employees now in one."""
        ended = set((await self.session.scalars(select(EmployeeStatus.code).where(EmployeeStatus.employment_ended.is_(True)))).all())
        ids = [e.id for e in employees if e.status_code in ended]
        if not ids:
            return {}
        rows = (await self.session.execute(
            select(EmployeeHistory.employee_id, EmployeeHistory.effective_date, EmployeeHistory.created_at)
            .where(EmployeeHistory.employee_id.in_(ids), EmployeeHistory.action == "status_changed", EmployeeHistory.to_status.in_(ended))
            .order_by(EmployeeHistory.created_at)
        )).all()
        out = {}
        for emp, eff, created in rows:
            out[emp] = eff or created.astimezone(self.tz).date()
        return out

    async def compute(self, employees: list[Employee], start: date, end: date, *, now: datetime | None = None) -> dict[uuid.UUID, EmployeeDays]:
        """Day results for each employee from max(start, joining) to min(end, today, exit date)."""
        now = (now or datetime.now(UTC)).astimezone(self.tz)
        today = now.date()
        end = min(end, today)
        result = {e.id: EmployeeDays(e, {}) for e in employees}
        if not employees or end < start:
            return result
        ids = [e.id for e in employees]
        await self._shifts()
        assignments = await self.assignments(ids)
        policies = await load_policies(self.session)
        locks = await locked_dates(self.session, start, end)
        exits = await self.exit_dates(employees)
        devices = {d.id: d.name for d in (await self.session.scalars(select(AttendanceDevice))).all()}

        # Events: accepted punches by (employee, date); warnings from all events of the day.
        events = (await self.session.scalars(select(AttendanceEvent).where(AttendanceEvent.employee_id.in_(ids), AttendanceEvent.attendance_date >= start, AttendanceEvent.attendance_date <= end))).all()
        punches: dict[tuple, list[Punch]] = defaultdict(list)
        warnings: dict[tuple, set[str]] = defaultdict(set)
        for ev in events:
            key = (ev.employee_id, ev.attendance_date)
            warnings[key].update(ev.warnings or [])
            if ev.processing_status == "accepted":
                punches[key].append(Punch(ev.at, ev.direction, ev.source, devices.get(ev.device_id), str(ev.id)))
        corrections = (await self.session.scalars(
            select(AttendanceCorrection).where(AttendanceCorrection.employee_id.in_(ids), AttendanceCorrection.date >= start, AttendanceCorrection.date <= end, AttendanceCorrection.status.in_(("approved", "pending")))
            .order_by(AttendanceCorrection.reviewed_at)
        )).all()
        approved: dict[tuple, AttendanceCorrection] = {}
        pending: set[tuple] = set()
        for c in corrections:
            if c.status == "approved":
                approved[(c.employee_id, c.date)] = c  # the latest approved one wins
            else:
                pending.add((c.employee_id, c.date))
        leave, holidays = await leave_and_holidays(self.session, employees, start, end)
        stored = {}
        if locks:
            rows = (await self.session.scalars(select(AttendanceDay).where(AttendanceDay.employee_id.in_(ids), AttendanceDay.date.in_(locks)))).all()
            stored = {(r.employee_id, r.date): r for r in rows}

        for e in employees:
            first_day = max(start, e.joining_date)
            last_day = min(end, exits.get(e.id, end))
            for d in daterange(first_day, last_day):
                key = (e.id, d)
                if d in locks and key in stored:
                    r = stored_result(stored[key], self.shifts)
                    # The stored status stays as locked; the names are shown from the leave data.
                    r.holiday_name = holidays.get((e.work_location_id, d)) or holidays.get((None, d))
                    if key in leave and r.status in ("on_leave", "half_day"):
                        r.leave_type_name, r.leave_days = leave[key][0], 1.0 if r.status == "on_leave" else 0.5
                    result[e.id].days[d] = r
                    continue
                shift = await self.shift_for(e.id, d, assignments)
                day_punches = punches.get(key, [])
                fix = approved.get(key)
                if fix:
                    day_punches = apply_correction(day_punches, fix.requested_in, fix.requested_out)
                r = calculate_day(
                    d, shift, day_punches, now, self.tz, policies.settings(d), overtime_eligible=e.overtime_policy_id is not None,
                    corrected=fix is not None, pending_correction=key in pending, event_warnings=tuple(warnings.get(key, ())),
                )
                holiday = holidays.get((e.work_location_id, d)) if e.work_location_id else None
                r = apply_leave_and_holiday(r, d, shift, leave=leave.get(key), holiday_name=holiday or holidays.get((None, d)))
                if r is not None:
                    result[e.id].days[d] = r
        return result


async def leave_and_holidays(session: AsyncSession, employees: list[Employee], start: date, end: date) -> tuple[dict, dict]:
    """Approved leave by (employee, charged date) -> (type name, portion), and holidays by
    (work location or None for company-wide, date) -> name (Module 6)."""
    from app.models.leave_model import Holiday, LeaveRequest, LeaveType

    ids = [e.id for e in employees]
    leave: dict[tuple, tuple[str, str]] = {}
    rows = (await session.execute(
        select(LeaveRequest.employee_id, LeaveRequest.charged_dates, LeaveRequest.portion, LeaveType.name).join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .where(LeaveRequest.employee_id.in_(ids), LeaveRequest.status == "approved", LeaveRequest.from_date <= end, LeaveRequest.to_date >= start)
    )).all() if ids else []
    for emp, dates, portion, name in rows:
        for d in dates:
            if start <= d <= end:
                leave[(emp, d)] = (name, portion)
    holidays = {(h.work_location_id, h.date): h.name for h in (await session.scalars(select(Holiday).where(Holiday.date >= start, Holiday.date <= end))).all()}
    return leave, holidays


def stored_result(row: AttendanceDay, shifts: dict[uuid.UUID, Shift]) -> DayResult:
    shift = shifts.get(row.shift_id) if row.shift_id else None
    return DayResult(
        date=row.date, status=row.status, shift=shift_info(shift) if shift else None, first_in=row.first_in, last_out=row.last_out, worked_minutes=row.worked_minutes,
        late_minutes=row.late_minutes, early_exit_minutes=row.early_exit_minutes, overtime_minutes=row.overtime_minutes, beyond_shift_minutes=row.beyond_shift_minutes,
        exceptions=list(row.exceptions), warnings=list(row.warnings), corrected=row.corrected,
    )
