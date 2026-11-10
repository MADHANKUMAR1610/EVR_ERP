"""Payroll configuration entered by HR (decision Q3), plus the frontend's read-only views of it.

- Salary components: one formula type each; every rate, cap and slab is HR-entered. Codes never change.
- Salary structures: an ordered list of components; percent and slab components may only use
  components placed before them (or GROSS), so the calculation order is always defined.
- Employee salary records: structure, effective date, monthly gross, per-employee amounts or rates.
  Append-only: a revision is a new record; the history is kept.
- Payroll periods: created by HR per month with their currency (no default currency).
Nothing is pre-filled. Every change is audited.
"""

from __future__ import annotations

import re
import uuid
from datetime import date

from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.models.employee_model import Employee
from app.models.payroll_model import EmployeeSalary, PayrollPeriod, PayrollPeriodEvent, SalaryComponent, SalaryStructure
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import text_match
from app.schemas.common import Page
from app.schemas.payroll_schema import (
    ComponentRefOut,
    EmployeeSalaryDetailOut,
    EmployeeSalaryIn,
    EmployeeSalaryRowOut,
    PayrollPeriodIn,
    PayrollPeriodOut,
    ResultLineOut,
    SalaryComponentIn,
    SalaryComponentOut,
    SalaryComponentSetupOut,
    SalaryHistoryOut,
    SalaryStructureIn,
    SalaryStructureOut,
    StructureComponentOut,
    StructureRefOut,
)
from app.services.attendance.attendance_read_service import employee_ref
from app.services.audit_service import AuditService, diff
from app.services.employee_scope_service import EmployeeScopeService
from app.services.employee_support import Caller, company_today, parse_date
from app.services.payroll.common import MODULE, amt, component_def, departments, month_bounds, period_out
from app.services.payroll.engine import GROSS, describe
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

CODE = re.compile(r"^[A-Z0-9_-]{1,20}$")


def _num(v):
    return float(v) if v is not None else None


