"""Reports (Module 9, contract Part F; MODULE_9_DECISIONS.md).

Every report builds ALL its matching rows from the module data (organizational scope applied); this service
then sorts, pages, totals and exports them, so a page, its totals and the export always agree.
No figure is invented: the definitions are those of the contract (F-Q1, pending confirmation).
"""

from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Awaitable, Callable

from openpyxl import Workbook
from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ForbiddenError, NotFoundError, ValidationFailedError
from app.core.permissions import P
from app.models.department_model import Department
from app.models.designation_model import Designation
from app.models.employee_document_model import EmployeeDocument
from app.models.employee_model import Employee
from app.models.leave_model import LeaveRequest, LeaveType, OvertimeRequest
from app.models.payroll_model import PayrollPeriod, PayrollPeriodEvent, PayrollResult, Payslip
from app.models.reference_data_model import DocumentType, EmploymentType, EmployeeStatus, WorkLocation
from app.models.report_model import ReportActivity
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import ACTIVE, text_match
from app.schemas.common import PageMeta
from app.schemas.employee_schema import NamedRefOut
from app.schemas.report_schema import (
    AttendanceTrendOut,
    HeadcountOut,
    MetricOut,
    MonthMetricOut,
    PayrollCostMetricOut,
    PayrollCostTrendOut,
    ReportActivityOut,
    ReportColumnOut,
    ReportDefinitionOut,
    ReportRefOut,
    ReportResultOut,
    ReportsDashboardOut,
    YearMetricOut,
)
from app.services.attendance.attendance_data import AttendanceData, company_tz
from app.services.audit_service import AuditService
from app.services.document_compliance_service import DocumentComplianceService
from app.services.employee_import_service import safe_cell
from app.services.employee_scope_service import EmployeeScopeService
from app.services.employee_support import Caller, company_today, parse_date
from app.services.leave.balance_service import BalanceService
from app.services.leave.calendar import leave_year_of, leave_year_start_month
from app.services.payroll.common import month_label
from app.utils.ids import body_id

MAX_ATTENDANCE_DAYS = 92
CALCULATED = ("calculated", "submitted", "approved", "payslips_published")
DAY_STATUS = {"present": "Present", "late": "Late", "absent": "Absent", "half_day": "Half day", "missing_punch": "Missing punch", "on_leave": "On leave",
              "weekly_off": "Weekly off", "holiday": "Holiday", "not_started": "Not started"}
REQUEST_STATUS = {"pending": "Pending", "approved": "Approved", "rejected": "Rejected", "cancelled": "Cancelled"}
PERIOD_STATUS = {"open": "Open", "validated": "Validated", "calculated": "Calculated", "submitted": "Submitted", "approved": "Approved", "rejected": "Sent back", "payslips_published": "Payslips published"}
DOC_STATUS = {"documents_pending": "Documents pending", "awaiting_verification": "Awaiting verification", "complete": "Complete"}
TYPE_LABEL = {"earning": "Earning", "deduction": "Deduction", "employer_contribution": "Employer contribution"}
PRESENT = ("present", "late", "missing_punch")


@dataclass
class Params:
    q: str | None = None
    department_id: str | None = None
    date: str | None = None
    from_: str | None = None
    to: str | None = None
    month: str | None = None
    year: int | None = None
    period_id: str | None = None
    leave_type_id: str | None = None
    status: str | None = None


@dataclass
class Built:
    columns: list[ReportColumnOut]
    rows: list[dict]
    totals: dict | None = None
    notes: list[str] = field(default_factory=list)
    currency: str | None = None


@dataclass(frozen=True)
class Report:
    id: str
    category: str
    title: str
    description: str
    filters: tuple[str, ...]
    default_sort: str
    needs: tuple[str, ...]  # every one of these permissions
    builder: str


def col(key, label, type_="text", sortable=True, priority=None) -> ReportColumnOut:
    return ReportColumnOut(key=key, label=label, type=type_, sortable=sortable, priority=priority)


EMP_COLS = [col("employeeCode", "Employee ID", "code", priority="primary"), col("employee", "Employee", priority="primary"), col("department", "Department", priority="secondary")]
HR, ATT, LV, PAY = (P.REPORTS_VIEW, P.EMPLOYEES_VIEW), (P.REPORTS_VIEW, P.ATTENDANCE_VIEW), (P.REPORTS_VIEW, P.LEAVE_VIEW), (P.REPORTS_PAYROLL_VIEW, P.PAYROLL_VIEW_AMOUNTS)
RANGE_ATT = ("dateRange", "department", "search")

