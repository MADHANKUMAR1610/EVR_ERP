"""The attendance calculation for one employee and one date. Pure functions, no database.

Rules (MODULE_5_DECISIONS.md; every threshold is an HR setting that starts empty and is then not applied):
- No shift for the date: a day exists only if there are punches (status present, no lateness).
- Not a working day of the shift: weekly_off (punches, if any, are still shown and measured).
- No accepted punch: not_started while the shift has not ended today (E1), otherwise absent.
- Only an in or only an out: still in progress before the shift end today (E-Q1), otherwise
  missing_punch with missing_in / missing_out.
- Worked minutes = last out - first in, minus the shift break only when `deductBreak` is on.
- Late: first in after shift start + the shift's grace minutes; late minutes count from the end of grace.
- Early exit: last out before the shift end, once the day is over.
- absentBelowMinutes / halfDayBelowMinutes (when set) turn a complete day into absent / half_day.
- Overtime: time beyond the shift, only when `calculateOvertime` is on and the employee has an
  overtime policy; then minimumMinutes, roundingMinutes (down) and maxMinutesPerDay apply when set.
- An approved correction replaces the punches of the direction(s) it corrects ("corrected").
- Leave and holidays (Module 6, `apply_leave_and_holiday`, applied after the calculation):
  approved full-day leave on a charged date -> on_leave; approved half-day leave -> half_day with
  the leave type (L25; lateness is not counted for a first-half leave, early exit not for a
  second-half leave, and no absence is reported); a holiday -> holiday (it takes precedence over a
  weekly off). Leave takes precedence over a holiday. Punches stay visible and measured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ShiftInfo:
    id: str
    code: str
    name: str
    start: time
    end: time
    overnight: bool
    break_minutes: int
    grace_minutes: int
    working_days: tuple[int, ...]

    def window(self, day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
        start = datetime.combine(day, self.start, tz)
        end = datetime.combine(day + timedelta(days=1) if self.overnight else day, self.end, tz)
        return start, end


@dataclass(frozen=True)
class Punch:
    at: datetime
    direction: str  # in | out
    source: str  # fingerprint | mobile_app | correction
    device_name: str | None = None
    event_id: str | None = None


@dataclass(frozen=True)
class Settings:
    deduct_break: bool = False
    half_day_below: int | None = None
    absent_below: int | None = None
    calculate_overtime: bool = False
    ot_minimum: int | None = None
    ot_rounding: int | None = None
    ot_cap: int | None = None


@dataclass
class DayResult:
    date: date
    status: str
    shift: ShiftInfo | None
    first_in: datetime | None = None
    last_out: datetime | None = None
    in_source: str | None = None
    out_source: str | None = None
    worked_minutes: int | None = None
    late_minutes: int = 0
    early_exit_minutes: int = 0
    overtime_minutes: int = 0
    beyond_shift_minutes: int = 0
    exceptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    corrected: bool = False
    pending_correction: bool = False
    punches: list[Punch] = field(default_factory=list)
    leave_type_name: str | None = None
    holiday_name: str | None = None
    leave_days: float = 0.0

    @property
    def sources(self) -> list[str]:
        return sorted({p.source for p in self.punches})


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def apply_correction(punches: list[Punch], requested_in: datetime | None, requested_out: datetime | None) -> list[Punch]:
    """An approved correction replaces the punches of each direction it corrects."""
    kept = [p for p in punches if not ((p.direction == "in" and requested_in) or (p.direction == "out" and requested_out))]
    if requested_in:
        kept.append(Punch(requested_in, "in", "correction"))
    if requested_out:
        kept.append(Punch(requested_out, "out", "correction"))
    return sorted(kept, key=lambda p: p.at)


def calculate_day(
    day: date,
    shift: ShiftInfo | None,
    punches: list[Punch],
    now: datetime,
    tz: ZoneInfo,
    settings: Settings,
    *,
    overtime_eligible: bool = False,
    corrected: bool = False,
    pending_correction: bool = False,
    event_warnings: tuple[str, ...] = (),
) -> DayResult | None:
    punches = sorted(punches, key=lambda p: p.at)
    ins = [p for p in punches if p.direction == "in"]
    outs = [p for p in punches if p.direction == "out"]
    first = ins[0] if ins else None
    last = outs[-1] if outs else None
    result = DayResult(date=day, status="present", shift=shift, punches=punches, corrected=corrected, pending_correction=pending_correction, warnings=sorted(set(event_warnings)))
    if first:
        result.first_in, result.in_source = first.at, first.source
    if last:
        result.last_out, result.out_source = last.at, last.source
    if first and last and last.at > first.at:
        worked = _minutes(last.at - first.at)
        if settings.deduct_break and shift:
            worked = max(0, worked - shift.break_minutes)
        result.worked_minutes = worked
    if pending_correction:
        result.exceptions.append("pending_correction")

    if shift is None:
        return result if punches else None
    start, end = shift.window(day, tz)
    if day.isoweekday() not in shift.working_days:
        result.status = "weekly_off"
        return result

    day_over = now >= end
    if not punches:
        result.status = "not_started" if not day_over else "absent"
        if result.status == "absent":
            result.exceptions.insert(0, "absent")
        return result

    if first and first.at > start + timedelta(minutes=shift.grace_minutes):
        result.late_minutes = _minutes(first.at - (start + timedelta(minutes=shift.grace_minutes)))
        result.exceptions.insert(0, "late_arrival")
    if (not first or not last) and day_over:
        result.status = "missing_punch"
        result.exceptions.insert(0, "missing_in" if not first else "missing_out")
        if "missing_punch" not in result.warnings:
            result.warnings.append("missing_punch")
        return result
    if not first or not last:  # still in progress today (E-Q1)
        result.status = "late" if result.late_minutes else "present"
        return result

    if day_over and last.at < end:
        result.early_exit_minutes = _minutes(end - last.at)
        result.exceptions.append("early_exit")
    planned = _minutes(end - start) - (shift.break_minutes if settings.deduct_break else 0)
    worked = result.worked_minutes or 0
    result.beyond_shift_minutes = max(0, worked - planned)
    if settings.calculate_overtime and overtime_eligible:
        ot = result.beyond_shift_minutes
        if settings.ot_minimum and ot < settings.ot_minimum:
            ot = 0
        if settings.ot_rounding:
            ot -= ot % settings.ot_rounding
        if settings.ot_cap is not None:
            ot = min(ot, settings.ot_cap)
        result.overtime_minutes = ot

    if settings.absent_below and worked < settings.absent_below:
        result.status = "absent"
        result.exceptions.insert(0, "absent")
    elif settings.half_day_below and worked < settings.half_day_below:
        result.status = "half_day"
    elif result.late_minutes:
        result.status = "late"
    return result


def attendance_date_for(at: datetime, tz: ZoneInfo, shift_on: callable) -> date:
    """Which date a punch belongs to (E-Q2: an overnight shift's punches belong to its start date).

    A punch after midnight belongs to the previous day when that day's shift is overnight and the
    punch is closer to that shift's end than to the start of the current day's shift.
    """
    local = at.astimezone(tz)
    today = local.date()
    previous = today - timedelta(days=1)
    prev_shift = shift_on(previous)
    if prev_shift and prev_shift.overnight:
        _, prev_end = prev_shift.window(previous, tz)
        current = shift_on(today)
        next_start = current.window(today, tz)[0] if current else prev_end + timedelta(hours=24)
        if local <= prev_end + (next_start - prev_end) / 2:
            return previous
    return today


def apply_leave_and_holiday(result: DayResult | None, day: date, shift: ShiftInfo | None, *, leave: tuple[str, str] | None, holiday_name: str | None) -> DayResult | None:
    """Overlays approved leave (type name, portion) and the holiday of the date on a calculated day."""
    if leave is None and holiday_name is None:
        return result
    if result is None:
        if leave is None:
            return None  # no shift and no punches: no attendance is expected, holiday or not
        result = DayResult(date=day, status="on_leave", shift=shift)
    keep = [x for x in result.exceptions if x == "pending_correction"]
    result.holiday_name = holiday_name
    if leave is not None:
        type_name, portion = leave
        result.leave_type_name = type_name
        if portion == "full":
            result.status, result.exceptions, result.late_minutes, result.early_exit_minutes, result.leave_days = "on_leave", keep, 0, 0, 1.0
            return result
        result.leave_days = 0.5
        drop = {"absent"} | ({"late_arrival"} if portion == "first_half" else {"early_exit"})
        result.exceptions = [x for x in result.exceptions if x not in drop]
        if portion == "first_half":
            result.late_minutes = 0
        else:
            result.early_exit_minutes = 0
        if result.status != "not_started":
            result.status = "half_day"
        return result
    result.status, result.exceptions, result.late_minutes, result.early_exit_minutes = "holiday", keep, 0, 0
    return result
