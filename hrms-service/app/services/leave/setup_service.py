"""Leave configuration entered by HR (additions under /hr/setup, `hr.leave-policies:manage`), and
the read-only lookups of the frontend (leave types, holidays, leave policies).

Nothing is pre-filled: no leave type, policy, entitlement or holiday exists until HR enters it.
Every change is audited. Codes of leave types never change (database trigger, as in Module 1).
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import false, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Principal
from app.core.errors import ConflictError, NotFoundError, PeriodLockedError, ValidationFailedError
from app.core.permissions import P, has_any
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.models.leave_model import Holiday, LeaveLedgerEntry, LeavePolicy, LeaveType
from app.models.reference_data_model import EmploymentType, WorkLocation
from app.schemas.employee_schema import NamedRefOut
from app.schemas.leave_schema import (
    AccrualOut,
    CarryForwardOut,
    HolidayIn,
    HolidayOut,
    HolidaySetupOut,
    LeavePolicyIn,
    LeavePolicyOut,
    LeavePolicySetupOut,
    LeaveTypeIn,
    LeaveTypeOut,
    LeaveTypeRefOut,
    LedgerEntryIn,
    LedgerEntryOut,
)
from app.services.attendance.attendance_data import is_locked
from app.services.attendance.attendance_read_service import employee_ref
from app.services.attendance.jobs import enqueue_recalculation
from app.services.audit_service import AuditService, diff
from app.services.employee_scope_service import EmployeeScopeService, caller_employee_id
from app.services.employee_support import Caller, company_today, parse_date
from app.services.leave.calendar import holiday_clause
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

MODULE = "Leave"


def type_ref(t: LeaveType) -> LeaveTypeRefOut:
    return LeaveTypeRefOut(id=str(t.id), code=t.code, name=t.name)


def type_out(t: LeaveType) -> LeaveTypeOut:
    return LeaveTypeOut(id=str(t.id), code=t.code, name=t.name, paid=t.paid, allow_half_day=t.allow_half_day, balance_tracked=t.balance_tracked, attachment_after_days=t.attachment_after_days, active=t.active)


def _num(v) -> float:
    return float(v) if v is not None else 0.0


def policy_applies(p: LeavePolicy, employee: Employee, on: date) -> bool:
    return (
        p.effective_from <= on and (p.effective_to is None or on <= p.effective_to)
        and (not p.employment_type_ids or employee.employment_type_id in p.employment_type_ids)
        and (not p.department_ids or employee.department_id in p.department_ids)
    )


async def policy_for(session: AsyncSession, employee: Employee, leave_type_id: uuid.UUID, on: date) -> LeavePolicy | None:
    rows = (await session.scalars(select(LeavePolicy).where(LeavePolicy.leave_type_id == leave_type_id))).all()
    return next((p for p in rows if policy_applies(p, employee, on)), None)


class LeaveSetupService:
    def __init__(self, session: AsyncSession, principal: Principal | None = None):
        self.session = session
        self.principal = principal
        self.audit = AuditService(session)

    # ---- Leave types ----------------------------------------------------------------------------------

    async def leave_types(self) -> list[LeaveTypeOut]:
        rows = (await self.session.scalars(select(LeaveType).order_by(func.lower(LeaveType.name)))).all()
        return [type_out(t) for t in rows]

    async def save_type(self, type_id: uuid.UUID | None, data: LeaveTypeIn) -> LeaveTypeOut:
        err = FieldErrors()
        code, name = data.code.strip(), data.name.strip()
        if not code or len(code) > 20 or not all(c.isalnum() or c in "_-" for c in code):
            err.add("code", "Use 1-20 letters, digits, '-' or '_'.")
        if len(name) < 2 or len(name) > 120:
            err.add("name", "Enter a name of 2-120 characters.")
        if data.attachment_after_days is not None and not 0 <= data.attachment_after_days <= 365:
            err.add("attachmentAfterDays", "Enter 0-365 days, or leave it empty.")
        if await self.session.scalar(select(LeaveType.id).where(func.lower(LeaveType.code) == code.lower(), LeaveType.id != (type_id or uuid.uuid4()))):
            err.add("code", "Another leave type already uses this code.")
        err.raise_if_any()
        if type_id is None:
            t = LeaveType(code=code, name=name, paid=data.paid, allow_half_day=data.allow_half_day, balance_tracked=data.balance_tracked, attachment_after_days=data.attachment_after_days, active=data.active)
            self.session.add(t)
            before: dict = {}
        else:
            t = await self.session.get(LeaveType, type_id)
            if t is None:
                raise NotFoundError()
            ensure_version(t, data.version)
            if code != t.code:
                raise ValidationFailedError(details=[{"field": "code", "message": "The code of a leave type cannot be changed."}])
            before = type_out(t).model_dump()
            t.name, t.paid, t.allow_half_day, t.balance_tracked, t.attachment_after_days, t.active = name, data.paid, data.allow_half_day, data.balance_tracked, data.attachment_after_days, data.active
        try:
            await self.session.flush()
        except IntegrityError:
            raise ValidationFailedError(details=[{"field": "code", "message": "Another leave type already uses this code."}]) from None
        self.audit.record(module=MODULE, action="leave_type.created" if not before else "leave_type.updated", summary=f"Leave type {t.code} saved", entity_type="leave_type", entity_id=t.id, entity_label=t.name,
                          changes=diff(before, type_out(t).model_dump()))
        await self.session.commit()
        return type_out(t)

    # ---- Leave policies ---------------------------------------------------------------------------------

    async def _policy_out(self, p: LeavePolicy, types: dict, etypes: dict, depts: dict) -> LeavePolicySetupOut:
        t = types[p.leave_type_id]
        parts = []
        if p.employment_type_ids:
            parts.append(", ".join(etypes.get(i, "?") for i in p.employment_type_ids))
        if p.department_ids:
            parts.append(", ".join(depts.get(i, "?") for i in p.department_ids))
        return LeavePolicySetupOut(
            id=str(p.id), leave_type=type_ref(t), accrual=AccrualOut(method=p.accrual_method, days=_num(p.accrual_days)),
            carry_forward=CarryForwardOut(allowed=p.carry_forward_allowed, max_days=float(p.carry_forward_max_days) if p.carry_forward_max_days is not None else None),
            effective_from=p.effective_from.isoformat(), effective_to=p.effective_to.isoformat() if p.effective_to else None,
            applies_to=" · ".join(parts) if parts else "All employees",
            allow_half_day=t.allow_half_day if p.allow_half_day is None else p.allow_half_day,
            attachment_after_days=p.attachment_after_days if p.attachment_after_days is not None else t.attachment_after_days,
            employment_type_ids=[str(i) for i in p.employment_type_ids], department_ids=[str(i) for i in p.department_ids], version=p.version,
        )

    async def _names(self) -> tuple[dict, dict, dict]:
        types = {t.id: t for t in (await self.session.scalars(select(LeaveType))).all()}
        etypes = {e.id: e.name for e in (await self.session.scalars(select(EmploymentType))).all()}
        depts = {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}
        return types, etypes, depts

    async def policies(self, *, setup: bool = False) -> list:
        types, etypes, depts = await self._names()
        rows = (await self.session.scalars(select(LeavePolicy).order_by(LeavePolicy.effective_from.desc()))).all()
        out = [await self._policy_out(p, types, etypes, depts) for p in rows]
        out.sort(key=lambda p: (p.leave_type.name.lower(), p.effective_from), reverse=False)
        if setup:
            return out
        return [LeavePolicyOut.model_validate(p.model_dump()) for p in out]

    async def save_policy(self, policy_id: uuid.UUID | None, data: LeavePolicyIn) -> LeavePolicySetupOut:
        err = FieldErrors()
        types, etypes, depts = await self._names()
        type_id = body_id(data.leave_type_id)
        if type_id not in types:
            err.add("leaveTypeId", "Choose an existing leave type.")
        start = end = None
        try:
            start = parse_date(data.effective_from)
        except ValueError:
            pass
        if start is None:
            err.add("effectiveFrom", "Enter the date the policy takes effect.")
        try:
            end = parse_date(data.effective_to)
        except ValueError:
            err.add("effectiveTo", "Enter a valid date.")
        if start and end and end < start:
            err.add("effectiveTo", "The end date must be on or after the start date.")
        if data.accrual_method == "none" and data.accrual_days:
            err.add("accrualDays", "A policy without accrual has no days.")
        if data.accrual_method != "none" and not 0 < data.accrual_days <= 366:
            err.add("accrualDays", "Enter the days credited (more than 0, at most 366).")
        if round(data.accrual_days * 2) != data.accrual_days * 2:
            err.add("accrualDays", "Use whole or half days.")
        if data.carry_forward_max_days is not None and (not data.carry_forward_allowed or data.carry_forward_max_days < 0):
            err.add("carryForwardMaxDays", "A maximum needs carry-forward allowed and cannot be negative.")
        if data.attachment_after_days is not None and not 0 <= data.attachment_after_days <= 365:
            err.add("attachmentAfterDays", "Enter 0-365 days, or leave it empty.")
        et_ids = [body_id(i) for i in data.employment_type_ids]
        dept_ids = [body_id(i) for i in data.department_ids]
        if any(i not in etypes for i in et_ids):
            err.add("employmentTypeIds", "Choose existing employment types.")
        if any(i not in depts for i in dept_ids):
            err.add("departmentIds", "Choose existing departments.")
        err.raise_if_any()
        if data.accrual_method != "none" and not types[type_id].balance_tracked:
            raise ValidationFailedError(details=[{"field": "accrualMethod", "message": "This leave type does not track a balance, so it has no accrual."}])
        # At most one policy applies to an employee, type and date.
        others = (await self.session.scalars(select(LeavePolicy).where(LeavePolicy.leave_type_id == type_id, LeavePolicy.id != (policy_id or uuid.uuid4())))).all()
        for o in others:
            dates = o.effective_from <= (end or date.max) and start <= (o.effective_to or date.max)
            et = not o.employment_type_ids or not et_ids or set(o.employment_type_ids) & set(et_ids)
            dp = not o.department_ids or not dept_ids or set(o.department_ids) & set(dept_ids)
            if dates and et and dp:
                raise ValidationFailedError(details=[{"field": "effectiveFrom", "message": f"Another policy of this leave type (from {o.effective_from.isoformat()}) applies to some of the same employees in this period."}])
        values = dict(leave_type_id=type_id, accrual_method=data.accrual_method, accrual_days=data.accrual_days, carry_forward_allowed=data.carry_forward_allowed,
                      carry_forward_max_days=data.carry_forward_max_days, effective_from=start, effective_to=end, employment_type_ids=et_ids, department_ids=dept_ids,
                      allow_half_day=data.allow_half_day, attachment_after_days=data.attachment_after_days)
        if policy_id is None:
            p = LeavePolicy(**values)
            self.session.add(p)
            before: dict = {}
        else:
            p = await self.session.get(LeavePolicy, policy_id)
            if p is None:
                raise NotFoundError()
            ensure_version(p, data.version)
            before = (await self._policy_out(p, types, etypes, depts)).model_dump(exclude={"version"})
            used = await self.session.scalar(select(LeaveLedgerEntry.id).where(LeaveLedgerEntry.leave_policy_id == p.id).limit(1))
            if used and (p.leave_type_id != type_id or p.accrual_method != data.accrual_method or float(p.accrual_days) != data.accrual_days or p.effective_from != start):
                # Credits were made under this version: it is closed and a new version is entered (G6).
                raise ConflictError("Credits were already made under this policy. Set its end date and enter a new policy for the changed rules.", code="POLICY_IN_USE")
            for k, v in values.items():
                setattr(p, k, v)
        await self.session.flush()
        out = await self._policy_out(p, types, etypes, depts)
        self.audit.record(module=MODULE, action="leave_policy.created" if not before else "leave_policy.updated", summary=f"Leave policy for {out.leave_type.code} from {out.effective_from} saved",
                          entity_type="leave_policy", entity_id=p.id, entity_label=out.leave_type.name, changes=diff(before, out.model_dump(exclude={"version"})))
        await self.session.commit()
        return out

    # ---- Holidays ------------------------------------------------------------------------------------------

    @staticmethod
    def _holiday_out(h: Holiday, locations: dict) -> HolidaySetupOut:
        loc = NamedRefOut(id=str(h.work_location_id), name=locations.get(h.work_location_id, "")) if h.work_location_id else None
        return HolidaySetupOut(id=str(h.id), date=h.date.isoformat(), name=h.name, type=h.type, location=loc, version=h.version)

    async def holidays_for_caller(self, year: int | None) -> list[HolidayOut]:
        """Owner decision 4: the caller's applicable holidays (company-wide + their location), all for HR."""
        year = year or company_today().year
        stmt = select(Holiday).where(Holiday.date >= date(year, 1, 1), Holiday.date <= date(year, 12, 31)).order_by(Holiday.date, Holiday.name)
        hr = self.principal is not None and has_any(self.principal.permissions, (P.LEAVE_POLICIES_VIEW, P.LEAVE_POLICIES_MANAGE, P.LEAVE_VIEW))
        if not hr:
            me = caller_employee_id(self.principal) if self.principal else None
            employee = await self.session.get(Employee, me) if me else None
            stmt = stmt.where(holiday_clause(employee.work_location_id if employee else None))
        return [HolidayOut(date=h.date.isoformat(), name=h.name, type=h.type) for h in (await self.session.scalars(stmt)).all()]

    async def holidays_setup(self, year: int | None) -> list[HolidaySetupOut]:
        locations = {loc.id: loc.name for loc in (await self.session.scalars(select(WorkLocation))).all()}
        stmt = select(Holiday).order_by(Holiday.date, Holiday.name)
        if year:
            stmt = stmt.where(Holiday.date >= date(year, 1, 1), Holiday.date <= date(year, 12, 31))
        return [self._holiday_out(h, locations) for h in (await self.session.scalars(stmt)).all()]

    async def _after_holiday_change(self, days: list[date], location_ids: list[uuid.UUID | None]) -> None:
        """Holidays change attendance: locked dates are refused; finished dates are recalculated."""
        if any([await is_locked(self.session, d, d) for d in days]):
            raise PeriodLockedError("This date is in a finalized payroll period, so its holidays can no longer change.")
        past = [d for d in days if d < company_today()]
        if not past:
            return
        stmt = select(Employee.id).where(Employee.joining_date <= max(past))
        if None not in location_ids:
            stmt = stmt.where(Employee.work_location_id.in_([i for i in location_ids if i]))
        ids = list((await self.session.scalars(stmt)).all())
        if ids:
            await enqueue_recalculation(self.session, ids, min(past), max(past), reason="holiday changed")

    async def save_holiday(self, holiday_id: uuid.UUID | None, data: HolidayIn) -> HolidaySetupOut:
        err = FieldErrors()
        locations = {loc.id: loc.name for loc in (await self.session.scalars(select(WorkLocation))).all()}
        day = None
        try:
            day = parse_date(data.date)
        except ValueError:
            pass
        if day is None:
            err.add("date", "Enter the date as YYYY-MM-DD.")
        name = data.name.strip()
        if len(name) < 2 or len(name) > 120:
            err.add("name", "Enter a name of 2-120 characters.")
        location_id = body_id(data.work_location_id) if data.work_location_id else None
        if data.work_location_id and location_id not in locations:
            err.add("workLocationId", "Choose an existing work location, or leave it empty for all locations.")
        if day and not err.has("workLocationId"):
            same = select(Holiday.id).where(Holiday.date == day, Holiday.id != (holiday_id or uuid.uuid4()))
            same = same.where(Holiday.work_location_id == location_id) if location_id else same.where(Holiday.work_location_id.is_(None))
            if await self.session.scalar(same):
                err.add("date", "A holiday for this date and location already exists.")
        err.raise_if_any()
        if holiday_id is None:
            h = Holiday(date=day, name=name, type=data.type, work_location_id=location_id)
            self.session.add(h)
            before: dict = {}
            await self._after_holiday_change([day], [location_id])
        else:
            h = await self.session.get(Holiday, holiday_id)
            if h is None:
                raise NotFoundError()
            ensure_version(h, data.version)
            before = self._holiday_out(h, locations).model_dump(exclude={"version"})
            if (h.date, h.work_location_id) != (day, location_id):
                await self._after_holiday_change([h.date, day], [h.work_location_id, location_id])
            h.date, h.name, h.type, h.work_location_id = day, name, data.type, location_id
        try:
            await self.session.flush()
        except IntegrityError:
            raise ValidationFailedError(details=[{"field": "date", "message": "A holiday for this date and location already exists."}]) from None
        out = self._holiday_out(h, locations)
        self.audit.record(module=MODULE, action="holiday.created" if not before else "holiday.updated", summary=f"Holiday {out.name} on {out.date} saved", entity_type="holiday", entity_id=h.id, entity_label=out.name,
                          changes=diff(before, out.model_dump(exclude={"version"})))
        await self.session.commit()
        return out

    async def delete_holiday(self, holiday_id: uuid.UUID) -> None:
        h = await self.session.get(Holiday, holiday_id)
        if h is None:
            raise NotFoundError()
        await self._after_holiday_change([h.date], [h.work_location_id])
        self.audit.record(module=MODULE, action="holiday.deleted", summary=f"Holiday {h.name} on {h.date.isoformat()} removed", entity_type="holiday", entity_id=h.id, entity_label=h.name)
        await self.session.delete(h)
        await self.session.commit()

    # ---- Ledger: allocations, adjustments, history ---------------------------------------------------------

    async def add_entry(self, entry_type: str, data: LedgerEntryIn, caller: Caller) -> LedgerEntryOut:
        """HR allocation (+days) or adjustment (± days, e.g. opening balances), always with a reason."""
        err = FieldErrors()
        employee_id, type_id = body_id(data.employee_id), body_id(data.leave_type_id)
        employee = await self.session.get(Employee, employee_id) if employee_id else None
        in_scope = employee is not None and await self.session.scalar(select(Employee.id).where(Employee.id == employee.id, EmployeeScopeService.clause(caller.scope))) is not None
        if not in_scope:
            err.add("employeeId", "Choose an employee within your organizational scope.")
        leave_type = await self.session.get(LeaveType, type_id) if type_id else None
        if leave_type is None:
            err.add("leaveTypeId", "Choose an existing leave type.")
        elif not leave_type.balance_tracked:
            err.add("leaveTypeId", "This leave type does not track a balance.")
        if not 2000 <= data.year <= 2100:
            err.add("year", "Enter the leave year.")
        if round(data.days * 2) != data.days * 2 or data.days == 0 or abs(data.days) > 366:
            err.add("days", "Enter whole or half days (not 0).")
        elif entry_type == "allocation" and data.days < 0:
            err.add("days", "An allocation adds days; use an adjustment to remove days.")
        reason = data.reason.strip()
        if len(reason) < 3:
            err.add("reason", "Enter the reason for this entry.")
        err.raise_if_any()
        entry = LeaveLedgerEntry(employee_id=employee.id, leave_type_id=leave_type.id, leave_year=data.year, entry_type=entry_type, days=data.days, reason=reason)
        self.session.add(entry)
        await self.session.flush()
        self.audit.record(module=MODULE, action=f"leave_balance.{entry_type}", summary=f"{data.days:+g} days {leave_type.code} {data.year} for {employee.employee_code}: {reason}",
                          entity_type="leave_ledger_entry", entity_id=entry.id, entity_label=employee.full_name)
        await self.session.commit()
        return await self._entry_out(entry)

    async def _entry_out(self, e: LeaveLedgerEntry, cache: dict | None = None) -> LedgerEntryOut:
        cache = cache if cache is not None else {}
        if "depts" not in cache:
            cache["depts"] = {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}
            cache["types"] = {t.id: t for t in (await self.session.scalars(select(LeaveType))).all()}
        employee = cache.get(e.employee_id) or await self.session.get(Employee, e.employee_id)
        cache[e.employee_id] = employee
        return LedgerEntryOut(
            id=str(e.id), employee=employee_ref(employee, cache["depts"]), leave_type=type_ref(cache["types"][e.leave_type_id]), year=e.leave_year, entry_type=e.entry_type,
            days=float(e.days), leave_request_id=str(e.leave_request_id) if e.leave_request_id else None, reason=e.reason, created_at=e.created_at, created_by=e.created_by_name,
        )

    async def ledger(self, caller: Caller, *, employee_id: str | None, leave_type_id: str | None, year: int | None, page: int, page_size: int):
        stmt = select(LeaveLedgerEntry).join(Employee, Employee.id == LeaveLedgerEntry.employee_id).where(EmployeeScopeService.clause(caller.scope))
        if employee_id:
            stmt = stmt.where(LeaveLedgerEntry.employee_id == body_id(employee_id)) if body_id(employee_id) else stmt.where(false())
        if leave_type_id:
            stmt = stmt.where(LeaveLedgerEntry.leave_type_id == body_id(leave_type_id)) if body_id(leave_type_id) else stmt.where(false())
        if year:
            stmt = stmt.where(LeaveLedgerEntry.leave_year == year)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self.session.scalars(stmt.order_by(LeaveLedgerEntry.created_at.desc(), LeaveLedgerEntry.id).limit(page_size).offset((page - 1) * page_size))).all()
        cache: dict = {}
        return total, [await self._entry_out(e, cache) for e in rows]

