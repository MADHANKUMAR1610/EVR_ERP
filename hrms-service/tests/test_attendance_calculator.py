"""Module 5: the attendance calculation (pure functions). Every threshold is an HR setting; empty = off."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.attendance.calculator import Punch, Settings, ShiftInfo, apply_correction, attendance_date_for, calculate_day

TZ = ZoneInfo("Asia/Kolkata")  # any zone; the calculation works in the company zone
DAY = date(2026, 10, 14)  # a Wednesday
GEN = ShiftInfo("s1", "GEN", "General", time(9, 0), time(17, 30), False, 30, 10, (1, 2, 3, 4, 5, 6))
NIGHT = ShiftInfo("s2", "C", "Night", time(22, 0), time(6, 0), True, 30, 5, (1, 2, 3, 4, 5, 6))
LATER = datetime(2026, 10, 20, 12, 0, tzinfo=TZ)  # the day is over
OFF = Settings()


def at(h: int, m: int = 0, day: date = DAY) -> datetime:
    return datetime.combine(day, time(h, m), TZ)


def punches(*pairs):
    return [Punch(t, d, "fingerprint") for t, d in pairs]


def calc(ps, settings=OFF, shift=GEN, now=LATER, day=DAY, **kw):
    return calculate_day(day, shift, ps, now, TZ, settings, **kw)


def test_present_and_worked_minutes_without_break_deduction():
    r = calc(punches((at(9, 5), "in"), (at(17, 40), "out")))
    assert (r.status, r.worked_minutes, r.late_minutes, r.exceptions) == ("present", 515, 0, [])
    assert r.in_source == "fingerprint" and r.first_in == at(9, 5) and r.last_out == at(17, 40)


def test_break_is_deducted_only_when_hr_switches_it_on():
    r = calc(punches((at(9), "in"), (at(17, 30), "out")), Settings(deduct_break=True))
    assert r.worked_minutes == 480


def test_late_counts_from_the_end_of_the_shift_grace():
    r = calc(punches((at(9, 25), "in"), (at(17, 30), "out")))
    assert r.status == "late" and r.late_minutes == 15 and r.exceptions == ["late_arrival"]
    assert calc(punches((at(9, 10), "in"), (at(17, 30), "out"))).status == "present", "within grace"


def test_early_exit():
    r = calc(punches((at(9), "in"), (at(16, 30), "out")))
    assert r.early_exit_minutes == 60 and "early_exit" in r.exceptions and r.status == "present"


def test_absent_and_not_started():
    assert calc([]).status == "absent" and calc([]).exceptions == ["absent"]
    today_morning = at(8, 0)
    assert calc([], now=today_morning).status == "not_started"


def test_missing_punch_only_after_the_shift_ends_today():
    r = calc(punches((at(9), "in")))
    assert r.status == "missing_punch" and r.exceptions == ["missing_out"] and "missing_punch" in r.warnings
    in_progress = calc(punches((at(9), "in")), now=at(12))
    assert in_progress.status == "present" and in_progress.exceptions == [], "E-Q1: not an exception before the shift ends"
    assert calc(punches((at(17, 30), "out"))).exceptions[0] == "missing_in"


def test_half_day_and_absent_thresholds_apply_only_when_set():
    short = punches((at(9), "in"), (at(12), "out"))  # 180 minutes
    assert calc(short).status == "present"
    assert calc(short, Settings(half_day_below=240)).status == "half_day"
    assert calc(short, Settings(absent_below=200, half_day_below=240)).status == "absent"


def test_weekly_off_from_shift_working_days():
    sunday = date(2026, 10, 18)
    assert calc([], day=sunday).status == "weekly_off"
    worked = calc(punches((at(10, day=sunday), "in"), (at(14, day=sunday), "out")), day=sunday)
    assert worked.status == "weekly_off" and worked.worked_minutes == 240


def test_no_shift():
    assert calc([], shift=None) is None, "no shift and no punches: no record"
    assert calc(punches((at(9), "in"), (at(17), "out")), shift=None).status == "present"


def test_overtime_only_when_switched_on_and_eligible():
    long_day = punches((at(9), "in"), (at(19, 47), "out"))  # 647 min; shift 510 -> 137 beyond
    assert calc(long_day).beyond_shift_minutes == 137 and calc(long_day).overtime_minutes == 0
    on = Settings(calculate_overtime=True)
    assert calc(long_day, on).overtime_minutes == 0, "not eligible without an overtime policy"
    assert calc(long_day, on, overtime_eligible=True).overtime_minutes == 137
    assert calc(long_day, Settings(calculate_overtime=True, ot_rounding=30), overtime_eligible=True).overtime_minutes == 120
    assert calc(long_day, Settings(calculate_overtime=True, ot_cap=60), overtime_eligible=True).overtime_minutes == 60
    assert calc(long_day, Settings(calculate_overtime=True, ot_minimum=150), overtime_eligible=True).overtime_minutes == 0


def test_overnight_shift_and_punch_dates():
    r = calc(punches((at(22, 0), "in"), (at(6, 5, DAY + timedelta(days=1)), "out")), shift=NIGHT)
    assert r.status == "present" and r.worked_minutes == 485
    shift_on = lambda d: NIGHT  # noqa: E731
    assert attendance_date_for(at(5, 55, DAY + timedelta(days=1)), TZ, shift_on) == DAY, "E-Q2: belongs to the start date"
    assert attendance_date_for(at(21, 50, DAY + timedelta(days=1)), TZ, shift_on) == DAY + timedelta(days=1)
    assert attendance_date_for(at(10, 0), TZ, lambda d: GEN) == DAY


def test_corrections_replace_the_corrected_direction():
    ps = punches((at(9, 40), "in"), (at(17, 35), "out"))
    fixed = apply_correction(ps, at(9, 0), None)
    r = calc(fixed, corrected=True)
    assert r.status == "present" and r.in_source == "correction" and r.out_source == "fingerprint" and r.corrected
    assert "pending_correction" in calc(ps, pending_correction=True).exceptions
