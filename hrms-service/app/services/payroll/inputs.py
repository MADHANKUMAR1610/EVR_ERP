"""Payroll inputs of a period, per employee, from attendance, leave, overtime and the salary records.

Rules (MODULE_7_DECISIONS.md, "Inputs from attendance and leave"); every value that changes pay comes from
the G6 `payroll` policy in force on the day of the calculation, and nothing is guessed:
- employees included: joined on or before the last day, and not left before the first day;
- days in period: by `prorationBasis` (calendar days, the employee's working days minus holidays, or
  `fixedDaysPerMonth`); for a fixed number of days, a joiner or leaver gets that number times the share of
  calendar days employed (pending HR confirmation);
- loss of pay: approved leave of unpaid types, plus absences (1) and half days without leave (0.5) when
  `absenceIsLossOfPay` is on;
- paid days = days employed (on the basis) - loss of pay; leave days = approved paid leave;
- overtime: approved overtime requests dated in the period.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.attendance_model import AttendanceCorrection
from app.models.employee_model import Employee
from app.models.leave_model import Holiday, LeaveRequest, LeaveType, OvertimeRequest, PermissionRequest
from app.models.payroll_model import EmployeeSalary, PayrollConfiguration, PayrollPeriod, SalaryComponent, SalaryStructure
from app.services.attendance.attendance_data import AttendanceData, daterange
from app.services.attendance.policy_service import PolicyValues, policy_values_on
from app.services.employee_support import company_today
from app.services.payroll.configuration_service import PayrollConfigurationService

D0 = Decimal("0")
BASES = ("calendar_days", "working_days", "fixed_days")


@dataclass
class EmployeeInput:
    employee: Employee
    days_in_period: Decimal = D0
    employed_days: Decimal = D0
    paid_days: Decimal = D0
    loss_of_pay_days: Decimal = D0
    leave_days: Decimal = D0
    overtime_minutes: int = 0
    salary: EmployeeSalary | None = None
    structure: SalaryStructure | None = None
    config_status: str = "missing"  # resolved | missing | conflict
    configuration: PayrollConfiguration | None = None
    attendance_exceptions: int = 0
    pending_requests: int = 0
    prorated: bool = False
    unknown_calendar_days: int = 0
    components: list[SalaryComponent] = field(default_factory=list)

    @property
    def overtime_payable(self) -> bool:
        if self.configuration is not None:
            return self.configuration.overtime_eligible
        return self.employee.overtime_policy_id is not None

    def issues(self) -> list[str]:
        out = []
        if self.salary is None:
            out.append("No salary record for the period")
        if self.config_status == "conflict":
            out.append("Two payroll configurations at the same level apply")
        elif self.config_status == "missing":
            out.append("No payroll configuration applies; the salary structure is used as it is")
        if self.attendance_exceptions:
            out.append(f"{self.attendance_exceptions} attendance exception(s) in the period")
        if self.pending_requests:
            out.append(f"{self.pending_requests} request(s) in the period awaiting a decision")
        if self.prorated:
            out.append("Joined or left during the period")
        if self.unknown_calendar_days:
            out.append(f"Working days unknown on {self.unknown_calendar_days} date(s): no shift and no company working days")
        return out


@dataclass
class PeriodInputs:
    period: PayrollPeriod
    policy: PolicyValues
    basis: str | None
    fixed_days: int | None
    rows: dict[uuid.UUID, EmployeeInput]
    pending_total: int
    components: dict[uuid.UUID, SalaryComponent]

    @property
    def policy_problem(self) -> str | None:
        if self.basis not in BASES:
            return "The payroll policy does not say how the days of a period are counted (HR Policies: payroll, \"Days in a pay period\")."
        if self.basis == "fixed_days" and not self.fixed_days:
            return "The payroll policy counts a fixed number of days, but the number is not set."
        return None


def _dec(v) -> Decimal:
    return Decimal(str(v))


async def period_employees(session: AsyncSession, period: PayrollPeriod) -> tuple[list[Employee], dict[uuid.UUID, date]]:
    employees = list((await session.scalars(select(Employee).where(Employee.joining_date <= period.to_date))).all())
    exits = await AttendanceData(session).exit_dates(employees)
    employees = [e for e in employees if exits.get(e.id) is None or exits[e.id] >= period.from_date]
    return employees, exits


async def compute_inputs(session: AsyncSession, period: PayrollPeriod) -> PeriodInputs:
    policy = await policy_values_on(session, company_today())
    basis = policy.get("payroll", "prorationBasis")
    fixed = policy.get("payroll", "fixedDaysPerMonth")
    fixed = int(fixed) if fixed else None
    absence_lop = policy.on("payroll", "absenceIsLossOfPay")
    start, end = period.from_date, period.to_date
    employees, exits = await period_employees(session, period)
    ids = [e.id for e in employees]
    rows = {e.id: EmployeeInput(e) for e in employees}
    comps = {c.id: c for c in (await session.scalars(select(SalaryComponent))).all()}

    # Attendance (locked dates read their stored records).
    attendance = AttendanceData(session)
    days = await attendance.compute(employees, start, end)
    assignments = await attendance.assignments(ids)
    holidays = {(h.work_location_id, h.date) for h in (await session.scalars(select(Holiday).where(Holiday.date >= start, Holiday.date <= end))).all()}
    company_days = get_settings().company_working_days

    # Approved leave: paid -> leave days; unpaid -> loss of pay.
    leave_rows = (await session.execute(
        select(LeaveRequest.employee_id, LeaveRequest.charged_dates, LeaveRequest.portion, LeaveType.paid).join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .where(LeaveRequest.employee_id.in_(ids), LeaveRequest.status == "approved", LeaveRequest.from_date <= end, LeaveRequest.to_date >= start)
    )).all() if ids else []
    paid_leave: dict[uuid.UUID, dict[date, Decimal]] = defaultdict(dict)
    unpaid_leave: dict[uuid.UUID, dict[date, Decimal]] = defaultdict(dict)
    for emp, dates, portion, paid in leave_rows:
        share = Decimal("1") if portion == "full" else Decimal("0.5")
        for d in dates:
            if start <= d <= end:
                (paid_leave if paid else unpaid_leave)[emp][d] = share

    # Approved overtime and requests still pending in the period.
    overtime: dict[uuid.UUID, int] = defaultdict(int)
    pending: dict[uuid.UUID, int] = defaultdict(int)
    if ids:
        for emp, minutes, status in (await session.execute(select(OvertimeRequest.employee_id, OvertimeRequest.minutes, OvertimeRequest.status)
                                                           .where(OvertimeRequest.employee_id.in_(ids), OvertimeRequest.date >= start, OvertimeRequest.date <= end, OvertimeRequest.status.in_(("approved", "pending"))))).all():
            if status == "approved":
                overtime[emp] += minutes
            else:
                pending[emp] += 1
        for model, lo, hi in ((PermissionRequest, PermissionRequest.date, PermissionRequest.date), (AttendanceCorrection, AttendanceCorrection.date, AttendanceCorrection.date),
                              (LeaveRequest, LeaveRequest.from_date, LeaveRequest.to_date)):
            for (emp,) in (await session.execute(select(model.employee_id).where(model.employee_id.in_(ids), model.status == "pending", lo <= end, hi >= start))).all():
                pending[emp] += 1

    # Salary records and effective configurations on each employee's last day in the period.
    structures = {s.id: s for s in (await session.scalars(select(SalaryStructure))).all()}
    salaries = (await session.scalars(select(EmployeeSalary).where(EmployeeSalary.employee_id.in_(ids), EmployeeSalary.effective_from <= end)
                                      .order_by(EmployeeSalary.employee_id, EmployeeSalary.effective_from.desc()))).all() if ids else []
    by_employee: dict[uuid.UUID, list[EmployeeSalary]] = defaultdict(list)
    for s in salaries:
        by_employee[s.employee_id].append(s)
    config_service = PayrollConfigurationService(session)
    everything = await config_service._all_assignments()
    configs = {c.id: c for c in (await session.scalars(select(PayrollConfiguration))).all()}

    month_days = (end - start).days + 1
    for e in employees:
        row = rows[e.id]
        first = max(start, e.joining_date)
        last = min(end, exits.get(e.id, end))
        row.prorated = first > start or last < end
        employed = set(daterange(first, last))

        def working(d: date) -> bool:
            if (e.work_location_id, d) in holidays or (None, d) in holidays:
                return False
            rows_ = assignments.get(e.id, [])
            shift_id = None
            for eff, sid in rows_:
                if eff <= d:
                    shift_id = sid
            if shift_id is not None and shift_id in attendance.shifts:
                return d.isoweekday() in attendance.shifts[shift_id].working_days
            if company_days:
                return d.isoweekday() in company_days
            row.unknown_calendar_days += 1
            return True

        if basis == "working_days":
            await attendance._shifts()
            work = [d for d in daterange(start, end) if working(d)]
            row.days_in_period = Decimal(len(work))
            row.employed_days = Decimal(sum(1 for d in work if d in employed))
        elif basis == "fixed_days" and fixed:
            row.days_in_period = Decimal(fixed)
            row.employed_days = Decimal(fixed) if not row.prorated else (Decimal(fixed) * len(employed) / month_days).quantize(Decimal("0.01"))
        else:
            row.days_in_period = Decimal(month_days)
            row.employed_days = Decimal(len(employed))

        lop = sum((v for d, v in unpaid_leave.get(e.id, {}).items() if d in employed), D0)
        exceptions = 0
        for d, r in days[e.id].days.items():
            if r.status in ("absent", "missing_punch"):
                exceptions += 1
            if absence_lop and d in employed and d not in unpaid_leave.get(e.id, {}):
                if r.status == "absent":
                    lop += Decimal("1")
                elif r.status == "half_day" and not r.leave_days:
                    lop += Decimal("0.5")
        row.loss_of_pay_days = lop
        row.paid_days = max(row.employed_days - lop, D0)
        row.leave_days = sum((v for d, v in paid_leave.get(e.id, {}).items() if d in employed), D0)
        row.overtime_minutes = overtime.get(e.id, 0)
        row.attendance_exceptions = exceptions
        row.pending_requests = pending.get(e.id, 0)

        salary = next(iter(s for s in by_employee.get(e.id, []) if s.effective_from <= last), None)
        row.salary = salary
        row.structure = structures.get(salary.structure_id) if salary else None
        status, chosen, _ = await config_service.resolve(e, last, everything)
        row.config_status = status
        row.configuration = configs.get(chosen.configuration_id) if chosen else None
        if row.structure is not None:
            allowed = set(row.configuration.component_ids) if row.configuration is not None and row.configuration.component_ids else None
            row.components = [comps[cid] for cid in row.structure.component_ids if cid in comps and comps[cid].active and (allowed is None or cid in allowed)]

    return PeriodInputs(period=period, policy=policy, basis=basis, fixed_days=fixed, rows=rows, pending_total=sum(pending.values()), components=comps)
