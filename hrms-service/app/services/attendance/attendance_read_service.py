"""Attendance screens: summary, daily register and detail, monthly register and detail, calendar, export.

Access (contract E, A4, H1):
- registers and the summary: hr.attendance:view, limited to the caller's organizational scope (Module 2);
- one employee's day, month or calendar: hr.attendance:view with the employee in scope, or the
  caller's own record (hr.self:view), or a direct report for managers (hr.approvals:act).
  Outside that: 403 for the calendar (H1 says so), 404 elsewhere (A4).
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ForbiddenError, NotFoundError, ValidationFailedError
from app.core.permissions import P, has_permission
from app.models.attendance_model import AttendanceCorrection, AttendanceDevice, AttendanceEvent
from app.models.department_model import Department
from app.models.designation_model import Designation
from app.models.employee_model import Employee
from app.models.reference_data_model import WorkLocation
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import text_match
from app.schemas.attendance_schema import (
    AttendanceEventDetailOut,
    AttendanceEventOut,
    CalendarDayOut,
    CalendarEmployeeOut,
    CalendarOut,
    CalendarSummaryOut,
    DailyDetailOut,
    DailyRecordOut,
    DepartmentAttendanceOut,
    EmployeeRefOut,
    MonthlyDayOut,
    MonthlyDetailOut,
    MonthlyRowOut,
    PunchOut,
    ShiftRefOut,
    SummaryOut,
)
from app.schemas.common import Page, PageParams
from app.schemas.employee_schema import NamedRefOut
from app.services.attendance.attendance_data import AttendanceData, company_tz
from app.services.attendance.calculator import DayResult
from app.services.attendance.correction_view import correction_out
from app.services.audit_service import AuditService
from app.services.employee_import_service import safe_cell
from app.services.employee_scope_service import EmployeeScopeService, caller_employee_id
from app.services.employee_support import Caller, company_today, parse_date
from app.utils.ids import body_id

DAILY_SORTS = ("employee", "status", "firstIn", "workedMinutes", "lateMinutes")
MONTHLY_SORTS = ("employee", "present", "absent", "late", "missingPunches", "workedMinutes", "overtimeMinutes")
# "Most serious first" for the summary's exceptions (O2, pending HR).
SEVERITY = {"missing_punch": 0, "absent": 1, "half_day": 2, "late": 3}


def employee_ref(e: Employee, departments: dict[uuid.UUID, str]) -> EmployeeRefOut:
    return EmployeeRefOut(id=str(e.id), employee_code=e.employee_code, full_name=e.full_name, department=NamedRefOut(id=str(e.department_id), name=departments.get(e.department_id, "")))


def shift_ref(r: DayResult) -> ShiftRefOut | None:
    s = r.shift
    return ShiftRefOut(id=s.id, code=s.code, name=s.name, start=s.start.strftime("%H:%M"), end=s.end.strftime("%H:%M"), overnight=s.overnight) if s else None


def day_out(e: Employee, r: DayResult, departments: dict) -> DailyRecordOut:
    return DailyRecordOut(
        id=f"{e.id}:{r.date.isoformat()}", employee=employee_ref(e, departments), date=r.date.isoformat(), shift=shift_ref(r), status=r.status, first_in=r.first_in, last_out=r.last_out,
        worked_minutes=r.worked_minutes, late_minutes=r.late_minutes, early_exit_minutes=r.early_exit_minutes, overtime_minutes=r.overtime_minutes, exceptions=r.exceptions,
        corrected=r.corrected, leave_type_name=r.leave_type_name, holiday_name=r.holiday_name, in_source=r.in_source, out_source=r.out_source, warnings=r.warnings,
    )


def month_bounds(month: str | None) -> tuple[date, date]:
    try:
        first = date.fromisoformat(f"{month}-01") if month and len(month) == 7 else None
    except ValueError:
        first = None
    if first is None:
        raise ValidationFailedError(details=[{"field": "month", "message": "Enter the month as YYYY-MM."}])
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first, last


def _sort(field: str, allowed: tuple) -> tuple[str, bool]:
    name, _, direction = field.partition(":")
    direction = direction or "asc"
    if name not in allowed or direction not in ("asc", "desc"):
        raise BadRequestError(f"Sorting by '{field}' is not supported.", details=[{"field": "sort", "message": f"Use one of: {', '.join(allowed)} with :asc or :desc."}])
    return name, direction == "desc"


class AttendanceReadService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.data = AttendanceData(session)
        self.scope_clause = EmployeeScopeService.clause(caller.scope)
        self.audit = AuditService(session)

    async def _devices(self) -> dict:
        locations = {w.id: w.name for w in (await self.session.scalars(select(WorkLocation))).all()}
        return {d.id: (d, locations.get(d.work_location_id)) for d in (await self.session.scalars(select(AttendanceDevice))).all()}

    async def _departments(self) -> dict[uuid.UUID, str]:
        return {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}

    async def employees(self, *, on: date | None = None, q: str | None = None, department_id: str | None = None, until: date | None = None) -> list[Employee]:
        """Employees in the caller's scope who had joined by `until` (records start at joining)."""
        stmt = select(Employee).where(self.scope_clause)
        if until:
            stmt = stmt.where(Employee.joining_date <= until)
        if q:
            stmt = stmt.where(text_match(q))
        if department_id:
            dep = body_id(department_id)
            if dep is None:
                return []
            stmt = stmt.where(Employee.department_id == dep)
        return list((await self.session.scalars(stmt.order_by(func.lower(Employee.full_name), Employee.employee_code))).all())

    async def employee_for_detail(self, employee_id: uuid.UUID, *, forbidden_status: int = 404) -> Employee:
        employee = await self.session.get(Employee, employee_id)
        allowed = False
        if employee is not None:
            if has_permission(self.caller.principal.permissions, P.ATTENDANCE_VIEW):
                allowed = await self.session.scalar(select(Employee.id).where(Employee.id == employee.id, self.scope_clause)) is not None
            me = caller_employee_id(self.caller.principal)
            if not allowed and me == employee.id and has_permission(self.caller.principal.permissions, P.SELF_VIEW):
                allowed = True
            if not allowed and me and employee.reporting_manager_id == me and has_permission(self.caller.principal.permissions, P.APPROVALS_ACT):
                allowed = True
        if not allowed:
            if forbidden_status == 403 and employee is not None:
                raise ForbiddenError()
            raise NotFoundError()
        return employee

    # ---- Daily ------------------------------------------------------------------------------------------

    def _date(self, raw: str | None, field: str = "date") -> date:
        try:
            d = parse_date(raw)
        except ValueError:
            d = None
        if d is None:
            raise ValidationFailedError(details=[{"field": field, "message": "Enter the date as YYYY-MM-DD."}])
        if d > company_today():
            raise ValidationFailedError(details=[{"field": field, "message": "The date cannot be in the future."}])
        return d

    async def _day_records(self, day: date, employees: list[Employee]) -> list[tuple[Employee, DayResult]]:
        computed = await self.data.compute(employees, day, day)
        return [(e, computed[e.id].days[day]) for e in employees if day in computed[e.id].days]

    async def daily(self, params: PageParams, *, day: str | None, department_id: str | None, shift_id: str | None, status: str | None, exceptions_only: bool, source: str | None, warnings_only: bool) -> Page:
        d = self._date(day)
        field, desc = _sort(params.sort or "employee:asc", DAILY_SORTS)
        rows = await self._day_records(d, await self.employees(q=params.q, department_id=department_id, until=d))
        if shift_id:
            rows = [(e, r) for e, r in rows if r.shift and r.shift.id == shift_id]
        if status:
            rows = [(e, r) for e, r in rows if r.status == status]
        if exceptions_only:
            rows = [(e, r) for e, r in rows if r.exceptions]
        if source:
            rows = [(e, r) for e, r in rows if source in (r.in_source, r.out_source)]
        if warnings_only:
            rows = [(e, r) for e, r in rows if r.warnings]
        keys = {
            "employee": lambda x: x[0].full_name.lower(), "status": lambda x: x[1].status, "firstIn": lambda x: x[1].first_in or datetime.max.replace(tzinfo=UTC),
            "workedMinutes": lambda x: x[1].worked_minutes or 0, "lateMinutes": lambda x: x[1].late_minutes,
        }
        rows.sort(key=lambda x: (keys[field](x), x[0].employee_code), reverse=desc)
        departments = await self._departments()
        start = (params.page - 1) * params.page_size
        page = rows[start : start + params.page_size]
        return Page.build(PageResult(page, params.page, params.page_size, len(rows)), [day_out(e, r, departments) for e, r in page])

    async def daily_detail(self, employee_id: uuid.UUID, day: str | None) -> DailyDetailOut:
        employee = await self.employee_for_detail(employee_id)
        d = self._date(day)
        result = (await self.data.compute([employee], d, d))[employee.id].days.get(d)
        if result is None:
            raise NotFoundError("There is no attendance record for this date.")
        departments = await self._departments()
        base = day_out(employee, result, departments)
        corrections = (await self.session.scalars(select(AttendanceCorrection).where(AttendanceCorrection.employee_id == employee.id, AttendanceCorrection.date == d).order_by(AttendanceCorrection.created_at))).all()
        events = (await self.session.scalars(select(AttendanceEvent).where(AttendanceEvent.employee_id == employee.id, AttendanceEvent.attendance_date == d).order_by(AttendanceEvent.at))).all()
        devices = await self._devices()
        return DailyDetailOut(
            **base.model_dump(),
            punches=[PunchOut(at=p.at, direction=p.direction, source=p.source, device_name=p.device_name, event_id=p.event_id) for p in result.punches],
            corrections=[await correction_out(self.session, c, employee, departments) for c in corrections],
            events=[event_out(ev, employee, departments, devices) for ev in events],
        )

    async def summary(self, day: str | None) -> SummaryOut:
        d = self._date(day)
        employees = await self.employees(until=d)
        rows = await self._day_records(d, employees)
        departments = await self._departments()
        count = lambda *statuses: sum(1 for _, r in rows if r.status in statuses)  # noqa: E731
        by_dept: dict[uuid.UUID, DepartmentAttendanceOut] = {}
        for e, r in rows:
            item = by_dept.setdefault(e.department_id, DepartmentAttendanceOut(department=NamedRefOut(id=str(e.department_id), name=departments.get(e.department_id, "")), expected=0, present=0, late=0, absent=0, on_leave=0, missing_punches=0))
            if r.status not in ("weekly_off", "holiday"):
                item.expected += 1
            item.present += r.status in ("present", "late", "missing_punch")
            item.late += r.status == "late"
            item.absent += r.status == "absent"
            item.missing_punches += r.status == "missing_punch"
        exceptions = sorted([(e, r) for e, r in rows if r.status in SEVERITY], key=lambda x: (SEVERITY[x[1].status], x[0].full_name.lower()))[:8]
        ids = [e.id for e in employees]
        pending = await self.session.scalar(select(func.count()).select_from(AttendanceCorrection).where(AttendanceCorrection.status == "pending", AttendanceCorrection.employee_id.in_(ids))) if ids else 0
        recent = (await self.session.scalars(select(AttendanceCorrection).where(AttendanceCorrection.employee_id.in_(ids)).order_by(AttendanceCorrection.created_at.desc()).limit(5))).all() if ids else []
        by_id = {e.id: e for e in employees}
        return SummaryOut(
            date=d.isoformat(), active_employees=len(rows), present=count("present", "late", "missing_punch"), absent=count("absent"), late=count("late"), on_leave=count("on_leave"),
            missing_punches=count("missing_punch"), weekly_off_or_holiday=count("weekly_off", "holiday"), not_started=count("not_started"), pending_corrections=pending or 0,
            by_department=sorted(by_dept.values(), key=lambda x: x.department.name.lower()), exceptions=[day_out(e, r, departments) for e, r in exceptions],
            recent_corrections=[await correction_out(self.session, c, by_id[c.employee_id], departments) for c in recent], as_of=datetime.now(UTC),
        )

    # ---- Monthly and calendar ------------------------------------------------------------------------------

    @staticmethod
    def _totals(e: Employee, month: str, days: dict[date, DayResult], ref: EmployeeRefOut) -> MonthlyRowOut:
        rs = days.values()
        return MonthlyRowOut(
            employee=ref, month=month, present=sum(r.status in ("present", "late", "missing_punch") for r in rs), absent=sum(r.status == "absent" for r in rs), leave=sum(r.leave_days for r in rs),
            weekly_off=sum(r.status == "weekly_off" for r in rs), holiday=sum(r.status == "holiday" for r in rs), late=sum(r.status == "late" for r in rs),
            missing_punches=sum(r.status == "missing_punch" for r in rs), worked_minutes=sum(r.worked_minutes or 0 for r in rs), overtime_minutes=sum(r.overtime_minutes for r in rs),
        )

    async def _month(self, employees: list[Employee], month: str) -> dict:
        first, last = month_bounds(month)
        if first > company_today():
            raise ValidationFailedError(details=[{"field": "month", "message": "The month cannot be in the future."}])
        return await self.data.compute(employees, first, last)

    async def monthly(self, params: PageParams, *, month: str | None, department_id: str | None) -> Page:
        field, desc = _sort(params.sort or "employee:asc", MONTHLY_SORTS)
        first, last = month_bounds(month)
        employees = await self.employees(q=params.q, department_id=department_id, until=last)
        computed = await self._month(employees, month)
        departments = await self._departments()
        rows = [self._totals(e, month, computed[e.id].days, employee_ref(e, departments)) for e in employees]
        keys = {"employee": lambda r: r.employee.full_name.lower(), "present": lambda r: r.present, "absent": lambda r: r.absent, "late": lambda r: r.late,
                "missingPunches": lambda r: r.missing_punches, "workedMinutes": lambda r: r.worked_minutes, "overtimeMinutes": lambda r: r.overtime_minutes}
        rows.sort(key=lambda r: (keys[field](r), r.employee.employee_code), reverse=desc)
        start = (params.page - 1) * params.page_size
        return Page.build(PageResult(rows[start : start + params.page_size], params.page, params.page_size, len(rows)), rows[start : start + params.page_size])

    async def monthly_detail(self, employee_id: uuid.UUID, month: str | None) -> MonthlyDetailOut:
        employee = await self.employee_for_detail(employee_id)
        computed = await self._month([employee], month)
        departments = await self._departments()
        days = computed[employee.id].days
        totals = self._totals(employee, month, days, employee_ref(employee, departments))
        return MonthlyDetailOut(**totals.model_dump(), days=[
            MonthlyDayOut(date=r.date.isoformat(), status=r.status, first_in=r.first_in, last_out=r.last_out, worked_minutes=r.worked_minutes, exceptions=r.exceptions,
                          corrected=r.corrected, leave_type_name=r.leave_type_name, holiday_name=r.holiday_name) for r in sorted(days.values(), key=lambda x: x.date)
        ])

    async def calendar(self, employee_id: uuid.UUID, month: str | None) -> CalendarOut:
        employee = await self.employee_for_detail(employee_id, forbidden_status=403)
        computed = await self._month([employee], month)
        departments = await self._departments()
        designation = await self.session.get(Designation, employee.designation_id)
        days = sorted(computed[employee.id].days.values(), key=lambda r: r.date)
        pending = sum(1 for r in days if r.pending_correction)
        worked = [r.worked_minutes for r in days if r.worked_minutes is not None]
        summary = CalendarSummaryOut(
            present_days=sum(r.status in ("present", "late", "missing_punch") for r in days), absent_days=sum(r.status == "absent" for r in days),
            late_arrivals=sum(r.status == "late" for r in days), half_days=sum(r.status == "half_day" for r in days), approved_leave_days=sum(r.leave_days for r in days),
            weekly_offs=sum(r.status == "weekly_off" for r in days), holidays=sum(r.status == "holiday" for r in days), missing_punch_days=sum(r.status == "missing_punch" for r in days),
            pending_corrections=pending, worked_minutes=sum(worked) if worked else None,
        )
        ref = employee_ref(employee, departments)
        return CalendarOut(
            employee=CalendarEmployeeOut(**ref.model_dump(), designation=designation.name if designation else None, joining_date=employee.joining_date.isoformat()),
            month=month, summary=summary, as_of=datetime.now(UTC),
            days=[CalendarDayOut(
                date=r.date.isoformat(), status=r.status, shift=shift_ref(r), first_in=r.first_in, last_out=r.last_out, worked_minutes=r.worked_minutes, late_minutes=r.late_minutes,
                overtime_minutes=r.overtime_minutes, exceptions=r.exceptions, corrected=r.corrected, pending_correction=r.pending_correction, leave_type_name=r.leave_type_name, holiday_name=r.holiday_name,
                sources=r.sources, warnings=r.warnings,
            ) for r in days],
        )

    async def export(self, *, month: str | None, department_id: str | None, q: str | None, employee_id: str | None, fmt: str) -> tuple[bytes, str, str]:
        first, last = month_bounds(month)
        if employee_id:
            employee = await self.employee_for_detail(body_id(employee_id) or uuid.uuid4())
            employees = [employee]
        else:
            employees = await self.employees(q=(q or "").strip() or None, department_id=department_id, until=last)
        computed = await self._month(employees, month)
        departments = await self._departments()
        header = ["Employee ID", "Name", "Department", "Present", "Absent", "Leave", "Weekly off", "Holiday", "Late", "Missing punches", "Worked hours", "Overtime hours"]
        lines = []
        for e in employees:
            t = self._totals(e, month, computed[e.id].days, employee_ref(e, departments))
            lines.append([e.employee_code, e.full_name, t.employee.department.name, t.present, t.absent, t.leave, t.weekly_off, t.holiday, t.late, t.missing_punches,
                          round(t.worked_minutes / 60, 2), round(t.overtime_minutes / 60, 2)])
        self.audit.record(module="Attendance", action="attendance.exported", summary=f"Monthly attendance {month} exported ({len(lines)} employee(s))")
        await self.session.commit()
        name = f"attendance-{month}"
        if fmt == "xlsx":
            wb = Workbook()
            wb.active.title = month
            wb.active.append(header)
            for line in lines:
                wb.active.append([safe_cell(v) if isinstance(v, str) else v for v in line])
            out = io.BytesIO()
            wb.save(out)
            return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{name}.xlsx"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(header)
        for line in lines:
            writer.writerow([safe_cell(v) if isinstance(v, str) else v for v in line])
        return ("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"{name}.csv"

    # ---- Events -------------------------------------------------------------------------------------------

    async def events(self, params: PageParams, *, day: str | None, department_id: str | None, employee_id: str | None, source: str | None, sync_status: str | None, exceptions: str | None) -> Page:
        d = self._date(day)
        employees = {e.id: e for e in await self.employees(q=params.q, department_id=department_id)}
        stmt = select(AttendanceEvent).where(AttendanceEvent.attendance_date == d)
        if employee_id:
            stmt = stmt.where(AttendanceEvent.employee_id == body_id(employee_id))
        stmt = stmt.where(AttendanceEvent.employee_id.in_(list(employees)))
        if source:
            stmt = stmt.where(AttendanceEvent.source == source)
        if sync_status:
            stmt = stmt.where(AttendanceEvent.sync_status == sync_status)
        if exceptions == "with":
            stmt = stmt.where((AttendanceEvent.exception.is_not(None)) | (func.cardinality(AttendanceEvent.warnings) > 0))
        elif exceptions == "without":
            stmt = stmt.where(AttendanceEvent.exception.is_(None), func.cardinality(AttendanceEvent.warnings) == 0)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self.session.scalars(stmt.order_by(AttendanceEvent.at.desc(), AttendanceEvent.id).limit(params.page_size).offset((params.page - 1) * params.page_size))).all()
        departments = await self._departments()
        devices = await self._devices()
        return Page.build(PageResult(rows, params.page, params.page_size, total), [event_out(ev, employees[ev.employee_id], departments, devices) for ev in rows])

    async def event(self, event_id: uuid.UUID) -> AttendanceEventDetailOut:
        ev = await self.session.get(AttendanceEvent, event_id)
        if ev is None or ev.employee_id is None:
            raise NotFoundError()
        employee = await self.session.scalar(select(Employee).where(Employee.id == ev.employee_id, self.scope_clause))
        if employee is None:
            raise NotFoundError()
        departments = await self._departments()
        devices = await self._devices()
        record = None
        if ev.attendance_date:
            r = (await self.data.compute([employee], ev.attendance_date, ev.attendance_date))[employee.id].days.get(ev.attendance_date)
            record = day_out(employee, r, departments) if r else None
        return AttendanceEventDetailOut(**event_out(ev, employee, departments, devices).model_dump(), record=record)


def event_out(ev: AttendanceEvent, employee: Employee, departments: dict, devices: dict) -> AttendanceEventOut:
    """`devices`: id -> (device, location name). Location is the device's configured office location (H2)."""
    device, location = devices.get(ev.device_id, (None, None)) if ev.device_id else (None, None)
    return AttendanceEventOut(
        id=str(ev.id), employee=employee_ref(employee, departments), attendance_date=(ev.attendance_date or ev.at.astimezone(company_tz()).date()).isoformat(), at=ev.at,
        direction=ev.direction, source=ev.source, device_id=str(ev.device_id) if ev.device_id else None, device_name=device.name if device else None, app_reference=ev.app_reference,
        location=location or None, received_at=ev.received_at, sync_status=ev.sync_status, processing_status=ev.processing_status, exception=ev.exception,
        original_event_id=str(ev.original_event_id) if ev.original_event_id else None, original_reference=ev.original_reference, warnings=list(ev.warnings or []),
        mobile_validation=None,
    )
