"""Payroll configurations and assignments (contract H4).

Configurations hold no formulas, rates or amounts: a structure, a component selection, overtime eligibility
and references to rules configured elsewhere. Assignments say who a configuration applies to, and when:
- precedence employee > department > company; two at the highest level covering a date are a conflict
  (the backend never chooses);
- assignments are never edited or deleted, only ended; every create and end goes to the history and the
  audit log;
- overlaps for the same target are refused (existing ones are reported with conflict = true);
- a change on or before the end of an approved or published period is refused (blockedBy);
- a change starting inside a period in progress needs confirmPeriodInProgress.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.models.attendance_model import Workflow
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.models.payroll_model import EmployeeSalary, PayrollAssignment, PayrollAssignmentHistory, PayrollConfiguration, PayrollPeriod, SalaryComponent, SalaryStructure
from app.models.reference_data_model import AttendancePolicyOption, EmploymentType, OvertimePolicyOption
from app.repositories.base_repository import PageResult
from app.schemas.common import Page
from app.schemas.employee_schema import NamedRefOut
from app.schemas.payroll_schema import (
    AssignmentEndIn,
    AssignmentHistoryEntryOut,
    AssignmentImpactOut,
    ComponentLinkOut,
    ConfigurationRefOut,
    EffectiveConfigurationOut,
    OptionComponentOut,
    OvertimeConfigOut,
    PayrollAssignmentIn,
    PayrollAssignmentOut,
    PayrollConfigurationIn,
    PayrollConfigurationOptionsOut,
    PayrollConfigurationOut,
    PeriodRefOut,
)
from app.services.attendance.attendance_read_service import employee_ref
from app.services.audit_service import AuditService, diff
from app.services.employee_support import company_today, parse_date
from app.services.payroll.common import FINALIZED, MODULE, departments, month_label
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

# The loss-of-pay rule lives in the G6 payroll policy (MODULE_7_DECISIONS.md); configurations reference it.
LOP_RULES = {"g6-payroll": "Payroll policy (HR Policies: payroll)"}
MAX_DATE = date(9999, 12, 31)


def _overlaps(a_from, a_to, b_from, b_to) -> bool:
    return a_from <= (b_to or MAX_DATE) and b_from <= (a_to or MAX_DATE)


def assignment_status(a: PayrollAssignment, today: date) -> str:
    if a.effective_from > today:
        return "scheduled"
    if a.effective_to is not None and a.effective_to < today:
        return "ended"
    return "active"


class PayrollConfigurationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.audit = AuditService(session)

    # ---- Configurations ------------------------------------------------------------------------------------

    async def _lookups(self) -> dict:
        async def named(model, attr="name"):
            return {r.id: getattr(r, attr) for r in (await self.session.scalars(select(model))).all()}
        return {
            "structures": await named(SalaryStructure), "components": {c.id: c for c in (await self.session.scalars(select(SalaryComponent))).all()},
            "etypes": await named(EmploymentType), "workflows": {w.id: w for w in (await self.session.scalars(select(Workflow))).all()},
            "attendance": await named(AttendancePolicyOption), "overtime": await named(OvertimePolicyOption),
        }

    async def _counts(self) -> dict[uuid.UUID, int]:
        today = company_today()
        rows = (await self.session.execute(select(PayrollAssignment.configuration_id, func.count()).where(or_(PayrollAssignment.effective_to.is_(None), PayrollAssignment.effective_to >= today))
                                           .group_by(PayrollAssignment.configuration_id))).all()
        return dict(rows)

    def _config_out(self, c: PayrollConfiguration, lk: dict, counts: dict) -> PayrollConfigurationOut:
        ref = lambda table, key: NamedRefOut(id=str(key), name=table.get(key, "")) if key else None  # noqa: E731
        comps = [lk["components"][i] for i in c.component_ids if i in lk["components"]]
        link = lambda kind: [ComponentLinkOut(component_id=str(x.id), code=x.code, name=x.name) for x in comps if x.type == kind]  # noqa: E731
        wf = lk["workflows"].get(c.approval_workflow_id)
        return PayrollConfigurationOut(
            id=str(c.id), code=c.code, name=c.name, description=c.description, frequency=c.frequency, structure=ref(lk["structures"], c.structure_id),
            earnings=link("earning"), deductions=link("deduction"), employer_contributions=link("employer_contribution"),
            overtime=OvertimeConfigOut(eligible=c.overtime_eligible, policy=ref(lk["overtime"], c.overtime_policy_id)),
            attendance_rule=ref(lk["attendance"], c.attendance_rule_id), loss_of_pay_rule=NamedRefOut(id=c.loss_of_pay_rule, name=LOP_RULES[c.loss_of_pay_rule]) if c.loss_of_pay_rule else None,
            employee_categories=[NamedRefOut(id=str(i), name=lk["etypes"].get(i, "")) for i in c.employee_category_ids],
            approval_workflow=NamedRefOut(id=str(wf.id), name=wf.name) if wf else None,
            effective_from=c.effective_from.isoformat(), effective_to=c.effective_to.isoformat() if c.effective_to else None, status=c.status,
            assignments_count=counts.get(c.id, 0), created_at=c.created_at, created_by=c.created_by_name, updated_at=c.updated_at, updated_by=c.updated_by_name, version=c.version,
        )

    async def configurations(self) -> list[PayrollConfigurationOut]:
        lk, counts = await self._lookups(), await self._counts()
        rows = (await self.session.scalars(select(PayrollConfiguration).order_by(PayrollConfiguration.code))).all()
        return [self._config_out(c, lk, counts) for c in rows]

    async def options(self) -> PayrollConfigurationOptionsOut:
        lk = await self._lookups()
        sort = lambda d: [NamedRefOut(id=str(k), name=v) for k, v in sorted(d.items(), key=lambda kv: kv[1].lower())]  # noqa: E731
        return PayrollConfigurationOptionsOut(
            structures=sort(lk["structures"]),
            components=[OptionComponentOut(id=str(c.id), code=c.code, name=c.name, type=c.type) for c in sorted(lk["components"].values(), key=lambda c: c.code) if c.active],
            employee_categories=sort(lk["etypes"]),
            approval_workflows=[NamedRefOut(id=str(w.id), name=w.name) for w in sorted(lk["workflows"].values(), key=lambda w: w.name.lower()) if w.process == "payroll"],
            attendance_rules=sort(lk["attendance"]), loss_of_pay_rules=[NamedRefOut(id=k, name=v) for k, v in LOP_RULES.items()], overtime_policies=sort(lk["overtime"]),
        )

    async def save_configuration(self, config_id: uuid.UUID | None, data: PayrollConfigurationIn) -> PayrollConfigurationOut:
        err = FieldErrors()
        lk = await self._lookups()
        code, name = data.code.strip().upper(), data.name.strip()
        if not 2 <= len(code) <= 12:
            err.add("code", "Use 2-12 characters.")
        if not 2 <= len(name) <= 120:
            err.add("name", "Enter a name of 2-120 characters.")
        if await self.session.scalar(select(PayrollConfiguration.id).where(func.upper(PayrollConfiguration.code) == code, PayrollConfiguration.id != (config_id or uuid.uuid4()))):
            err.add("code", "Another configuration already uses this code.")
        structure_id = body_id(data.structure_id) if data.structure_id else None
        if data.structure_id and structure_id not in lk["structures"]:
            err.add("structureId", "Choose an existing salary structure.")
        component_ids = [body_id(i) for i in data.component_ids]
        if any(i not in lk["components"] for i in component_ids):
            err.add("componentIds", "Choose existing components.")
        elif not any(lk["components"][i].type == "earning" for i in component_ids):
            err.add("componentIds", "Choose at least one earning component.")
        overtime_policy_id = body_id(data.overtime_policy_id) if data.overtime_policy_id else None
        if data.overtime_eligible and overtime_policy_id is None:
            err.add("overtimePolicyId", "Choose the overtime policy.")
        elif overtime_policy_id and overtime_policy_id not in lk["overtime"]:
            err.add("overtimePolicyId", "Choose an existing overtime policy.")
        attendance_rule_id = body_id(data.attendance_rule_id) if data.attendance_rule_id else None
        if attendance_rule_id and attendance_rule_id not in lk["attendance"]:
            err.add("attendanceRuleId", "Choose an existing attendance rule.")
        if data.loss_of_pay_rule_id and data.loss_of_pay_rule_id not in LOP_RULES:
            err.add("lossOfPayRuleId", "Choose an existing loss-of-pay rule.")
        category_ids = [body_id(i) for i in data.employee_category_ids]
        if any(i not in lk["etypes"] for i in category_ids):
            err.add("employeeCategoryIds", "Choose existing employee categories.")
        workflow_id = body_id(data.approval_workflow_id) if data.approval_workflow_id else None
        if workflow_id and (workflow_id not in lk["workflows"] or lk["workflows"][workflow_id].process != "payroll"):
            err.add("approvalWorkflowId", "Choose a payroll approval workflow.")
        start = end = None
        try:
            start = parse_date(data.effective_from)
        except ValueError:
            pass
        if start is None:
            err.add("effectiveFrom", "Enter the date the configuration takes effect.")
        try:
            end = parse_date(data.effective_to)
        except ValueError:
            err.add("effectiveTo", "Enter a valid date.")
        if start and end and end < start:
            err.add("effectiveTo", "The end date must be on or after the start date.")
        if config_id and data.status == "inactive" and (await self._counts()).get(config_id):
            err.add("status", "This configuration has current or scheduled assignments. End them before deactivating it.")
        err.raise_if_any()
        values = dict(name=name, description=data.description.strip(), frequency=data.frequency, structure_id=structure_id, component_ids=component_ids, overtime_eligible=data.overtime_eligible,
                      overtime_policy_id=overtime_policy_id, attendance_rule_id=attendance_rule_id, loss_of_pay_rule=data.loss_of_pay_rule_id, employee_category_ids=category_ids,
                      approval_workflow_id=workflow_id, effective_from=start, effective_to=end, status=data.status)
        counts = await self._counts()
        if config_id is None:
            c = PayrollConfiguration(code=code, **values)
            self.session.add(c)
            before: dict = {}
        else:
            c = await self.session.get(PayrollConfiguration, config_id)
            if c is None:
                raise NotFoundError()
            ensure_version(c, data.version)
            if code != c.code:
                raise ValidationFailedError(details=[{"field": "code", "message": "The code of a configuration cannot be changed."}])
            before = self._config_out(c, lk, counts).model_dump(exclude={"version", "updated_at", "updated_by", "created_at", "created_by", "assignments_count"})
            for k, v in values.items():
                setattr(c, k, v)
        await self.session.flush()
        out = self._config_out(c, lk, counts)
        self.audit.record(module=MODULE, action="payroll_configuration.created" if not before else "payroll_configuration.updated", summary=f"Payroll configuration {c.code} saved",
                          entity_type="payroll_configuration", entity_id=c.id, entity_label=c.name, changes=diff(before, out.model_dump(exclude={"version", "updated_at", "updated_by", "created_at", "created_by", "assignments_count"})))
        await self.session.commit()
        return out

    # ---- Assignments ---------------------------------------------------------------------------------------------

    @staticmethod
    def _target(a) -> tuple:
        return (a.scope, a.department_id, a.employee_id)

    async def _all_assignments(self) -> list[PayrollAssignment]:
        return list((await self.session.scalars(select(PayrollAssignment))).all())

    def _conflicting(self, a: PayrollAssignment, everything: list[PayrollAssignment]) -> bool:
        return any(o.id != a.id and self._target(o) == self._target(a) and _overlaps(o.effective_from, o.effective_to, a.effective_from, a.effective_to) for o in everything)

    async def _assignment_out(self, a: PayrollAssignment, everything: list[PayrollAssignment], cache: dict) -> PayrollAssignmentOut:
        if "depts" not in cache:
            cache["depts"] = await departments(self.session)
            cache["configs"] = {c.id: c for c in (await self.session.scalars(select(PayrollConfiguration))).all()}
        cfg = cache["configs"][a.configuration_id]
        employee = None
        if a.employee_id:
            e = cache.get(a.employee_id) or await self.session.get(Employee, a.employee_id)
            cache[a.employee_id] = e
            employee = employee_ref(e, cache["depts"])
        return PayrollAssignmentOut(
            id=str(a.id), configuration=ConfigurationRefOut(id=str(cfg.id), code=cfg.code, name=cfg.name), scope=a.scope,
            department=NamedRefOut(id=str(a.department_id), name=cache["depts"].get(a.department_id, "")) if a.department_id else None, employee=employee,
            effective_from=a.effective_from.isoformat(), effective_to=a.effective_to.isoformat() if a.effective_to else None, status=assignment_status(a, company_today()),
            reason=a.reason, conflict=self._conflicting(a, everything), created_at=a.created_at, created_by=a.created_by_name, version=a.version,
        )

    async def assignments(self, *, scope, configuration_id, department_id, employee_id, status, conflicts_only, page, page_size) -> Page:
        everything = await self._all_assignments()
        today = company_today()
        rows = everything
        if scope:
            rows = [a for a in rows if a.scope == scope]
        for raw, attr in ((configuration_id, "configuration_id"), (department_id, "department_id"), (employee_id, "employee_id")):
            if raw:
                rid = body_id(raw)
                rows = [a for a in rows if getattr(a, attr) == rid]
        if status:
            rows = [a for a in rows if assignment_status(a, today) == status]
        if conflicts_only:
            rows = [a for a in rows if self._conflicting(a, everything)]
        rows.sort(key=lambda a: ({"company": 0, "department": 1, "employee": 2}[a.scope], a.effective_from), reverse=False)
        total = len(rows)
        cache: dict = {}
        items = [await self._assignment_out(a, everything, cache) for a in rows[(page - 1) * page_size: page * page_size]]
        return Page.build(PageResult(items, page, page_size, total), items)

    async def _finalized_end(self) -> PayrollPeriod | None:
        return await self.session.scalar(select(PayrollPeriod).where(PayrollPeriod.status.in_(FINALIZED)).order_by(PayrollPeriod.to_date.desc()).limit(1))

    async def _period_in_progress(self, on: date) -> PayrollPeriod | None:
        return await self.session.scalar(select(PayrollPeriod).where(PayrollPeriod.from_date <= on, PayrollPeriod.to_date >= on, PayrollPeriod.status.not_in(FINALIZED)))

    async def _affected(self, scope: str, department_id, employee_id) -> int:
        if scope == "employee":
            return 1
        stmt = select(func.count()).select_from(Employee)
        if scope == "department":
            stmt = stmt.where(Employee.department_id == department_id)
        return await self.session.scalar(stmt) or 0

    async def _check(self, data: PayrollAssignmentIn) -> tuple[FieldErrors, dict]:
        err = FieldErrors()
        cfg = await self.session.get(PayrollConfiguration, body_id(data.configuration_id)) if body_id(data.configuration_id) else None
        if cfg is None:
            err.add("configurationId", "Choose an existing payroll configuration.")
        elif cfg.status != "active":
            err.add("configurationId", "This configuration is inactive.")
        department_id = body_id(data.department_id) if data.department_id else None
        employee_id = body_id(data.employee_id) if data.employee_id else None
        if data.scope == "department" and (department_id is None or await self.session.get(Department, department_id) is None):
            err.add("departmentId", "Choose the department.")
        if data.scope == "employee" and (employee_id is None or await self.session.get(Employee, employee_id) is None):
            err.add("employeeId", "Choose the employee.")
        if data.scope != "department":
            department_id = None
        if data.scope != "employee":
            employee_id = None
        start = end = None
        try:
            start = parse_date(data.effective_from)
        except ValueError:
            pass
        if start is None:
            err.add("effectiveFrom", "Enter the date the assignment takes effect.")
        try:
            end = parse_date(data.effective_to)
        except ValueError:
            err.add("effectiveTo", "Enter a valid date.")
        if start and end and end < start:
            err.add("effectiveTo", "The end date must be on or after the start date.")
        if cfg and start and (start < cfg.effective_from or (cfg.effective_to and (end is None or end > cfg.effective_to))):
            err.add("effectiveFrom", "The assignment must lie within the configuration's effective dates.")
        return err, dict(cfg=cfg, department_id=department_id, employee_id=employee_id, start=start, end=end)

    async def _impact(self, scope, department_id, employee_id, start, end) -> AssignmentImpactOut:
        everything = await self._all_assignments()
        target = (scope, department_id, employee_id)
        overlapping = [a for a in everything if self._target(a) == target and _overlaps(a.effective_from, a.effective_to, start, end)]
        finalized = await self._finalized_end()
        blocked = None
        if finalized and start <= finalized.to_date:
            blocked = f"Payroll for {month_label(finalized.month)} is {finalized.status.replace('_', ' ')}: changes must start after {finalized.to_date.isoformat()}."
        progress = await self._period_in_progress(start)
        cache: dict = {}
        return AssignmentImpactOut(
            affected_employees=await self._affected(scope, department_id, employee_id),
            period_in_progress=PeriodRefOut(id=str(progress.id), label=month_label(progress.month), status=progress.status) if progress else None,
            overlapping=[await self._assignment_out(a, everything, cache) for a in overlapping], blocked_by=blocked,
        )

    async def preview(self, data: PayrollAssignmentIn) -> AssignmentImpactOut:
        err, v = await self._check(data)
        err.raise_if_any()
        return await self._impact(data.scope, v["department_id"], v["employee_id"], v["start"], v["end"])

    async def create(self, data: PayrollAssignmentIn) -> PayrollAssignmentOut:
        err, v = await self._check(data)
        reason = data.reason.strip()
        if len(reason) < 3:
            err.add("reason", "Enter the reason for this assignment.")
        err.raise_if_any()
        impact = await self._impact(data.scope, v["department_id"], v["employee_id"], v["start"], v["end"])
        if impact.blocked_by:
            raise ValidationFailedError(details=[{"field": "effectiveFrom", "message": impact.blocked_by}])
        if impact.overlapping:
            raise ValidationFailedError(details=[{"field": "effectiveFrom", "message": "This overlaps an existing assignment for the same target. End that one first."}])
        if impact.period_in_progress and not data.confirm_period_in_progress:
            raise ValidationFailedError(details=[{"field": "confirmPeriodInProgress", "message": f"This change starts inside {impact.period_in_progress.label}, which is in progress. Confirm to continue; the period must then be recalculated."}])
        a = PayrollAssignment(configuration_id=v["cfg"].id, scope=data.scope, department_id=v["department_id"], employee_id=v["employee_id"], effective_from=v["start"], effective_to=v["end"], reason=reason)
        self.session.add(a)
        await self.session.flush()
        everything = await self._all_assignments()
        out = await self._assignment_out(a, everything, {})
        summary = f"{v['cfg'].code} assigned to {self._target_label(out)} from {a.effective_from.isoformat()}" + (f" to {a.effective_to.isoformat()}" if a.effective_to else "")
        self.session.add(PayrollAssignmentHistory(assignment_id=a.id, action="assigned", snapshot=out.model_dump(mode="json", by_alias=True), summary=summary))
        self.audit.record(module=MODULE, action="payroll_assignment.created", summary=summary, entity_type="payroll_assignment", entity_id=a.id)
        await self.session.commit()
        return out

    @staticmethod
    def _target_label(out: PayrollAssignmentOut) -> str:
        if out.scope == "company":
            return "the company"
        if out.scope == "department":
            return f"department {out.department.name}"
        return f"employee {out.employee.employee_code}"

    async def end(self, assignment_id: uuid.UUID, data: AssignmentEndIn) -> PayrollAssignmentOut:
        a = await self.session.get(PayrollAssignment, assignment_id)
        if a is None:
            raise NotFoundError()
        ensure_version(a, data.version)
        err = FieldErrors()
        end = None
        try:
            end = parse_date(data.effective_to)
        except ValueError:
            pass
        if end is None:
            err.add("effectiveTo", "Enter the last day of the assignment.")
        elif end < a.effective_from - timedelta(days=1):
            err.add("effectiveTo", "The end cannot be before the assignment starts.")
        elif a.effective_to is not None and end >= a.effective_to:
            err.add("effectiveTo", "The assignment already ends on or before this date.")
        reason = data.reason.strip()
        if len(reason) < 3:
            err.add("reason", "Enter the reason for ending the assignment.")
        err.raise_if_any()
        change_from = end + timedelta(days=1)
        finalized = await self._finalized_end()
        if finalized and change_from <= finalized.to_date:
            raise ValidationFailedError(details=[{"field": "effectiveTo", "message": f"Payroll for {month_label(finalized.month)} is finalized: the assignment can only end on or after {finalized.to_date.isoformat()}."}])
        progress = await self._period_in_progress(change_from)
        if progress and not data.confirm_period_in_progress:
            raise ValidationFailedError(details=[{"field": "confirmPeriodInProgress", "message": f"This change takes effect inside {month_label(progress.month)}, which is in progress. Confirm to continue; the period must then be recalculated."}])
        a.effective_to = end
        a.reason = (a.reason or "") + f" | Ended: {reason}"
        await self.session.flush()
        out = await self._assignment_out(a, await self._all_assignments(), {})
        summary = f"{out.configuration.code} for {self._target_label(out)} ended on {end.isoformat()}: {reason}"
        self.session.add(PayrollAssignmentHistory(assignment_id=a.id, action="ended", snapshot=out.model_dump(mode="json", by_alias=True), summary=summary))
        self.audit.record(module=MODULE, action="payroll_assignment.ended", summary=summary, entity_type="payroll_assignment", entity_id=a.id)
        await self.session.commit()
        return out

    async def history(self, *, employee_id, department_id, scope, page, page_size) -> Page:
        stmt = select(PayrollAssignmentHistory, PayrollAssignment).join(PayrollAssignment, PayrollAssignment.id == PayrollAssignmentHistory.assignment_id)
        if employee_id:
            stmt = stmt.where(PayrollAssignment.employee_id == body_id(employee_id)) if body_id(employee_id) else stmt.where(false())
        if department_id:
            stmt = stmt.where(PayrollAssignment.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        if scope:
            stmt = stmt.where(PayrollAssignment.scope == scope)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self.session.execute(stmt.order_by(PayrollAssignmentHistory.created_at.desc(), PayrollAssignmentHistory.id).limit(page_size).offset((page - 1) * page_size))).all()
        items = [AssignmentHistoryEntryOut(id=str(h.id), at=h.created_at, by=h.created_by_name, action=h.action, assignment=PayrollAssignmentOut.model_validate(h.snapshot), summary=h.summary) for h, _ in rows]
        return Page.build(PageResult(items, page, page_size, total), items)

    # ---- Effective configuration -------------------------------------------------------------------------------------

    async def resolve(self, employee: Employee, on: date, everything: list[PayrollAssignment] | None = None) -> tuple[str, PayrollAssignment | None, list[PayrollAssignment]]:
        """(status, chosen assignment, candidates highest priority first) per the H4 resolution rule."""
        everything = everything if everything is not None else await self._all_assignments()
        covering = [a for a in everything if a.effective_from <= on and (a.effective_to is None or on <= a.effective_to)]
        levels = [[a for a in covering if a.scope == "employee" and a.employee_id == employee.id],
                  [a for a in covering if a.scope == "department" and a.department_id == employee.department_id],
                  [a for a in covering if a.scope == "company"]]
        candidates = [a for level in levels for a in level]
        for level in levels:
            if len(level) > 1:
                return "conflict", None, candidates
            if level:
                return "resolved", level[0], candidates
        return "missing", None, candidates

    async def effective(self, employee_id: uuid.UUID, on: date | None) -> EffectiveConfigurationOut:
        employee = await self.session.get(Employee, employee_id)
        if employee is None:
            raise NotFoundError()
        on = on or company_today()
        everything = await self._all_assignments()
        status, chosen, candidates = await self.resolve(employee, on, everything)
        cache: dict = {}
        configs = {c.id: c for c in (await self.session.scalars(select(PayrollConfiguration))).all()}
        structures = {s.id: s for s in (await self.session.scalars(select(SalaryStructure))).all()}
        salary = await self.session.scalar(select(EmployeeSalary).where(EmployeeSalary.employee_id == employee.id, EmployeeSalary.effective_from <= on).order_by(EmployeeSalary.effective_from.desc()).limit(1))
        cfg = configs.get(chosen.configuration_id) if chosen else None
        warnings = []
        if status == "missing":
            warnings.append("No payroll configuration covers this date. The employee's salary structure is used as it is.")
        if status == "conflict":
            warnings.append("Two assignments at the same level cover this date. Payroll cannot be calculated for this employee until one is ended.")
        if salary is None:
            warnings.append("The employee has no salary record on this date.")
        sal_s = structures.get(salary.structure_id) if salary else None
        cfg_s = structures.get(cfg.structure_id) if cfg and cfg.structure_id else None
        if sal_s and cfg_s and sal_s.id != cfg_s.id:
            warnings.append(f"The salary record uses structure {sal_s.name}, the configuration {cfg_s.name}. The salary record's structure is calculated.")
        if cfg and cfg.status != "active":
            warnings.append("The configuration is inactive.")
        return EffectiveConfigurationOut(
            employee=employee_ref(employee, await departments(self.session)), date=on.isoformat(), status=status,
            configuration=ConfigurationRefOut(id=str(cfg.id), code=cfg.code, name=cfg.name) if cfg else None, source=chosen.scope if chosen else None,
            assignment=await self._assignment_out(chosen, everything, cache) if chosen else None, candidates=[await self._assignment_out(a, everything, cache) for a in candidates],
            salary_structure=NamedRefOut(id=str(sal_s.id), name=sal_s.name) if sal_s else None, configuration_structure=NamedRefOut(id=str(cfg_s.id), name=cfg_s.name) if cfg_s else None,
            warnings=warnings,
        )
