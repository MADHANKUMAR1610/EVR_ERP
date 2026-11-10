"""Payroll periods (contract E4): list, summary, validation, inputs, calculation, results and the workflow.

open -> validated -> calculated -> submitted -> approved -> payslips_published; rejected returns to validation.
- Validation runs the checks, discards earlier results and moves the period to `validated` (to `open` while a
  check is blocking).
- Calculation is synchronous; it re-runs the checks and refuses (422) while any is blocking.
- Approval needs a different person from the submitter unless the G6 setting `allowSelfApproval` is on, and a
  period that has ended; it stores and locks the period's attendance. Rejection needs a reason.
- Publication creates the payslips. Approved and published periods never change.
Calculation covers every employee in the period; the lists follow the caller's organizational scope.
Amounts are null without hr.payroll:view-amounts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ForbiddenError, InvalidTransitionError, NotFoundError, PeriodLockedError, ValidationFailedError
from app.models.attendance_model import AttendanceLockPeriod
from app.models.employee_model import Employee
from app.models.payroll_model import PayrollPeriod, PayrollPeriodEvent, PayrollResult, Payslip
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import text_match
from app.schemas.payroll_schema import (
    ComponentRefOut,
    MoneyOut,
    PayrollInputRowOut,
    PayrollPeriodOut,
    PayrollResultDetailOut,
    PayrollResultRowOut,
    PeriodDecisionIn,
    PeriodSummaryOut,
    ResultLineOut,
    ResultsPageOut,
    SubmissionIn,
    ValidationCheckOut,
    ValidationResultOut,
    ValidationWithPeriodOut,
    VersionIn,
)
from app.schemas.common import Page
from app.services.attendance.attendance_read_service import employee_ref
from app.services.attendance.jobs import store_days
from app.services.audit_service import AuditService
from app.services.employee_scope_service import EmployeeScopeService
from app.services.employee_support import Caller, company_today
from app.services.payroll.common import FINALIZED, MODULE, amt, can_amounts, component_def, departments, period_out
from app.services.payroll.engine import calculate, incomplete
from app.services.payroll.inputs import EmployeeInput, PeriodInputs, compute_inputs
from app.services.payroll.setup_service import PayrollSetupService
from app.utils.ids import body_id
from app.utils.validation import ensure_version

LINKS = {
    "payroll_policy": "/admin/policies", "components": "/hr/payroll/salary-structure", "configuration_conflict": "/hr/payroll/assignments",
    "missing_salary": "/hr/payroll/salaries", "missing_configuration": "/hr/payroll/assignments", "attendance_exceptions": "/hr/attendance/monthly",
    "pending_requests": "/hr/approvals", "working_calendar": "/hr/shifts",
}
RESULT_SORTS = ("employee", "employeeCode", "paidDays", "gross", "net")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _check(code: str, label: str, blocking: bool, count: int, detail_ok: str, detail: str) -> ValidationCheckOut:
    status = "passed" if count == 0 else ("blocking" if blocking else "warning")
    return ValidationCheckOut(code=code, label=label, status=status, count=count, detail=detail_ok if count == 0 else detail, link=None if count == 0 else LINKS[code])


def _num(v) -> float:
    return float(v)


class PayrollPeriodService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.audit = AuditService(session)
        self.amounts = can_amounts(caller)

    # ---- Helpers --------------------------------------------------------------------------------------------

    async def _period(self, period_id: uuid.UUID, *, for_update: bool = False) -> PayrollPeriod:
        stmt = select(PayrollPeriod).where(PayrollPeriod.id == period_id)
        if for_update:
            stmt = stmt.with_for_update()
        p = await self.session.scalar(stmt)
        if p is None:
            raise NotFoundError()
        return p

    def _event(self, p: PayrollPeriod, action: str, comment: str | None) -> None:
        self.session.add(PayrollPeriodEvent(period_id=p.id, action=action, comment=comment))

    async def _in_scope(self) -> set[uuid.UUID]:
        return set((await self.session.scalars(select(Employee.id).where(EmployeeScopeService.clause(self.caller.scope)))).all())

    async def _finish(self, p: PayrollPeriod, action: str, summary: str) -> PayrollPeriodOut:
        await self.session.flush()
        self.audit.record(module=MODULE, action=f"payroll_period.{action}", summary=summary, entity_type="payroll_period", entity_id=p.id, entity_label=p.month)
        await self.session.commit()
        await self.session.refresh(p)
        return await period_out(self.session, p)

    @staticmethod
    def _require(p: PayrollPeriod, allowed: tuple[str, ...], action: str) -> None:
        if p.status in FINALIZED and p.status not in allowed:
            raise PeriodLockedError(f"The {p.month} payroll is {p.status.replace('_', ' ')} and can no longer change.")
        if p.status not in allowed:
            raise InvalidTransitionError(f"A period in status '{p.status}' cannot be {action}.")

    # ---- Lists ---------------------------------------------------------------------------------------------------

    async def periods(self) -> list[PayrollPeriodOut]:
        rows = (await self.session.scalars(select(PayrollPeriod).order_by(PayrollPeriod.month.desc()))).all()
        return [await period_out(self.session, p) for p in rows]

    async def _results(self, p: PayrollPeriod) -> list[PayrollResult]:
        return list((await self.session.scalars(select(PayrollResult).where(PayrollResult.period_id == p.id))).all())

    def _money(self, rows: list[PayrollResult]) -> MoneyOut:
        rows = [r for r in rows if "missing_salary" not in r.exceptions]
        if not self.amounts:
            return MoneyOut(gross=None, deductions=None, net=None)
        return MoneyOut(gross=_num(sum((r.gross for r in rows), Decimal("0"))), deductions=_num(sum((r.deductions for r in rows), Decimal("0"))), net=_num(sum((r.net for r in rows), Decimal("0"))))

    async def summary(self, period_id: uuid.UUID) -> PeriodSummaryOut:
        p = await self._period(period_id)
        scope = await self._in_scope()
        results = [r for r in await self._results(p) if r.employee_id in scope]
        if results:
            needing = sum(1 for r in results if r.exceptions)
            missing = sum(1 for r in results if "missing_salary" in r.exceptions)
            attendance = sum(1 for r in results if "attendance_exceptions" in r.exceptions)
            included = len(results)
        else:
            inputs = await compute_inputs(self.session, p)
            rows = [r for r in inputs.rows.values() if r.employee.id in scope]
            needing = sum(1 for r in rows if r.salary is None or r.attendance_exceptions or r.pending_requests or r.config_status != "resolved" or r.prorated)
            missing = sum(1 for r in rows if r.salary is None)
            attendance = sum(1 for r in rows if r.attendance_exceptions)
            included = len(rows)
        pending = await self._pending_in_scope(p, scope)
        return PeriodSummaryOut(period=await period_out(self.session, p), employees_included=included, needing_review=needing, missing_salary=missing, attendance_exceptions=attendance,
                                pending_approvals=pending, totals=self._money(results) if results and self.amounts else None, as_of=_utcnow())

    async def _pending_in_scope(self, p: PayrollPeriod, scope: set[uuid.UUID]) -> int:
        from app.models.attendance_model import AttendanceCorrection
        from app.models.leave_model import LeaveRequest, OvertimeRequest, PermissionRequest

        total = 0
        ids = list(scope)
        if not ids:
            return 0
        for model, lo, hi in ((PermissionRequest, PermissionRequest.date, PermissionRequest.date), (OvertimeRequest, OvertimeRequest.date, OvertimeRequest.date),
                              (AttendanceCorrection, AttendanceCorrection.date, AttendanceCorrection.date), (LeaveRequest, LeaveRequest.from_date, LeaveRequest.to_date)):
            total += await self.session.scalar(select(func.count()).select_from(model).where(model.employee_id.in_(ids), model.status == "pending", lo <= p.to_date, hi >= p.from_date)) or 0
        return total

    # ---- Validation ---------------------------------------------------------------------------------------------

    @staticmethod
    def checks(inputs: PeriodInputs) -> list[ValidationCheckOut]:
        rows = list(inputs.rows.values())
        problem = inputs.policy_problem
        component_issues: set[str] = set()
        for r in rows:
            if r.salary is None or r.config_status == "conflict":
                continue
            for c in r.components:
                why = incomplete(component_def(c))
                if why:
                    component_issues.add(why)
                if c.formula == "overtime_rate" and c.rate is None and r.overtime_payable and r.overtime_minutes > 0 and (r.salary.values.get(str(c.id), {}) or {}).get("rate") is None:
                    component_issues.add(f"{c.code}: no overtime rate for {r.employee.employee_code}")
        conflicts = [r for r in rows if r.config_status == "conflict"]
        missing = [r for r in rows if r.salary is None]
        no_config = [r for r in rows if r.config_status == "missing"]
        attendance = [r for r in rows if r.attendance_exceptions]
        pending = [r for r in rows if r.pending_requests]
        unknown = [r for r in rows if r.unknown_calendar_days] if inputs.basis == "working_days" else []

        def names(items: list[EmployeeInput]) -> str:
            codes = [r.employee.employee_code for r in items[:10]]
            return ", ".join(codes) + (f" and {len(items) - 10} more" if len(items) > 10 else "")

        return [
            _check("payroll_policy", "Payroll policy", True, 1 if problem else 0, "The payroll policy says how the days of a period are counted.", problem or ""),
            _check("components", "Salary components", True, len(component_issues), "Every component used is fully configured.", "; ".join(sorted(component_issues))),
            _check("configuration_conflict", "Payroll configuration conflicts", True, len(conflicts), "No employee has two configurations at the same level.",
                   f"Two assignments at the same level apply to {names(conflicts)}. End one of them."),
            _check("missing_salary", "Salary records", False, len(missing), "Every employee has a salary record.", f"No salary record: {names(missing)}. They are listed without amounts."),
            _check("missing_configuration", "Payroll configuration", False, len(no_config), "A payroll configuration applies to every employee.",
                   f"No configuration applies to {names(no_config)}; their salary structure is used as it is."),
            _check("attendance_exceptions", "Attendance exceptions", False, len(attendance), "No absences or missing punches in the period.",
                   f"Absences or missing punches for {names(attendance)}."),
            _check("pending_requests", "Pending requests", False, len(pending), "No leave, permission, overtime or correction request in the period awaits a decision.",
                   f"Requests awaiting a decision for {names(pending)}."),
            _check("working_calendar", "Working days", False, len(unknown), "Working days are known for every employee.",
                   f"No shift and no company working days for {names(unknown)}: every date counts as a working day."),
        ]

    async def validate(self, period_id: uuid.UUID, data: VersionIn) -> ValidationWithPeriodOut:
        p = await self._period(period_id, for_update=True)
        ensure_version(p, data.version)
        self._require(p, ("open", "validated", "calculated", "rejected"), "validated")
        inputs = await compute_inputs(self.session, p)
        checks = self.checks(inputs)
        can = not any(c.status == "blocking" for c in checks)
        now = _utcnow()
        await self.session.execute(delete(PayrollResult).where(PayrollResult.period_id == p.id))
        result = ValidationResultOut(checks=checks, can_calculate=can, validated_at=now)
        p.validation = result.model_dump(mode="json", by_alias=True)
        p.validated_at, p.calculated_at, p.employees_included = now, None, None
        p.status = "validated" if can else "open"
        blocking = sum(c.status == "blocking" for c in checks)
        warnings = sum(c.status == "warning" for c in checks)
        self._event(p, "updated", f"Validated: {blocking} blocking, {warnings} warning(s)")
        out = await self._finish(p, "validated", f"Payroll {p.month} validated ({blocking} blocking, {warnings} warnings)")
        return ValidationWithPeriodOut(**result.model_dump(), period=out)

    async def validation(self, period_id: uuid.UUID) -> ValidationResultOut | None:
        p = await self._period(period_id)
        return ValidationResultOut.model_validate(p.validation) if p.validation else None

    # ---- Inputs ----------------------------------------------------------------------------------------------------

    async def _filtered_employees(self, q: str | None, department_id: str | None) -> set[uuid.UUID]:
        stmt = select(Employee.id).where(EmployeeScopeService.clause(self.caller.scope))
        if q:
            stmt = stmt.where(text_match(q))
        if department_id:
            stmt = stmt.where(Employee.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        return set((await self.session.scalars(stmt)).all())

    @staticmethod
    def _sort(items: list, sort: str | None, key_of, allowed: tuple[str, ...] = RESULT_SORTS) -> list:
        name, _, direction = (sort or "employee:asc").partition(":")
        if name not in allowed or direction not in ("", "asc", "desc"):
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": f"Use {', '.join(allowed)} with :asc or :desc."}])
        return sorted(items, key=lambda x: key_of(x, name), reverse=direction == "desc")

    async def inputs(self, period_id: uuid.UUID, *, q, department_id, exceptions_only: bool, sort, page: int, page_size: int) -> Page:
        p = await self._period(period_id)
        allowed = await self._filtered_employees(q, department_id)
        depts = await departments(self.session)
        results = await self._results(p)
        rows: list[PayrollInputRowOut] = []
        if results:
            employees = {e.id: e for e in (await self.session.scalars(select(Employee).where(Employee.id.in_([r.employee_id for r in results])))).all()}
            labels = {"missing_salary": "No salary record for the period", "attendance_exceptions": "Attendance exceptions in the period", "pending_requests": "Requests in the period awaiting a decision",
                      "prorated": "Joined or left during the period", "large_change": "Net pay changed by more than the set percentage"}
            for r in results:
                if r.employee_id in allowed:
                    rows.append(PayrollInputRowOut(employee=employee_ref(employees[r.employee_id], depts), days_in_period=_num(r.days_in_period), paid_days=_num(r.paid_days), loss_of_pay_days=_num(r.loss_of_pay_days),
                                                   leave_days=_num(r.leave_days), overtime_minutes=r.overtime_minutes, salary_assigned="missing_salary" not in r.exceptions, issues=[labels[x] for x in r.exceptions]))
        else:
            data = await compute_inputs(self.session, p)
            for r in data.rows.values():
                if r.employee.id in allowed:
                    rows.append(PayrollInputRowOut(employee=employee_ref(r.employee, depts), days_in_period=_num(r.days_in_period), paid_days=_num(r.paid_days), loss_of_pay_days=_num(r.loss_of_pay_days),
                                                   leave_days=_num(r.leave_days), overtime_minutes=r.overtime_minutes, salary_assigned=r.salary is not None, issues=r.issues()))
        if exceptions_only:
            rows = [r for r in rows if r.issues]
        rows = self._sort(rows, sort, lambda x, n: (x.employee.full_name.lower() if n == "employee" else x.employee.employee_code if n == "employeeCode" else x.paid_days, x.employee.id),
                          ("employee", "employeeCode", "paidDays"))
        total = len(rows)
        return Page.build(PageResult(rows, page, page_size, total), rows[(page - 1) * page_size: page * page_size])

    # ---- Calculation ---------------------------------------------------------------------------------------------

    async def calculate(self, period_id: uuid.UUID, data: VersionIn) -> PayrollPeriodOut:
        p = await self._period(period_id, for_update=True)
        ensure_version(p, data.version)
        self._require(p, ("validated", "calculated"), "calculated")
        inputs = await compute_inputs(self.session, p)
        checks = self.checks(inputs)
        blocking = [c for c in checks if c.status == "blocking"]
        if blocking:
            raise ValidationFailedError("Payroll cannot be calculated while a check is blocking.", details=[{"field": c.code, "message": c.detail} for c in blocking])
        large = inputs.policy.get("payroll", "largeChangePercent")
        previous = await self._previous_nets(p)
        comps = inputs.components
        await self.session.execute(delete(PayrollResult).where(PayrollResult.period_id == p.id))
        count = 0
        for r in inputs.rows.values():
            exceptions = []
            if r.salary is None:
                exceptions.append("missing_salary")
            if r.attendance_exceptions:
                exceptions.append("attendance_exceptions")
            if r.pending_requests:
                exceptions.append("pending_requests")
            if r.prorated:
                exceptions.append("prorated")
            lines: list[dict] = []
            gross = deductions = contributions = Decimal("0")
            if r.salary is not None and r.structure is not None:
                gross_value = PayrollSetupService.monthly_gross(r.salary, r.structure, comps)
                factor = (r.paid_days / r.days_in_period) if r.days_in_period > 0 else Decimal("0")
                outcome = calculate([component_def(c) for c in r.components], r.salary.values or {}, monthly_gross=Decimal(str(gross_value)) if gross_value is not None else None,
                                    factor=min(factor, Decimal("1")), overtime_hours=Decimal(r.overtime_minutes) / 60, overtime_payable=r.overtime_payable)
                gross, deductions, contributions = outcome.gross, outcome.deductions, outcome.employer_contributions
                lines = [{"componentId": line.component.id, "code": line.component.code, "name": line.component.name, "type": line.component.type, "amount": str(line.amount)} for line in outcome.lines]
            net = gross - deductions
            prev = previous.get(r.employee.id)
            if large and prev is not None and prev > 0 and r.salary is not None and abs(net - prev) * 100 / prev > Decimal(str(large)):
                exceptions.append("large_change")
            self.session.add(PayrollResult(
                period_id=p.id, employee_id=r.employee.id, days_in_period=r.days_in_period, paid_days=r.paid_days, loss_of_pay_days=r.loss_of_pay_days, leave_days=r.leave_days,
                overtime_minutes=r.overtime_minutes, gross=gross, deductions=deductions, employer_contributions=contributions, net=net, previous_net=prev, exceptions=exceptions, lines=lines,
                salary_id=r.salary.id if r.salary else None, configuration_id=r.configuration.id if r.configuration else None,
            ))
            count += 1
        p.status, p.calculated_at, p.employees_included = "calculated", _utcnow(), count
        self._event(p, "updated", f"Calculated for {count} employee(s)")
        return await self._finish(p, "calculated", f"Payroll {p.month} calculated for {count} employees")

    async def _previous_nets(self, p: PayrollPeriod) -> dict[uuid.UUID, Decimal]:
        """Net pay in the latest finalized period before this one."""
        prev = await self.session.scalar(select(PayrollPeriod).where(PayrollPeriod.month < p.month, PayrollPeriod.status.in_(FINALIZED)).order_by(PayrollPeriod.month.desc()).limit(1))
        if prev is None:
            return {}
        rows = (await self.session.execute(select(PayrollResult.employee_id, PayrollResult.net, PayrollResult.exceptions).where(PayrollResult.period_id == prev.id))).all()
        return {e: Decimal(str(n)) for e, n, x in rows if "missing_salary" not in (x or [])}

    # ---- Results ------------------------------------------------------------------------------------------------------

    def _row(self, r: PayrollResult, e: Employee, depts) -> PayrollResultRowOut:
        show = self.amounts and "missing_salary" not in r.exceptions
        return PayrollResultRowOut(employee=employee_ref(e, depts), paid_days=_num(r.paid_days), gross=amt(r.gross, show), deductions=amt(r.deductions, show), net=amt(r.net, show), exceptions=list(r.exceptions))

    async def results(self, period_id: uuid.UUID, *, q, department_id, exceptions_only: bool, sort, page: int, page_size: int) -> ResultsPageOut:
        p = await self._period(period_id)
        allowed = await self._filtered_employees(q, department_id)
        results = [r for r in await self._results(p) if r.employee_id in allowed]
        if exceptions_only:
            results = [r for r in results if r.exceptions]
        employees = {e.id: e for e in (await self.session.scalars(select(Employee).where(Employee.id.in_([r.employee_id for r in results])))).all()} if results else {}
        if sort and sort.split(":")[0] in ("gross", "net") and not self.amounts:
            raise BadRequestError("Sorting by amounts needs permission to see amounts.", details=[{"field": "sort", "message": "Sort by employee, employeeCode or paidDays."}])

        def key(r: PayrollResult, n: str):
            e = employees[r.employee_id]
            v = {"employee": e.full_name.lower(), "employeeCode": e.employee_code, "paidDays": r.paid_days, "gross": r.gross, "net": r.net}[n]
            return (v, str(e.id))

        results = self._sort(results, sort, key)
        depts = await departments(self.session)
        total = len(results)
        items = [self._row(r, employees[r.employee_id], depts) for r in results[(page - 1) * page_size: page * page_size]]
        page_out = Page.build(PageResult(items, page, page_size, total), items)
        return ResultsPageOut(items=items, meta=page_out.meta, totals=self._money(results), currency=p.currency)

    async def result(self, period_id: uuid.UUID, employee_id: uuid.UUID) -> PayrollResultDetailOut:
        p = await self._period(period_id)
        r = await self.session.scalar(select(PayrollResult).where(PayrollResult.period_id == p.id, PayrollResult.employee_id == employee_id))
        if r is None or employee_id not in await self._in_scope():
            raise NotFoundError()
        e = await self.session.get(Employee, employee_id)
        row = self._row(r, e, await departments(self.session))
        show = self.amounts and "missing_salary" not in r.exceptions
        lines = [ResultLineOut(component=ComponentRefOut(code=x["code"], name=x["name"], type=x["type"]), amount=amt(x["amount"], show)) for x in r.lines]
        return PayrollResultDetailOut(**row.model_dump(), lines=lines, previous_net=amt(r.previous_net, self.amounts))

    # ---- Workflow ------------------------------------------------------------------------------------------------------

    async def submit(self, period_id: uuid.UUID, data: SubmissionIn) -> PayrollPeriodOut:
        p = await self._period(period_id, for_update=True)
        ensure_version(p, data.version)
        self._require(p, ("calculated",), "submitted")
        comment = (data.comment or "").strip() or None
        p.status, p.submitted_by = "submitted", self.caller.principal.actor_uuid
        self._event(p, "submitted", comment)
        return await self._finish(p, "submitted", f"Payroll {p.month} submitted for approval")

    async def decide(self, period_id: uuid.UUID, data: PeriodDecisionIn) -> PayrollPeriodOut:
        p = await self._period(period_id, for_update=True)
        ensure_version(p, data.version)
        self._require(p, ("submitted",), "approved or rejected")
        comment = (data.comment or "").strip() or None
        if data.decision == "reject":
            if not comment:
                raise ValidationFailedError(details=[{"field": "comment", "message": "Enter the reason for sending the payroll back."}])
            p.status = "rejected"
            self._event(p, "rejected", comment)
            return await self._finish(p, "rejected", f"Payroll {p.month} sent back: {comment}")
        policy = await compute_policy(self.session)
        if p.submitted_by == self.caller.principal.actor_uuid and not policy.on("payroll", "allowSelfApproval"):
            raise ForbiddenError("The payroll must be approved by someone other than the person who submitted it.")
        if p.to_date >= company_today():
            raise InvalidTransitionError("A payroll period can be approved only after it has ended.")
        # Freeze and lock the period's attendance (Module 5 lock).
        employees = list((await self.session.scalars(select(Employee).where(Employee.joining_date <= p.to_date))).all())
        await store_days(self.session, employees, p.from_date, p.to_date)
        covered = await self.session.scalar(select(AttendanceLockPeriod.id).where(AttendanceLockPeriod.from_date <= p.from_date, AttendanceLockPeriod.to_date >= p.to_date))
        if covered is None:
            self.session.add(AttendanceLockPeriod(from_date=p.from_date, to_date=p.to_date, reason=f"Payroll {p.month} approved"))
        p.status = "approved"
        self._event(p, "approved", comment)
        return await self._finish(p, "approved", f"Payroll {p.month} approved; attendance from {p.from_date.isoformat()} to {p.to_date.isoformat()} locked")

    async def publish(self, period_id: uuid.UUID, data: VersionIn) -> PayrollPeriodOut:
        p = await self._period(period_id, for_update=True)
        ensure_version(p, data.version)
        self._require(p, ("approved",), "published")
        now = _utcnow()
        count = 0
        for r in await self._results(p):
            if "missing_salary" in r.exceptions:
                continue
            self.session.add(Payslip(period_id=p.id, employee_id=r.employee_id, result_id=r.id, net_pay=r.net, currency=p.currency, published_at=now))
            count += 1
        p.status = "payslips_published"
        self._event(p, "updated", f"Payslips published for {count} employee(s)")
        return await self._finish(p, "payslips_published", f"Payroll {p.month}: {count} payslips published")


async def compute_policy(session: AsyncSession):
    from app.services.attendance.policy_service import policy_values_on

    return await policy_values_on(session, company_today())