class PayrollSetupService:
    def __init__(self, session: AsyncSession, caller: Caller | None = None):
        self.session = session
        self.caller = caller
        self.audit = AuditService(session)

    async def _components(self) -> dict[uuid.UUID, SalaryComponent]:
        return {c.id: c for c in (await self.session.scalars(select(SalaryComponent))).all()}

    @staticmethod
    def _names(components) -> dict[str, str]:
        return {c.code: c.name for c in components}

    # ---- Components ---------------------------------------------------------------------------------------

    def _component_out(self, c: SalaryComponent, names: dict[str, str]) -> SalaryComponentOut:
        return SalaryComponentOut(id=str(c.id), code=c.code, name=c.name, type=c.type, rule=describe(component_def(c), names), taxable=c.taxable, statutory=c.statutory, active=c.active)

    def _component_setup_out(self, c: SalaryComponent, names: dict[str, str]) -> SalaryComponentSetupOut:
        base = self._component_out(c, names).model_dump()
        return SalaryComponentSetupOut(**base, formula=c.formula, rate=_num(c.rate), base=list(c.base or []), base_cap=_num(c.base_cap), max_amount=_num(c.max_amount),
                                       slabs=list(c.slabs or []), prorate=c.prorate, version=c.version)

    async def components(self, *, setup: bool = False) -> list:
        rows = sorted((await self._components()).values(), key=lambda c: ({"earning": 0, "deduction": 1, "employer_contribution": 2}[c.type], c.code))
        names = self._names(rows)
        return [self._component_setup_out(c, names) if setup else self._component_out(c, names) for c in rows]

    async def save_component(self, component_id: uuid.UUID | None, data: SalaryComponentIn) -> SalaryComponentSetupOut:
        err = FieldErrors()
        code, name = data.code.strip().upper(), data.name.strip()
        if not CODE.match(code):
            err.add("code", "Use 1-20 capital letters, digits, '-' or '_'.")
        elif code == GROSS:
            err.add("code", "GROSS is reserved for the gross pay base.")
        if not 2 <= len(name) <= 120:
            err.add("name", "Enter a name of 2-120 characters.")
        existing = await self._components()
        by_code = {c.code: c for c in existing.values()}
        if code in by_code and by_code[code].id != component_id:
            err.add("code", "Another component already uses this code.")
        base = [b.strip().upper() for b in data.base]
        if data.formula in ("percent", "slab"):
            if not base:
                err.add("base", "Choose the base: GROSS or other components.")
            for b in base:
                if b != GROSS and b not in by_code:
                    err.add("base", f"Unknown component {b} in the base.")
                elif b == code:
                    err.add("base", "A component cannot be its own base.")
        if data.formula == "percent" and data.rate is None:
            err.add("rate", "Enter the percentage.")
        if data.formula == "percent" and data.rate is not None and data.rate > 100:
            err.add("rate", "Enter a percentage from 0 to 100.")
        if data.formula == "slab":
            if not data.slabs:
                err.add("slabs", "Enter at least one slab.")
            for i, s in enumerate(data.slabs):
                if (s.amount is None) == (s.rate is None):
                    err.add(f"slabs.{i}", "Each slab needs either an amount or a rate.")
                if s.to is not None and s.to < s.from_:
                    err.add(f"slabs.{i}", "A slab must end at or after its start.")
            ordered = sorted(data.slabs, key=lambda s: s.from_)
            for a, b in zip(ordered, ordered[1:]):
                if a.to is None or b.from_ <= a.to:
                    err.add("slabs", "Slabs must not overlap.")
                    break
        if data.formula == "balance_of_gross" and data.type != "earning":
            err.add("formula", "Balance of gross can only be an earning.")
        if data.formula not in ("percent", "slab") and (base or data.base_cap is not None):
            err.add("base", "Only percentage and slab components have a base.")
        err.raise_if_any()
        values = dict(name=name, type=data.type, formula=data.formula, rate=data.rate, base=base if data.formula in ("percent", "slab") else [],
                      base_cap=data.base_cap if data.formula in ("percent", "slab") else None, max_amount=data.max_amount,
                      slabs=[s.model_dump(by_alias=True) for s in data.slabs] if data.formula == "slab" else [], prorate=data.prorate, taxable=data.taxable,
                      statutory=data.statutory, active=data.active)
        if component_id is None:
            c = SalaryComponent(code=code, **values)
            self.session.add(c)
            before: dict = {}
        else:
            c = existing.get(component_id)
            if c is None:
                raise NotFoundError()
            ensure_version(c, data.version)
            if code != c.code:
                raise ValidationFailedError(details=[{"field": "code", "message": "The code of a component cannot be changed."}])
            before = self._component_setup_out(c, self._names(existing.values())).model_dump(exclude={"version"})
            for k, v in values.items():
                setattr(c, k, v)
        await self.session.flush()
        names = self._names((await self._components()).values())
        out = self._component_setup_out(c, names)
        self.audit.record(module=MODULE, action="salary_component.created" if not before else "salary_component.updated", summary=f"Salary component {c.code} saved",
                          entity_type="salary_component", entity_id=c.id, entity_label=c.name, changes=diff(before, out.model_dump(exclude={"version"})))
        await self.session.commit()
        return out

    # ---- Structures -------------------------------------------------------------------------------------------

    async def _structure_out(self, s: SalaryStructure, comps: dict, counts: dict) -> SalaryStructureOut:
        names = self._names(comps.values())
        items = [comps[cid] for cid in s.component_ids if cid in comps]
        return SalaryStructureOut(
            id=str(s.id), code=s.code, name=s.name, description=s.description,
            components=[StructureComponentOut(component_id=str(c.id), code=c.code, name=c.name, type=c.type, rule=describe(component_def(c), names)) for c in items],
            employees_assigned=counts.get(s.id, 0), effective_from=s.effective_from.isoformat(), active=s.active,
        )

    async def _assigned_counts(self) -> dict[uuid.UUID, int]:
        """Employees whose salary record in force today uses each structure."""
        today = company_today()
        latest = select(EmployeeSalary.employee_id, EmployeeSalary.structure_id).where(EmployeeSalary.effective_from <= today).distinct(EmployeeSalary.employee_id).order_by(EmployeeSalary.employee_id, EmployeeSalary.effective_from.desc()).subquery()
        rows = (await self.session.execute(select(latest.c.structure_id, func.count()).group_by(latest.c.structure_id))).all()
        return dict(rows)

    async def structures(self) -> list[SalaryStructureOut]:
        comps, counts = await self._components(), await self._assigned_counts()
        rows = (await self.session.scalars(select(SalaryStructure).order_by(SalaryStructure.code))).all()
        return [await self._structure_out(s, comps, counts) for s in rows]

    async def save_structure(self, structure_id: uuid.UUID | None, data: SalaryStructureIn) -> SalaryStructureOut:
        err = FieldErrors()
        code, name = data.code.strip().upper(), data.name.strip()
        if not CODE.match(code):
            err.add("code", "Use 1-20 capital letters, digits, '-' or '_'.")
        if not 2 <= len(name) <= 120:
            err.add("name", "Enter a name of 2-120 characters.")
        start = None
        try:
            start = parse_date(data.effective_from)
        except ValueError:
            pass
        if start is None:
            err.add("effectiveFrom", "Enter the date the structure takes effect.")
        comps = await self._components()
        ids = [body_id(i) for i in data.component_ids]
        if not ids:
            err.add("componentIds", "Add at least one component.")
        elif any(i not in comps for i in ids):
            err.add("componentIds", "Choose existing components.")
        elif len(set(ids)) != len(ids):
            err.add("componentIds", "Each component can appear once.")
        else:
            seen: set[str] = set()
            if not any(comps[i].type == "earning" for i in ids):
                err.add("componentIds", "Add at least one earning.")
            if sum(comps[i].formula == "balance_of_gross" for i in ids) > 1:
                err.add("componentIds", "Only one balance-of-gross component is possible.")
            for i in ids:
                c = comps[i]
                missing = [b for b in (c.base or []) if b != GROSS and b not in seen]
                if missing:
                    err.add("componentIds", f"{c.code} uses {', '.join(missing)}, which must come before it in the structure.")
                seen.add(c.code)
        existing = await self.session.scalar(select(SalaryStructure.id).where(SalaryStructure.code == code, SalaryStructure.id != (structure_id or uuid.uuid4())))
        if existing:
            err.add("code", "Another structure already uses this code.")
        err.raise_if_any()
        if structure_id is None:
            s = SalaryStructure(code=code, name=name, description=data.description.strip(), component_ids=ids, effective_from=start, active=data.active)
            self.session.add(s)
            created = True
        else:
            s = await self.session.get(SalaryStructure, structure_id)
            if s is None:
                raise NotFoundError()
            ensure_version(s, data.version)
            if code != s.code:
                raise ValidationFailedError(details=[{"field": "code", "message": "The code of a structure cannot be changed."}])
            s.name, s.description, s.component_ids, s.effective_from, s.active = name, data.description.strip(), ids, start, data.active
            created = False
        await self.session.flush()
        self.audit.record(module=MODULE, action="salary_structure.created" if created else "salary_structure.updated", summary=f"Salary structure {s.code} saved", entity_type="salary_structure", entity_id=s.id, entity_label=s.name)
        await self.session.commit()
        return await self._structure_out(s, comps, await self._assigned_counts())

    # ---- Employee salary records ---------------------------------------------------------------------------------

    async def add_salary(self, data: EmployeeSalaryIn, caller: Caller) -> EmployeeSalaryDetailOut:
        err = FieldErrors()
        employee = await self.session.get(Employee, body_id(data.employee_id)) if body_id(data.employee_id) else None
        if employee is None or await self.session.scalar(select(Employee.id).where(Employee.id == employee.id, EmployeeScopeService.clause(caller.scope))) is None:
            err.add("employeeId", "Choose an employee within your organizational scope.")
        structure = await self.session.get(SalaryStructure, body_id(data.structure_id)) if body_id(data.structure_id) else None
        if structure is None:
            err.add("structureId", "Choose an existing salary structure.")
        elif not structure.active:
            err.add("structureId", "This structure is not active.")
        start = None
        try:
            start = parse_date(data.effective_from)
        except ValueError:
            pass
        if start is None:
            err.add("effectiveFrom", "Enter the date the salary takes effect.")
        elif employee is not None and start < employee.joining_date:
            err.add("effectiveFrom", "The salary cannot start before the joining date.")
        reason = data.reason.strip()
        if len(reason) < 3:
            err.add("reason", "Enter the reason for this salary record.")
        comps = await self._components()
        values: dict[str, dict] = {}
        if structure is not None:
            in_structure = set(structure.component_ids)
            for i, v in enumerate(data.values):
                cid = body_id(v.component_id)
                if cid not in in_structure:
                    err.add(f"values.{i}.componentId", "This component is not part of the structure.")
                    continue
                c = comps[cid]
                if c.formula == "fixed" and v.amount is None:
                    err.add(f"values.{i}.amount", f"Enter the monthly amount of {c.code}.")
                if c.formula not in ("fixed", "overtime_rate") and (v.amount is not None or v.rate is not None):
                    err.add(f"values.{i}", f"{c.code} is calculated by its formula; it takes no per-employee value.")
                values[str(cid)] = {"amount": v.amount, "rate": v.rate}
            for cid in structure.component_ids:
                c = comps.get(cid)
                if c and c.formula == "fixed" and str(cid) not in values:
                    err.add("values", f"Enter the monthly amount of {c.code}.")
                if c and c.formula == "balance_of_gross" and data.monthly_gross is None:
                    err.add("monthlyGross", f"{c.code} is the balance of the monthly gross: enter the monthly gross.")
                if c and c.formula == "percent" and GROSS in (c.base or []) and c.type == "earning" and data.monthly_gross is None:
                    err.add("monthlyGross", f"{c.code} is a percentage of the monthly gross: enter the monthly gross.")
        if employee is not None and start is not None and await self.session.scalar(select(EmployeeSalary.id).where(EmployeeSalary.employee_id == employee.id, EmployeeSalary.effective_from == start)):
            err.add("effectiveFrom", "A salary record for this employee already starts on this date.")
        err.raise_if_any()
        record = EmployeeSalary(employee_id=employee.id, structure_id=structure.id, effective_from=start, monthly_gross=data.monthly_gross, values=values, reason=reason)
        self.session.add(record)
        await self.session.flush()
        self.audit.record(module=MODULE, action="employee_salary.recorded", summary=f"Salary record for {employee.employee_code} from {start.isoformat()} ({structure.code}): {reason}",
                          entity_type="employee_salary", entity_id=record.id, entity_label=employee.full_name)
        await self.session.commit()
        return await self.salary(employee.id, caller)

    @staticmethod
    def monthly_gross(record: EmployeeSalary, structure: SalaryStructure, comps: dict) -> float | None:
        """The salary record's monthly gross: as entered, else the sum of its fixed earnings."""
        if record.monthly_gross is not None:
            return float(record.monthly_gross)
        total = 0.0
        for cid in structure.component_ids:
            c = comps.get(cid)
            if c and c.type == "earning" and c.formula == "fixed":
                total += float(record.values.get(str(cid), {}).get("amount") or 0)
        return total

    async def _current(self, employee_ids: list[uuid.UUID], on: date) -> dict[uuid.UUID, EmployeeSalary]:
        if not employee_ids:
            return {}
        rows = (await self.session.scalars(select(EmployeeSalary).where(EmployeeSalary.employee_id.in_(employee_ids), EmployeeSalary.effective_from <= on)
                                           .distinct(EmployeeSalary.employee_id).order_by(EmployeeSalary.employee_id, EmployeeSalary.effective_from.desc()))).all()
        return {r.employee_id: r for r in rows}

    async def salaries(self, caller: Caller, *, q: str | None, department_id: str | None, missing_only: bool, sort: str | None, page: int, page_size: int, currency: str) -> Page:
        today = company_today()
        stmt = select(Employee).where(EmployeeScopeService.clause(caller.scope))
        if department_id:
            stmt = stmt.where(Employee.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        if q:
            stmt = stmt.where(text_match(q))
        if missing_only:
            stmt = stmt.where(~select(EmployeeSalary.id).where(EmployeeSalary.employee_id == Employee.id, EmployeeSalary.effective_from <= today).exists())
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        name, _, direction = (sort or "employee:asc").partition(":")
        if name not in ("employee", "employeeCode"):
            from app.core.errors import BadRequestError
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": "Use employee or employeeCode with :asc or :desc."}])
        col = func.lower(Employee.full_name) if name == "employee" else Employee.employee_code
        stmt = stmt.order_by(col.desc() if direction == "desc" else col.asc(), Employee.id).limit(page_size).offset((page - 1) * page_size)
        employees = list((await self.session.scalars(stmt)).all())
        current = await self._current([e.id for e in employees], today)
        structures = {s.id: s for s in (await self.session.scalars(select(SalaryStructure))).all()}
        comps, depts = await self._components(), await departments(self.session)
        items = []
        for e in employees:
            r = current.get(e.id)
            s = structures.get(r.structure_id) if r else None
            items.append(EmployeeSalaryRowOut(employee=employee_ref(e, depts), structure=StructureRefOut(id=str(s.id), name=s.name) if s else None,
                                              effective_from=r.effective_from.isoformat() if r else None, monthly_gross=amt(self.monthly_gross(r, s, comps), True) if r else None, currency=currency))
        return Page.build(PageResult(employees, page, page_size, total), items)

    async def salary(self, employee_id: uuid.UUID, caller: Caller, currency: str = "") -> EmployeeSalaryDetailOut:
        employee = await self.session.get(Employee, employee_id)
        if employee is None or await self.session.scalar(select(Employee.id).where(Employee.id == employee_id, EmployeeScopeService.clause(caller.scope))) is None:
            raise NotFoundError()
        records = list((await self.session.scalars(select(EmployeeSalary).where(EmployeeSalary.employee_id == employee_id).order_by(EmployeeSalary.effective_from.desc()))).all())
        structures = {s.id: s for s in (await self.session.scalars(select(SalaryStructure))).all()}
        comps, depts = await self._components(), await departments(self.session)
        today = company_today()
        current = next((r for r in records if r.effective_from <= today), None)
        s = structures.get(current.structure_id) if current else None
        lines = []
        if current and s:
            for cid in s.component_ids:
                c = comps.get(cid)
                if c is None:
                    continue
                v = current.values.get(str(cid), {})
                value = v.get("amount") if c.formula == "fixed" else (v.get("rate") if c.formula == "overtime_rate" else None)
                lines.append(ResultLineOut(component=ComponentRefOut(code=c.code, name=c.name, type=c.type), amount=float(value) if value is not None else None))
        history = [SalaryHistoryOut(effective_from=r.effective_from.isoformat(), structure_name=structures[r.structure_id].name, monthly_gross=self.monthly_gross(r, structures[r.structure_id], comps), reason=r.reason) for r in records]
        return EmployeeSalaryDetailOut(
            employee=employee_ref(employee, depts), structure=StructureRefOut(id=str(s.id), name=s.name) if s else None, effective_from=current.effective_from.isoformat() if current else None,
            monthly_gross=self.monthly_gross(current, s, comps) if current else None, currency=currency or await self.latest_currency(), lines=lines, history=history,
        )

    async def latest_currency(self) -> str:
        """The currency of the newest payroll period ("" while no period exists: there is no default currency)."""
        return await self.session.scalar(select(PayrollPeriod.currency).order_by(PayrollPeriod.month.desc()).limit(1)) or ""

    # ---- Periods --------------------------------------------------------------------------------------------------

    async def create_period(self, data: PayrollPeriodIn) -> PayrollPeriodOut:
        err = FieldErrors()
        month = data.month.strip()
        if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", month):
            err.add("month", "Enter the month as YYYY-MM.")
        currency = data.currency.strip().upper()
        if not re.match(r"^[A-Z]{3}$", currency):
            err.add("currency", "Enter the ISO 4217 currency code, for example INR.")
        if not err.has("month") and await self.session.scalar(select(PayrollPeriod.id).where(PayrollPeriod.month == month)):
            err.add("month", "A payroll period for this month already exists.")
        err.raise_if_any()
        start, end = month_bounds(month)
        p = PayrollPeriod(month=month, from_date=start, to_date=end, status="open", currency=currency)
        self.session.add(p)
        await self.session.flush()
        self.session.add(PayrollPeriodEvent(period_id=p.id, action="updated", comment="Period opened"))
        self.audit.record(module=MODULE, action="payroll_period.created", summary=f"Payroll period {month} ({currency}) opened", entity_type="payroll_period", entity_id=p.id, entity_label=month)
        await self.session.commit()
        return await period_out(self.session, p)