REPORTS: dict[str, Report] = {r.id: r for r in [
    Report("employee_directory", "hr", "Employee directory", "Employees with department, designation, type, status and joining date.", ("department", "search"), "employee:asc", HR, "employee_directory"),
    Report("headcount_by_department", "hr", "Headcount by department", "Employees in employment per department.", ("department",), "department:asc", HR, "headcount"),
    Report("joiners_exits", "hr", "Joiners and exits", "Employees who joined or left in the date range (exit dates from the status change).", ("dateRange", "department", "search"), "date:asc", HR, "joiners_exits"),
    Report("employment_type", "hr", "Employees by employment type", "Employees in employment per employment type.", ("department",), "employmentType:asc", HR, "employment_type"),
    Report("document_completion", "hr", "Document completion", "Required documents completed and verified per employee.", ("department", "search"), "employee:asc", (*HR, P.DOCUMENTS_VIEW), "document_completion"),
    Report("missing_documents", "hr", "Missing documents", "Required documents not yet completed, one row per employee and document.", ("department", "search"), "employee:asc", (*HR, P.DOCUMENTS_VIEW), "missing_documents"),
    Report("expiring_documents", "hr", "Expiring documents", "Documents whose expiry date falls in the range (default: the next 60 days).", ("dateRange", "department", "search"), "expiryDate:asc", (*HR, P.DOCUMENTS_VIEW), "expiring_documents"),
    Report("daily_attendance", "attendance", "Daily attendance", "Status, punches, worked time and overtime of every employee on a date.", ("date", "department", "search"), "employee:asc", ATT, "daily_attendance"),
    Report("monthly_attendance", "attendance", "Monthly attendance", "Monthly totals per employee.", ("month", "department", "search"), "employee:asc", ATT, "monthly_attendance"),
    Report("department_attendance", "attendance", "Department attendance", "Monthly totals and attendance rate per department.", ("month", "department"), "department:asc", ATT, "department_attendance"),
    Report("late_early", "attendance", "Late arrivals and early exits", "Late arrivals and early exits per employee in the range.", RANGE_ATT, "lateDays:desc", ATT, "late_early"),
    Report("absenteeism", "attendance", "Absenteeism", "Absent days and absence rate per employee in the range.", RANGE_ATT, "absentDays:desc", ATT, "absenteeism"),
    Report("overtime_summary", "attendance", "Overtime summary", "Calculated overtime and overtime requests per employee in the range.", RANGE_ATT, "overtimeMinutes:desc", (*ATT, P.OVERTIME_VIEW), "overtime_summary"),
    Report("missing_punch", "attendance", "Missing punches", "Days with a missing in or out punch in the range.", RANGE_ATT, "date:asc", ATT, "missing_punch"),
    Report("leave_utilisation_employee", "leave", "Leave utilisation by employee", "Days used against allocated and carried forward, per employee and leave type with a balance.", ("year", "leaveType", "department", "search"), "utilisation:desc", (*LV, P.LEAVE_BALANCES_VIEW), "utilisation_employee"),
    Report("leave_utilisation_department", "leave", "Leave utilisation by department", "Days used against allocated and carried forward, per department and leave type.", ("year", "leaveType", "department"), "department:asc", (*LV, P.LEAVE_BALANCES_VIEW), "utilisation_department"),
    Report("leave_balance", "leave", "Leave balances", "Allocated, carried forward, used, pending and available days.", ("year", "leaveType", "department", "search"), "employee:asc", (*LV, P.LEAVE_BALANCES_VIEW), "leave_balance"),
    Report("leave_history", "leave", "Leave history", "Leave requests in the range (default: the current year).", ("dateRange", "leaveType", "requestStatus", "department", "search"), "from:desc", LV, "leave_history"),
    Report("upcoming_leave", "leave", "Upcoming leave", "Approved leave starting in the range (default: the next 30 days).", ("dateRange", "leaveType", "department", "search"), "from:asc", LV, "upcoming_leave"),
    Report("payroll_summary", "payroll", "Payroll summary", "Gross, deductions, net and employer contributions per employee.", ("period", "department", "search"), "employee:asc", PAY, "payroll_summary"),
    Report("payroll_department_cost", "payroll", "Payroll cost by department", "Payroll cost (gross + employer contributions) per department.", ("period", "department"), "department:asc", PAY, "payroll_department_cost"),
    Report("earnings_deductions", "payroll", "Earnings and deductions", "Totals per salary component.", ("period", "department"), "type:asc", PAY, "earnings_deductions"),
    Report("lop_summary", "payroll", "Loss of pay summary", "Days in period, paid days, loss of pay and leave per employee.", ("period", "department", "search"), "lossOfPayDays:desc", (P.REPORTS_PAYROLL_VIEW, P.PAYROLL_VIEW), "lop_summary"),
    Report("processing_status", "payroll", "Payroll processing status", "Every payroll period with its status and last step.", (), "month:desc", (P.REPORTS_PAYROLL_VIEW, P.PAYROLL_VIEW), "processing_status"),
    Report("payslip_register", "payroll", "Payslip register", "Published payslips of a period.", ("period", "department", "search"), "employee:asc", PAY, "payslip_register"),
]}


def _f(v) -> float:
    return float(Decimal(str(v)))


def _pct(num, den) -> float | None:
    return round(float(num) * 100 / float(den), 1) if den else None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _sum(rows: list[dict], keys: list[str]) -> dict:
    return {k: round(sum((r.get(k) or 0) for r in rows), 2) for k in keys}


class ReportService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.audit = AuditService(session)
        self.tz = company_tz()
        self._depts: dict | None = None

    # ---- Catalogue and access ------------------------------------------------------------------------------------

    def allowed(self, r: Report) -> bool:
        return all(self.caller.has(code) for code in r.needs)

    def catalog(self) -> list[ReportDefinitionOut]:
        return [ReportDefinitionOut(id=r.id, category=r.category, title=r.title, description=r.description, filters=list(r.filters), formats=["csv", "xlsx"], default_sort=r.default_sort)
                for r in REPORTS.values() if self.allowed(r)]

    def _report(self, report_id: str) -> Report:
        r = REPORTS.get(report_id)
        if r is None:
            raise NotFoundError("This report does not exist.")
        if not self.allowed(r):
            raise ForbiddenError()
        return r

    # ---- Shared data -----------------------------------------------------------------------------------------------

    async def depts(self) -> dict[uuid.UUID, str]:
        if self._depts is None:
            self._depts = {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}
        return self._depts

    async def employees(self, p: Params, *, active: bool = False, until: date | None = None, search: bool = True) -> list[Employee]:
        stmt = select(Employee).where(EmployeeScopeService.clause(self.caller.scope))
        if active:
            stmt = stmt.where(ACTIVE)
        if until:
            stmt = stmt.where(Employee.joining_date <= until)
        if search and p.q:
            stmt = stmt.where(text_match(p.q))
        if p.department_id:
            stmt = stmt.where(Employee.department_id == body_id(p.department_id)) if body_id(p.department_id) else stmt.where(false())
        return list((await self.session.scalars(stmt.order_by(Employee.employee_code))).all())

    async def emp(self, e: Employee) -> dict:
        return {"employeeCode": e.employee_code, "employee": e.full_name, "department": (await self.depts()).get(e.department_id, "")}

    @staticmethod
    def _parse(value: str | None, field: str) -> date | None:
        try:
            return parse_date(value)
        except ValueError:
            raise ValidationFailedError(details=[{"field": field, "message": "Enter the date as YYYY-MM-DD."}]) from None

    def range(self, p: Params, default: tuple[date, date], *, limit: int | None = None) -> tuple[date, date]:
        start = self._parse(p.from_, "from") or default[0]
        end = self._parse(p.to, "to") or default[1]
        if end < start:
            raise ValidationFailedError(details=[{"field": "to", "message": "The range must end on or after its start."}])
        if limit and (end - start).days + 1 > limit:
            raise ValidationFailedError(details=[{"field": "to", "message": f"Choose a range of at most {limit} days."}])
        return start, end

    def att_range(self, p: Params) -> tuple[date, date]:
        today = company_today()
        return self.range(p, (today.replace(day=1), today), limit=MAX_ATTENDANCE_DAYS)

    def month(self, p: Params) -> tuple[str, date, date]:
        from app.services.attendance.attendance_read_service import month_bounds

        m = p.month or company_today().strftime("%Y-%m")
        first, last = month_bounds(m)
        if first > company_today():
            raise ValidationFailedError(details=[{"field": "month", "message": "The month cannot be in the future."}])
        return m, first, last

    async def period(self, p: Params) -> PayrollPeriod | None:
        if p.period_id:
            pid = body_id(p.period_id)
            period = await self.session.get(PayrollPeriod, pid) if pid else None
            if period is None:
                raise ValidationFailedError(details=[{"field": "periodId", "message": "Choose an existing payroll period."}])
            return period
        return await self.session.scalar(select(PayrollPeriod).where(PayrollPeriod.status.in_(CALCULATED)).order_by(PayrollPeriod.month.desc()).limit(1))

    async def results(self, period: PayrollPeriod | None, p: Params) -> list[tuple[PayrollResult, Employee]]:
        if period is None:
            return []
        ids = {e.id: e for e in await self.employees(p)}
        rows = (await self.session.scalars(select(PayrollResult).where(PayrollResult.period_id == period.id))).all()
        return [(r, ids[r.employee_id]) for r in rows if r.employee_id in ids]

    def time(self, at: datetime | None) -> str | None:
        return at.astimezone(self.tz).strftime("%H:%M") if at else None

    # ---- HR -------------------------------------------------------------------------------------------------------------

    async def employee_directory(self, p: Params) -> Built:
        employees = await self.employees(p)
        desig = {d.id: d.name for d in (await self.session.scalars(select(Designation))).all()}
        types = {t.id: t.name for t in (await self.session.scalars(select(EmploymentType))).all()}
        locs = {w.id: w.name for w in (await self.session.scalars(select(WorkLocation))).all()}
        statuses = {s.code: s.label for s in (await self.session.scalars(select(EmployeeStatus))).all()}
        rows = [{**await self.emp(e), "designation": desig.get(e.designation_id, ""), "employmentType": types.get(e.employment_type_id, ""), "status": statuses.get(e.status_code, e.status_code),
                 "joiningDate": e.joining_date.isoformat(), "workLocation": locs.get(e.work_location_id, "")} for e in employees]
        cols = [*EMP_COLS, col("designation", "Designation", priority="secondary"), col("employmentType", "Employment type", priority="detail"), col("status", "Status", "status"),
                col("joiningDate", "Joining date", "date", priority="secondary"), col("workLocation", "Work location", priority="detail")]
        return Built(cols, rows, {"employee": len(rows)})

    async def headcount(self, p: Params) -> Built:
        counts: dict[str, int] = defaultdict(int)
        for e in await self.employees(p, active=True, search=False):
            counts[(await self.depts()).get(e.department_id, "")] += 1
        rows = [{"department": d, "employees": n} for d, n in counts.items()]
        return Built([col("department", "Department", priority="primary"), col("employees", "Employees", "number", priority="primary")], rows, _sum(rows, ["employees"]),
                     ["Employees in a status not marked \"employment ended\"."])

    async def joiners_exits(self, p: Params) -> Built:
        today = company_today()
        start, end = self.range(p, (today.replace(day=1), today))
        employees = await self.employees(p)
        exits = await AttendanceData(self.session).exit_dates(employees)
        rows = []
        for e in employees:
            if start <= e.joining_date <= end:
                rows.append({**await self.emp(e), "event": "Joined", "date": e.joining_date.isoformat()})
            if e.id in exits and start <= exits[e.id] <= end:
                rows.append({**await self.emp(e), "event": "Exited", "date": exits[e.id].isoformat()})
        return Built([*EMP_COLS, col("event", "Event", "status"), col("date", "Date", "date")], rows,
                     {"employee": len(rows)}, ["Exit dates are the effective dates of the status change into a status marked \"employment ended\"."])

    async def employment_type(self, p: Params) -> Built:
        types = {t.id: t.name for t in (await self.session.scalars(select(EmploymentType))).all()}
        counts: dict[str, int] = defaultdict(int)
        for e in await self.employees(p, active=True, search=False):
            counts[types.get(e.employment_type_id, "")] += 1
        rows = [{"employmentType": t, "employees": n} for t, n in counts.items()]
        return Built([col("employmentType", "Employment type", priority="primary"), col("employees", "Employees", "number", priority="primary")], rows, _sum(rows, ["employees"]))

    async def _compliance(self, p: Params):
        rows, types, window = await DocumentComplianceService(self.session, self.caller)._rows(q=p.q, department_id=p.department_id)
        return rows, types

    async def document_completion(self, p: Params) -> Built:
        rows, _ = await self._compliance(p)
        out = [{"employeeCode": r.out.employee_code, "employee": r.out.full_name, "department": r.out.department.name, "required": r.result.required_count, "completed": r.result.completed_count,
                "verified": r.result.verified_count, "awaitingVerification": r.result.awaiting_verification_count, "completion": _pct(r.result.completed_count, r.result.required_count),
                "status": DOC_STATUS[r.result.status]} for r in rows]
        total_req, total_done = sum(r["required"] for r in out), sum(r["completed"] for r in out)
        cols = [*EMP_COLS, col("required", "Required", "number", priority="detail"), col("completed", "Completed", "number"), col("verified", "Verified", "number", priority="detail"),
                col("awaitingVerification", "Awaiting verification", "number", priority="detail"), col("completion", "Completion", "percent"), col("status", "Status", "status")]
        return Built(cols, out, {**_sum(out, ["required", "completed", "verified", "awaitingVerification"]), "completion": _pct(total_done, total_req)}, ["Employees in employment; active required document types."])

    async def missing_documents(self, p: Params) -> Built:
        rows, _ = await self._compliance(p)
        out = [{"employeeCode": r.out.employee_code, "employee": r.out.full_name, "department": r.out.department.name, "documentType": t.name} for r in rows for t in (r.result.pending_types or [])]
        return Built([*EMP_COLS, col("documentType", "Document", priority="primary")], out, {"documentType": len(out)})

    async def expiring_documents(self, p: Params) -> Built:
        today = company_today()
        start, end = self.range(p, (today, today + timedelta(days=60)))
        rows, types = await self._compliance(p)
        out = []
        for r in rows:
            for type_id, d in r.latest.items():
                if d.expiry_date and start <= d.expiry_date <= end:
                    out.append({"employeeCode": r.out.employee_code, "employee": r.out.full_name, "department": r.out.department.name, "documentType": types[type_id].name,
                                "expiryDate": d.expiry_date.isoformat(), "daysLeft": (d.expiry_date - today).days})
        return Built([*EMP_COLS, col("documentType", "Document"), col("expiryDate", "Expires", "date"), col("daysLeft", "Days left", "number")], out, {"documentType": len(out)})

    # ---- Attendance -----------------------------------------------------------------------------------------------------

    async def _days(self, p: Params, start: date, end: date):
        employees = await self.employees(p, until=end)
        return employees, await AttendanceData(self.session).compute(employees, start, end)

    async def daily_attendance(self, p: Params) -> Built:
        d = self._parse(p.date, "date") or company_today()
        if d > company_today():
            raise ValidationFailedError(details=[{"field": "date", "message": "The date cannot be in the future."}])
        employees, computed = await self._days(p, d, d)
        rows = []
        for e in employees:
            r = computed[e.id].days.get(d)
            if r is None:
                continue
            rows.append({**await self.emp(e), "shift": r.shift.code if r.shift else "", "status": DAY_STATUS.get(r.status, r.status), "firstIn": self.time(r.first_in), "lastOut": self.time(r.last_out),
                         "workedMinutes": r.worked_minutes, "lateMinutes": r.late_minutes, "overtimeMinutes": r.overtime_minutes})
        cols = [*EMP_COLS, col("shift", "Shift", "code", priority="detail"), col("status", "Status", "status", priority="primary"), col("firstIn", "In", "time"), col("lastOut", "Out", "time"),
                col("workedMinutes", "Worked", "minutes"), col("lateMinutes", "Late", "minutes", priority="detail"), col("overtimeMinutes", "Overtime", "minutes", priority="detail")]
        return Built(cols, rows, _sum(rows, ["workedMinutes", "lateMinutes", "overtimeMinutes"]), [f"Attendance on {d.isoformat()}, from the punches, approved corrections, shifts and approved leave."])

    @staticmethod
    def _month_totals(days) -> dict:
        rs = list(days.values())
        return {"present": sum(r.status in PRESENT for r in rs), "absent": sum(r.status == "absent" for r in rs), "leave": sum(r.leave_days for r in rs),
                "weeklyOff": sum(r.status == "weekly_off" for r in rs), "holiday": sum(r.status == "holiday" for r in rs), "late": sum(r.status == "late" for r in rs),
                "missingPunches": sum(r.status == "missing_punch" for r in rs), "workedMinutes": sum(r.worked_minutes or 0 for r in rs), "overtimeMinutes": sum(r.overtime_minutes for r in rs)}

    MONTH_KEYS = ["present", "absent", "leave", "weeklyOff", "holiday", "late", "missingPunches", "workedMinutes", "overtimeMinutes"]

    async def monthly_attendance(self, p: Params) -> Built:
        m, first, last = self.month(p)
        employees, computed = await self._days(p, first, last)
        rows = [{**await self.emp(e), **self._month_totals(computed[e.id].days)} for e in employees]
        cols = [*EMP_COLS, col("present", "Present", "number"), col("absent", "Absent", "number"), col("leave", "Leave", "number"), col("weeklyOff", "Weekly off", "number", priority="detail"),
                col("holiday", "Holiday", "number", priority="detail"), col("late", "Late", "number", priority="detail"), col("missingPunches", "Missing punches", "number", priority="detail"),
                col("workedMinutes", "Worked", "minutes"), col("overtimeMinutes", "Overtime", "minutes", priority="detail")]
        return Built(cols, rows, _sum(rows, self.MONTH_KEYS), [f"{month_label(m)}, up to today. Late arrivals and missing punches count as present."])

    async def department_attendance(self, p: Params) -> Built:
        m, first, last = self.month(p)
        employees, computed = await self._days(p, first, last)
        agg: dict[str, dict] = {}
        for e in employees:
            name = (await self.depts()).get(e.department_id, "")
            a = agg.setdefault(name, {"department": name, "employees": 0, "present": 0, "absent": 0, "leave": 0.0})
            t = self._month_totals(computed[e.id].days)
            a["employees"] += 1
            a["present"] += t["present"]
            a["absent"] += t["absent"]
            a["leave"] += t["leave"]
        rows = [{**a, "attendanceRate": _pct(a["present"], a["present"] + a["absent"])} for a in agg.values()]
        totals = _sum(rows, ["employees", "present", "absent", "leave"])
        totals["attendanceRate"] = _pct(totals["present"], totals["present"] + totals["absent"])
        cols = [col("department", "Department", priority="primary"), col("employees", "Employees", "number"), col("present", "Present days", "number"), col("absent", "Absent days", "number"),
                col("leave", "Leave days", "number", priority="detail"), col("attendanceRate", "Attendance rate", "percent", priority="primary")]
        return Built(cols, rows, totals, ["Attendance rate = present ÷ (present + absent), completed days only (pending confirmation, F-Q1)."])

    async def late_early(self, p: Params) -> Built:
        start, end = self.att_range(p)
        employees, computed = await self._days(p, start, end)
        rows = []
        for e in employees:
            rs = computed[e.id].days.values()
            rows.append({**await self.emp(e), "lateDays": sum(r.late_minutes > 0 for r in rs), "lateMinutes": sum(r.late_minutes for r in rs),
                         "earlyExitDays": sum(r.early_exit_minutes > 0 for r in rs), "earlyExitMinutes": sum(r.early_exit_minutes for r in rs)})
        cols = [*EMP_COLS, col("lateDays", "Late days", "number"), col("lateMinutes", "Late", "minutes"), col("earlyExitDays", "Early exit days", "number"), col("earlyExitMinutes", "Early exits", "minutes")]
        return Built(cols, rows, _sum(rows, ["lateDays", "lateMinutes", "earlyExitDays", "earlyExitMinutes"]), [f"{start.isoformat()} to {end.isoformat()}; grace periods from the shifts."])

    async def absenteeism(self, p: Params) -> Built:
        start, end = self.att_range(p)
        employees, computed = await self._days(p, start, end)
        rows = []
        for e in employees:
            rs = list(computed[e.id].days.values())
            present, absent = sum(r.status in PRESENT for r in rs), sum(r.status == "absent" for r in rs)
            rows.append({**await self.emp(e), "presentDays": present, "absentDays": absent, "absenceRate": _pct(absent, present + absent)})
        totals = _sum(rows, ["presentDays", "absentDays"])
        totals["absenceRate"] = _pct(totals["absentDays"], totals["presentDays"] + totals["absentDays"])
        return Built([*EMP_COLS, col("presentDays", "Present days", "number"), col("absentDays", "Absent days", "number"), col("absenceRate", "Absence rate", "percent")], rows, totals,
                     [f"{start.isoformat()} to {end.isoformat()}. Absence rate = absent ÷ (present + absent)."])

    async def overtime_summary(self, p: Params) -> Built:
        start, end = self.att_range(p)
        employees, computed = await self._days(p, start, end)
        ids = [e.id for e in employees]
        requests = defaultdict(lambda: {"approved": 0, "pending": 0})
        if ids:
            for emp, minutes, status in (await self.session.execute(select(OvertimeRequest.employee_id, OvertimeRequest.minutes, OvertimeRequest.status)
                                                                    .where(OvertimeRequest.employee_id.in_(ids), OvertimeRequest.date >= start, OvertimeRequest.date <= end, OvertimeRequest.status.in_(("approved", "pending"))))).all():
                requests[emp][status] += minutes
        rows = [{**await self.emp(e), "overtimeMinutes": sum(r.overtime_minutes for r in computed[e.id].days.values()), "approvedMinutes": requests[e.id]["approved"],
                 "pendingMinutes": requests[e.id]["pending"]} for e in employees]
        rows = [r for r in rows if r["overtimeMinutes"] or r["approvedMinutes"] or r["pendingMinutes"]]
        cols = [*EMP_COLS, col("overtimeMinutes", "Calculated overtime", "minutes"), col("approvedMinutes", "Approved requests", "minutes"), col("pendingMinutes", "Pending requests", "minutes")]
        return Built(cols, rows, _sum(rows, ["overtimeMinutes", "approvedMinutes", "pendingMinutes"]), ["Calculated overtime follows the HR overtime policy; payroll pays approved requests only."])

    async def missing_punch(self, p: Params) -> Built:
        start, end = self.att_range(p)
        employees, computed = await self._days(p, start, end)
        rows = []
        for e in employees:
            for d, r in sorted(computed[e.id].days.items()):
                if r.status == "missing_punch":
                    rows.append({**await self.emp(e), "date": d.isoformat(), "missing": "Missing in" if "missing_in" in r.exceptions else "Missing out",
                                 "firstIn": self.time(r.first_in), "lastOut": self.time(r.last_out)})
        cols = [*EMP_COLS, col("date", "Date", "date"), col("missing", "Missing", "status"), col("firstIn", "In", "time", priority="detail"), col("lastOut", "Out", "time", priority="detail")]
        return Built(cols, rows, {"date": len(rows)})

    # ---- Leave -----------------------------------------------------------------------------------------------------------

    async def _year(self, p: Params) -> int:
        return p.year or leave_year_of(company_today(), await leave_year_start_month(self.session))

    async def _balances(self, p: Params, *, search: bool = True):
        year = await self._year(p)
        employees = await self.employees(p, search=search)
        lt = body_id(p.leave_type_id) if p.leave_type_id else None
        if p.leave_type_id and lt is None:
            raise ValidationFailedError(details=[{"field": "leaveTypeId", "message": "Choose an existing leave type."}])
        out = []
        for row in await BalanceService(self.session, self.caller)._rows(employees, year):
            for b in row.balances:
                if lt and b.leave_type.id != str(lt):
                    continue
                out.append((row.employee, b))
        return year, out

    async def utilisation_employee(self, p: Params) -> Built:
        year, items = await self._balances(p)
        rows = [{"employeeCode": e.employee_code, "employee": e.full_name, "department": e.department.name, "leaveType": b.leave_type.name, "allocated": b.allocated, "carriedForward": b.carried_forward,
                 "used": b.used, "utilisation": _pct(b.used, (b.allocated or 0) + b.carried_forward)} for e, b in items if b.allocated is not None]
        totals = _sum(rows, ["allocated", "carriedForward", "used"])
        totals["utilisation"] = _pct(totals["used"], totals["allocated"] + totals["carriedForward"])
        cols = [*EMP_COLS, col("leaveType", "Leave type"), col("allocated", "Allocated", "number"), col("carriedForward", "Carried forward", "number", priority="detail"), col("used", "Used", "number"),
                col("utilisation", "Utilisation", "percent")]
        return Built(cols, rows, totals, [f"Leave year {year}. Utilisation = used ÷ (allocated + carried forward), leave types with a balance (pending confirmation, F-Q1)."])

    async def utilisation_department(self, p: Params) -> Built:
        year, items = await self._balances(p, search=False)
        agg: dict[tuple, dict] = {}
        for e, b in items:
            if b.allocated is None:
                continue
            a = agg.setdefault((e.department.name, b.leave_type.name), {"department": e.department.name, "leaveType": b.leave_type.name, "employees": 0, "allocated": 0.0, "carriedForward": 0.0, "used": 0.0})
            a["employees"] += 1
            a["allocated"] += b.allocated
            a["carriedForward"] += b.carried_forward
            a["used"] += b.used
        rows = [{**a, "utilisation": _pct(a["used"], a["allocated"] + a["carriedForward"])} for a in agg.values()]
        totals = _sum(rows, ["employees", "allocated", "carriedForward", "used"])
        totals["utilisation"] = _pct(totals["used"], totals["allocated"] + totals["carriedForward"])
        cols = [col("department", "Department", priority="primary"), col("leaveType", "Leave type"), col("employees", "Employees", "number", priority="detail"), col("allocated", "Allocated", "number"),
                col("carriedForward", "Carried forward", "number", priority="detail"), col("used", "Used", "number"), col("utilisation", "Utilisation", "percent", priority="primary")]
        return Built(cols, rows, totals, [f"Leave year {year}."])

    async def leave_balance(self, p: Params) -> Built:
        year, items = await self._balances(p)
        rows = [{"employeeCode": e.employee_code, "employee": e.full_name, "department": e.department.name, "leaveType": b.leave_type.name, "allocated": b.allocated, "carriedForward": b.carried_forward,
                 "used": b.used, "pending": b.pending, "available": b.available} for e, b in items]
        cols = [*EMP_COLS, col("leaveType", "Leave type"), col("allocated", "Allocated", "number"), col("carriedForward", "Carried forward", "number", priority="detail"), col("used", "Used", "number"),
                col("pending", "Pending", "number", priority="detail"), col("available", "Available", "number", priority="primary")]
        return Built(cols, rows, _sum(rows, ["allocated", "carriedForward", "used", "pending", "available"]), [f"Leave year {year}. Leave types without a balance show no allocated or available days."])

    async def _requests(self, p: Params, start: date, end: date, *, statuses: tuple[str, ...] | None, starting: bool) -> list[dict]:
        employees = {e.id: e for e in await self.employees(p)}
        if not employees:
            return []
        stmt = select(LeaveRequest, LeaveType.name).join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id).where(LeaveRequest.employee_id.in_(employees))
        stmt = stmt.where(LeaveRequest.from_date >= start, LeaveRequest.from_date <= end) if starting else stmt.where(LeaveRequest.from_date <= end, LeaveRequest.to_date >= start)
        if statuses:
            stmt = stmt.where(LeaveRequest.status.in_(statuses))
        if p.leave_type_id:
            lt = body_id(p.leave_type_id)
            stmt = stmt.where(LeaveRequest.leave_type_id == lt) if lt else stmt.where(false())
        rows = []
        for r, type_name in (await self.session.execute(stmt)).all():
            rows.append({**await self.emp(employees[r.employee_id]), "leaveType": type_name, "from": r.from_date.isoformat(), "to": r.to_date.isoformat(), "days": _f(r.days),
                         "status": REQUEST_STATUS[r.status], "appliedAt": r.created_at.isoformat()})
        return rows

    LEAVE_COLS = [*EMP_COLS, col("leaveType", "Leave type"), col("from", "From", "date"), col("to", "To", "date"), col("days", "Days", "number"), col("status", "Status", "status")]

    async def leave_history(self, p: Params) -> Built:
        today = company_today()
        start, end = self.range(p, (today.replace(month=1, day=1), today.replace(month=12, day=31)))
        if p.status and p.status not in REQUEST_STATUS:
            raise ValidationFailedError(details=[{"field": "status", "message": "Use pending, approved, rejected or cancelled."}])
        rows = await self._requests(p, start, end, statuses=(p.status,) if p.status else None, starting=False)
        return Built([*self.LEAVE_COLS, col("appliedAt", "Applied", "datetime", priority="detail")], rows, _sum(rows, ["days"]), [f"Requests overlapping {start.isoformat()} to {end.isoformat()}."])

    async def upcoming_leave(self, p: Params) -> Built:
        today = company_today()
        start, end = self.range(p, (today, today + timedelta(days=30)))
        rows = await self._requests(p, start, end, statuses=("approved",), starting=True)
        return Built(self.LEAVE_COLS, rows, _sum(rows, ["days"]), [f"Approved leave starting {start.isoformat()} to {end.isoformat()}."])

    # ---- Payroll ---------------------------------------------------------------------------------------------------------

    def _no_period(self, cols) -> Built:
        return Built(cols, [], None, ["No payroll period has been calculated yet."])

    async def payroll_summary(self, p: Params) -> Built:
        cols = [*EMP_COLS, col("paidDays", "Paid days", "number", priority="detail"), col("gross", "Gross", "money"), col("deductions", "Deductions", "money"), col("net", "Net", "money", priority="primary"),
                col("employerContributions", "Employer contributions", "money", priority="detail"), col("exceptions", "Exceptions", priority="detail", sortable=False)]
        period = await self.period(p)
        if period is None:
            return self._no_period(cols)
        rows = [{**await self.emp(e), "paidDays": _f(r.paid_days), "gross": _f(r.gross), "deductions": _f(r.deductions), "net": _f(r.net), "employerContributions": _f(r.employer_contributions),
                 "exceptions": ", ".join(x.replace("_", " ") for x in r.exceptions)} for r, e in await self.results(period, p) if "missing_salary" not in r.exceptions]
        return Built(cols, rows, _sum(rows, ["gross", "deductions", "net", "employerContributions"]), [f"Amounts are taken from the payroll results of {month_label(period.month)} ({PERIOD_STATUS[period.status].lower()})."], period.currency)

    async def payroll_department_cost(self, p: Params) -> Built:
        cols = [col("department", "Department", priority="primary"), col("employees", "Employees", "number"), col("gross", "Gross", "money"), col("employerContributions", "Employer contributions", "money"),
                col("cost", "Payroll cost", "money", priority="primary"), col("net", "Net", "money", priority="detail")]
        period = await self.period(p)
        if period is None:
            return self._no_period(cols)
        agg: dict[str, dict] = {}
        for r, e in await self.results(period, p):
            if "missing_salary" in r.exceptions:
                continue
            name = (await self.depts()).get(e.department_id, "")
            a = agg.setdefault(name, {"department": name, "employees": 0, "gross": 0.0, "employerContributions": 0.0, "cost": 0.0, "net": 0.0})
            a["employees"] += 1
            a["gross"] += _f(r.gross)
            a["employerContributions"] += _f(r.employer_contributions)
            a["cost"] += _f(r.gross) + _f(r.employer_contributions)
            a["net"] += _f(r.net)
        rows = [{k: round(v, 2) if isinstance(v, float) else v for k, v in a.items()} for a in agg.values()]
        return Built(cols, rows, _sum(rows, ["employees", "gross", "employerContributions", "cost", "net"]), [f"{month_label(period.month)}. Payroll cost = gross earnings + employer contributions (pending confirmation, F-Q1)."], period.currency)

    async def earnings_deductions(self, p: Params) -> Built:
        cols = [col("code", "Code", "code"), col("component", "Component", priority="primary"), col("type", "Type", "status"), col("employees", "Employees", "number", priority="detail"),
                col("amount", "Amount", "money", priority="primary")]
        period = await self.period(p)
        if period is None:
            return self._no_period(cols)
        agg: dict[str, dict] = {}
        for r, _ in await self.results(period, p):
            for x in r.lines:
                a = agg.setdefault(x["code"], {"code": x["code"], "component": x["name"], "type": TYPE_LABEL.get(x["type"], x["type"]), "employees": 0, "amount": Decimal("0")})
                a["employees"] += 1
                a["amount"] += Decimal(str(x["amount"]))
        rows = [{**a, "amount": _f(a["amount"])} for a in agg.values()]
        return Built(cols, rows, None, [f"{month_label(period.month)}. Totals per type are not added together: earnings, deductions and employer contributions differ in meaning."], period.currency)

    async def lop_summary(self, p: Params) -> Built:
        cols = [*EMP_COLS, col("daysInPeriod", "Days in period", "number", priority="detail"), col("paidDays", "Paid days", "number"), col("lossOfPayDays", "Loss of pay", "number", priority="primary"),
                col("leaveDays", "Paid leave", "number", priority="detail")]
        period = await self.period(p)
        if period is None:
            return self._no_period(cols)
        rows = [{**await self.emp(e), "daysInPeriod": _f(r.days_in_period), "paidDays": _f(r.paid_days), "lossOfPayDays": _f(r.loss_of_pay_days), "leaveDays": _f(r.leave_days)}
                for r, e in await self.results(period, p)]
        return Built(cols, rows, _sum(rows, ["lossOfPayDays", "leaveDays"]), [f"{month_label(period.month)}; loss of pay as defined by the payroll policy."])

    async def processing_status(self, p: Params) -> Built:
        periods = (await self.session.scalars(select(PayrollPeriod))).all()
        rows = []
        for period in periods:
            last = await self.session.scalar(select(PayrollPeriodEvent).where(PayrollPeriodEvent.period_id == period.id).order_by(PayrollPeriodEvent.created_at.desc(), PayrollPeriodEvent.id.desc()).limit(1))
            rows.append({"month": period.month, "period": month_label(period.month), "status": PERIOD_STATUS[period.status], "employees": period.employees_included, "calculatedAt": period.calculated_at.isoformat() if period.calculated_at else None,
                         "lastStep": (last.comment or last.action) if last else None, "lastBy": last.created_by_name if last else None, "lastAt": last.created_at.isoformat() if last else None})
        cols = [col("month", "Month", "code", priority="detail"), col("period", "Period", priority="primary"), col("status", "Status", "status", priority="primary"), col("employees", "Employees", "number"),
                col("calculatedAt", "Calculated", "datetime", priority="detail"), col("lastStep", "Last step", priority="secondary"), col("lastBy", "By", priority="detail"), col("lastAt", "At", "datetime", priority="detail")]
        return Built(cols, rows, None)

    async def payslip_register(self, p: Params) -> Built:
        cols = [*EMP_COLS, col("netPay", "Net pay", "money", priority="primary"), col("publishedAt", "Published", "datetime", priority="detail")]
        period = await self.period(p)
        if period is None:
            return self._no_period(cols)
        employees = {e.id: e for e in await self.employees(p)}
        slips = (await self.session.scalars(select(Payslip).where(Payslip.period_id == period.id))).all()
        rows = [{**await self.emp(employees[s.employee_id]), "netPay": _f(s.net_pay), "publishedAt": s.published_at.isoformat()} for s in slips if s.employee_id in employees]
        notes = [f"{month_label(period.month)}."] + ([] if period.status == "payslips_published" else ["Payslips of this period are not published yet."])
        return Built(cols, rows, _sum(rows, ["netPay"]), notes, period.currency)

    # ---- Running and exporting -------------------------------------------------------------------------------------------

    async def _build(self, r: Report, p: Params, sort: str | None) -> Built:
        built: Built = await getattr(self, r.builder)(p)
        name, _, direction = (sort or r.default_sort).partition(":")
        sortable = {c.key for c in built.columns if c.sortable}
        if name not in sortable or direction not in ("", "asc", "desc"):
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": f"Use one of {', '.join(sorted(sortable))} with :asc or :desc."}])
        present = [x for x in built.rows if x.get(name) is not None]
        empty = [x for x in built.rows if x.get(name) is None]
        present.sort(key=lambda x: (x[name].lower() if isinstance(x[name], str) else x[name], x.get("employeeCode") or ""), reverse=direction == "desc")
        built.rows = present + empty  # empty values last either way
        return built

    def _record(self, r: Report, action: str, fmt: str | None, rows: int) -> None:
        self.session.add(ReportActivity(report_id=r.id, report_title=r.title, action=action, format=fmt))
        self.audit.record(module="Reports", action=f"report.{action}", summary=f"Report {r.title} {action}{f' as {fmt.upper()}' if fmt else ''} ({rows} row(s))", entity_type="report", entity_label=r.id)

    async def run(self, report_id: str, p: Params, *, sort: str | None, page: int, page_size: int) -> ReportResultOut:
        r = self._report(report_id)
        built = await self._build(r, p, sort)
        total = len(built.rows)
        meta = PageResult([], page, page_size, total)
        if page == 1:
            self._record(r, "generated", None, total)
            await self.session.commit()
        return ReportResultOut(report=ReportRefOut(id=r.id, title=r.title), columns=built.columns, rows=built.rows[(page - 1) * page_size: page * page_size], totals=built.totals,
                               meta=PageMeta(page=meta.page, page_size=meta.page_size, total_items=meta.total_items, total_pages=meta.total_pages), currency=built.currency,
                               notes=built.notes, generated_at=_utcnow())

    async def export(self, report_id: str, p: Params, *, sort: str | None, fmt: str) -> tuple[bytes, str, str]:
        r = self._report(report_id)
        built = await self._build(r, p, sort)
        header = [c.label + (f" ({built.currency})" if c.type == "money" and built.currency else "") for c in built.columns]
        lines = [[x.get(c.key) for c in built.columns] for x in built.rows]
        if built.totals:
            lines.append([("Total" if i == 0 else built.totals.get(c.key)) if i == 0 or c.key in built.totals else None for i, c in enumerate(built.columns)])
        self._record(r, "exported", fmt, len(built.rows))
        await self.session.commit()
        name = f"{r.id}-{company_today().isoformat()}"
        if fmt == "xlsx":
            wb = Workbook()
            wb.active.title = r.title[:31]
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
            writer.writerow(["" if v is None else (safe_cell(v) if isinstance(v, str) else v) for v in line])
        return ("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"{name}.csv"

    async def activity(self, limit: int) -> list[ReportActivityOut]:
        ids = [r.id for r in REPORTS.values() if self.allowed(r)]
        rows = (await self.session.scalars(select(ReportActivity).where(ReportActivity.report_id.in_(ids)).order_by(ReportActivity.created_at.desc(), ReportActivity.id.desc()).limit(limit))).all() if ids else []
        return [ReportActivityOut(id=str(a.id), report_id=a.report_id, report_title=a.report_title, action=a.action, format=a.format, by=a.created_by_name, at=a.created_at) for a in rows]

    # ---- Dashboard --------------------------------------------------------------------------------------------------------

    async def _rate(self, employees: list[Employee], start: date, end: date) -> float | None:
        if not employees or start > company_today():
            return None
        computed = await AttendanceData(self.session).compute(employees, start, end)
        present = absent = 0
        for e in employees:
            for r in computed[e.id].days.values():
                present += r.status in PRESENT
                absent += r.status == "absent"
        return _pct(present, present + absent)

    async def dashboard(self) -> ReportsDashboardOut:
        today = company_today()
        everyone = Params()
        missing = "You do not have permission to see this figure."
        if self.caller.has(P.EMPLOYEES_VIEW):
            active = await self.employees(everyone, active=True)
            total = MetricOut(value=len(active))
            counts: dict[uuid.UUID, int] = defaultdict(int)
            for e in active:
                counts[e.department_id] += 1
            depts = await self.depts()
            headcount = sorted((HeadcountOut(department=NamedRefOut(id=str(d), name=depts.get(d, "")), count=n) for d, n in counts.items()), key=lambda h: (-h.count, h.department.name))
        else:
            total, headcount = MetricOut(value=None, unavailable_reason=missing), []
        month = today.strftime("%Y-%m")
        trend: list[AttendanceTrendOut] = []
        if self.caller.has(P.ATTENDANCE_VIEW):
            first = today.replace(day=1)
            months = []
            d = first
            for _ in range(6):
                months.append(d)
                d = (d - timedelta(days=1)).replace(day=1)
            for m in reversed(months):
                last = (m.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                employees = await self.employees(everyone, until=last)
                trend.append(AttendanceTrendOut(month=m.strftime("%Y-%m"), rate=await self._rate(employees, m, min(last, today))))
            rate = MonthMetricOut(value=trend[-1].rate, month=month)
        else:
            rate = MonthMetricOut(value=None, unavailable_reason=missing, month=month)
        year = await leave_year_of_today(self.session)
        if self.caller.has(P.LEAVE_VIEW) and self.caller.has(P.LEAVE_BALANCES_VIEW):
            _, items = await self._balances(Params(year=year))
            used = sum(b.used for _, b in items if b.allocated is not None)
            base = sum((b.allocated or 0) + b.carried_forward for _, b in items if b.allocated is not None)
            leave = YearMetricOut(value=_pct(used, base), year=year)
        else:
            leave = YearMetricOut(value=None, unavailable_reason=missing, year=year)
        latest = await self.session.scalar(select(PayrollPeriod).where(PayrollPeriod.status.in_(CALCULATED)).order_by(PayrollPeriod.month.desc()).limit(1))
        amounts = self.caller.has(P.PAYROLL_VIEW_AMOUNTS)
        scope = {e.id for e in await self.employees(everyone)}

        async def cost(period: PayrollPeriod) -> float:
            rows = (await self.session.execute(select(PayrollResult.employee_id, PayrollResult.gross, PayrollResult.employer_contributions).where(PayrollResult.period_id == period.id))).all()
            return round(sum(_f(g) + _f(c) for emp, g, c in rows if emp in scope), 2)

        if amounts:
            payroll_cost = PayrollCostMetricOut(value=await cost(latest) if latest else None, period_label=month_label(latest.month) if latest else None, currency=latest.currency if latest else "",
                                                unavailable_reason=None if latest else "No payroll period has been calculated yet.")
        else:
            payroll_cost = PayrollCostMetricOut(value=None, unavailable_reason=missing, period_label=month_label(latest.month) if latest else None, currency=latest.currency if latest else "")
        if self.caller.has(P.PAYROLL_VIEW):
            exc = sum(1 for emp, x in (await self.session.execute(select(PayrollResult.employee_id, PayrollResult.exceptions).where(PayrollResult.period_id == latest.id))).all() if x and emp in scope) if latest else 0
            exceptions = MetricOut(value=exc)
            pending = MetricOut(value=await self.session.scalar(select(func.count()).select_from(PayrollPeriod).where(PayrollPeriod.status == "submitted")) or 0)
        else:
            exceptions, pending = MetricOut(value=None, unavailable_reason=missing), MetricOut(value=None, unavailable_reason=missing)
        periods = list((await self.session.scalars(select(PayrollPeriod).where(PayrollPeriod.status.in_(CALCULATED)).order_by(PayrollPeriod.month.desc()).limit(6))).all())
        cost_trend = [PayrollCostTrendOut(month=x.month, label=month_label(x.month), cost=await cost(x) if amounts else None) for x in reversed(periods)]
        return ReportsDashboardOut(total_employees=total, attendance_rate=rate, leave_utilisation=leave, payroll_cost=payroll_cost, payroll_exceptions=exceptions, pending_payroll_approvals=pending,
                                   attendance_trend=trend, headcount_by_department=headcount, payroll_cost_trend=cost_trend, as_of=_utcnow())


async def leave_year_of_today(session: AsyncSession) -> int:
    return leave_year_of(company_today(), await leave_year_start_month(session))


BuilderFn = Callable[[ReportService, Params], Awaitable[Built]]
