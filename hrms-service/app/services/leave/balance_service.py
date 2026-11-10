"""Leave balances from the append-only ledger (owner decision 5: balances are never edited).

Signs: credits are positive (allocation, accrual, carry_forward, usage_reversal, positive
adjustments), debits negative (usage, lapse, negative adjustments). For a leave year:
- allocated      = allocation + accrual           (null when the type tracks no balance)
- carriedForward = carry_forward
- used           = -(usage + usage_reversal)
- pending        = days of pending requests charged to that year (computed, not in the ledger)
- available      = sum of all entries - pending   (null when the type tracks no balance)

Accrual (`leave.accrue`, daily, idempotent through period keys) applies ONLY the policies HR has
entered: `annual` credits the policy's days once per leave year, `monthly` once per month, to
employees employed then and covered by the policy. No proration (L7, L8). Carry-forward (L9): at
the start of a leave year, where the policy in force on the last day of the old year allows it,
the old year's remaining balance (capped at maxDays when set) is credited to the new year and the
old year's remainder is closed with a `lapse` entry.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import Float, case, cast, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import SYSTEM_ACTOR_ID, SYSTEM_ACTOR_NAME
from app.core.errors import ForbiddenError, NotFoundError
from app.core.permissions import P
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.models.leave_model import LeaveLedgerEntry, LeavePolicy, LeaveRequest, LeaveType
from app.models.reference_data_model import EmployeeStatus
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import text_match
from app.schemas.common import Page
from app.schemas.leave_schema import EmployeeBalancesOut, LeaveBalanceOut
from app.services.attendance.attendance_read_service import employee_ref
from app.services.audit_service import AuditService
from app.services.employee_scope_service import EmployeeScopeService, caller_employee_id
from app.services.employee_support import Caller, company_today
from app.services.leave.calendar import leave_year_bounds, leave_year_of, leave_year_start_month
from app.services.leave.setup_service import policy_applies, type_ref
from app.utils.ids import body_id

CREDIT_ALLOCATED = ("allocation", "accrual")
CREDIT_BATCH = 1000


async def ledger_sums(session: AsyncSession, employee_ids: list[uuid.UUID], year: int) -> dict[tuple, dict[str, float]]:
    """{(employee, type): {entry_type: sum}} for one leave year."""
    out: dict[tuple, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    if not employee_ids:
        return out
    rows = (await session.execute(
        select(LeaveLedgerEntry.employee_id, LeaveLedgerEntry.leave_type_id, LeaveLedgerEntry.entry_type, func.sum(LeaveLedgerEntry.days))
        .where(LeaveLedgerEntry.employee_id.in_(employee_ids), LeaveLedgerEntry.leave_year == year)
        .group_by(LeaveLedgerEntry.employee_id, LeaveLedgerEntry.leave_type_id, LeaveLedgerEntry.entry_type)
    )).all()
    for emp, typ, kind, total in rows:
        out[(emp, typ)][kind] = float(total)
    return out


async def pending_sums(session: AsyncSession, employee_ids: list[uuid.UUID], year: int, *, exclude: uuid.UUID | None = None) -> dict[tuple, float]:
    out: dict[tuple, float] = defaultdict(float)
    if not employee_ids:
        return out
    days = cast(LeaveRequest.days_by_year[str(year)].astext, Float)
    stmt = (select(LeaveRequest.employee_id, LeaveRequest.leave_type_id, func.sum(days))
            .where(LeaveRequest.employee_id.in_(employee_ids), LeaveRequest.status == "pending", LeaveRequest.days_by_year.has_key(str(year)))
            .group_by(LeaveRequest.employee_id, LeaveRequest.leave_type_id))
    if exclude:
        stmt = stmt.where(LeaveRequest.id != exclude)
    for emp, typ, total in (await session.execute(stmt)).all():
        out[(emp, typ)] = float(total or 0)
    return out


def balance_out(t: LeaveType, sums: dict[str, float], pending: float) -> LeaveBalanceOut:
    allocated = sum(sums.get(k, 0.0) for k in CREDIT_ALLOCATED)
    used = -(sums.get("usage", 0.0) + sums.get("usage_reversal", 0.0))
    available = sum(sums.values()) - pending
    return LeaveBalanceOut(
        leave_type=type_ref(t), allocated=round(allocated, 2) if t.balance_tracked else None, carried_forward=round(sums.get("carry_forward", 0.0), 2),
        used=round(used, 2), pending=round(pending, 2), available=round(available, 2) if t.balance_tracked else None,
    )


async def available_days(session: AsyncSession, employee_id: uuid.UUID, leave_type_id: uuid.UUID, year: int, *, exclude: uuid.UUID | None = None) -> float:
    sums = await ledger_sums(session, [employee_id], year)
    pending = await pending_sums(session, [employee_id], year, exclude=exclude)
    return round(sum(sums[(employee_id, leave_type_id)].values()) - pending[(employee_id, leave_type_id)], 2)


class BalanceService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller

    async def _rows(self, employees: list[Employee], year: int) -> list[EmployeeBalancesOut]:
        ids = [e.id for e in employees]
        types = {t.id: t for t in (await self.session.scalars(select(LeaveType))).all()}
        sums = await ledger_sums(self.session, ids, year)
        pending = await pending_sums(self.session, ids, year)
        departments = {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}
        out = []
        ordered = sorted(types.values(), key=lambda t: t.name.lower())
        for e in employees:
            balances = [balance_out(t, sums.get((e.id, t.id), {}), pending.get((e.id, t.id), 0.0)) for t in ordered if t.active or (e.id, t.id) in sums or (e.id, t.id) in pending]
            out.append(EmployeeBalancesOut(employee=employee_ref(e, departments), balances=balances))
        return out

    async def list(self, *, year: int | None, department_id: str | None, q: str | None, page: int, page_size: int) -> Page:
        year = year or leave_year_of(company_today(), await leave_year_start_month(self.session))
        stmt = select(Employee).where(EmployeeScopeService.clause(self.caller.scope))
        if department_id:
            dept = body_id(department_id)
            stmt = stmt.where(Employee.department_id == dept) if dept else stmt.where(text("false"))
        if q:
            stmt = stmt.where(text_match(q))
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        employees = list((await self.session.scalars(stmt.order_by(func.lower(Employee.full_name), Employee.id).limit(page_size).offset((page - 1) * page_size))).all())
        return Page.build(PageResult(employees, page, page_size, total), await self._rows(employees, year))

    async def mine(self, year: int | None) -> EmployeeBalancesOut:
        if not self.caller.has(P.SELF_VIEW):
            raise ForbiddenError()
        me = caller_employee_id(self.caller.principal)
        employee = await self.session.get(Employee, me) if me else None
        if employee is None:
            raise NotFoundError("Your sign-in is not linked to an employee record.")
        year = year or leave_year_of(company_today(), await leave_year_start_month(self.session))
        return (await self._rows([employee], year))[0]


# ---- Worker: accrual and carry-forward ------------------------------------------------------------------------


async def _credit(session: AsyncSession, rows: list[dict]) -> int:
    """Inserts ledger entries in batches; an entry whose period key already exists is skipped (idempotent)."""
    inserted = 0
    for r in rows:
        r.update(id=uuid.uuid4(), created_by=SYSTEM_ACTOR_ID, created_by_name=SYSTEM_ACTOR_NAME, updated_by=SYSTEM_ACTOR_ID, updated_by_name=SYSTEM_ACTOR_NAME)
    for i in range(0, len(rows), CREDIT_BATCH):  # PostgreSQL allows at most 32,767 parameters per statement
        stmt = insert(LeaveLedgerEntry).values(rows[i : i + CREDIT_BATCH]).on_conflict_do_nothing(index_elements=["employee_id", "leave_type_id", "period_key"], index_where=text("period_key IS NOT NULL"))
        inserted += len((await session.execute(stmt.returning(LeaveLedgerEntry.id))).all())
    return inserted


async def _employed(session: AsyncSession, on: date) -> list[Employee]:
    ended = set((await session.scalars(select(EmployeeStatus.code).where(EmployeeStatus.employment_ended.is_(True)))).all())
    rows = (await session.scalars(select(Employee).where(Employee.joining_date <= on))).all()
    return [e for e in rows if e.status_code not in ended]


def _months(start: date, end: date):
    d = date(start.year, start.month, 1)
    while d <= end:
        yield d
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)


async def run_accrual(session: AsyncSession, today: date | None = None) -> dict:
    today = today or company_today()
    start_month = await leave_year_start_month(session)
    year = leave_year_of(today, start_month)
    year_start, _ = leave_year_bounds(year, start_month)
    employees = await _employed(session, today)
    types = {t.id: t for t in (await session.scalars(select(LeaveType).where(LeaveType.balance_tracked.is_(True)))).all()}
    policies = [p for p in (await session.scalars(select(LeavePolicy).where(LeavePolicy.accrual_method != "none"))).all() if p.leave_type_id in types]
    credited = 0
    for p in policies:
        rows = []
        if p.accrual_method == "annual":
            # The policy is in force at some point of this leave year, up to today.
            on = max(year_start, p.effective_from)
            if on > today or (p.effective_to and p.effective_to < year_start):
                continue
            for e in employees:
                if policy_applies(p, e, max(on, e.joining_date)) and e.joining_date <= today:
                    rows.append(dict(employee_id=e.id, leave_type_id=p.leave_type_id, leave_year=year, entry_type="allocation", days=p.accrual_days, leave_policy_id=p.id,
                                     period_key=f"annual:{p.id}:{year}", reason=f"Annual credit {year} (policy from {p.effective_from.isoformat()})"))
        else:
            for month in _months(max(year_start, p.effective_from), today):
                month_end = _months_end(month)
                if p.effective_to and p.effective_to < month:
                    break
                for e in employees:
                    on = max(month, e.joining_date, p.effective_from)
                    if e.joining_date <= month_end and policy_applies(p, e, on):
                        rows.append(dict(employee_id=e.id, leave_type_id=p.leave_type_id, leave_year=leave_year_of(month, start_month), entry_type="accrual", days=p.accrual_days,
                                         leave_policy_id=p.id, period_key=f"monthly:{p.id}:{month.strftime('%Y-%m')}", reason=f"Monthly credit {month.strftime('%Y-%m')}"))
        n = await _credit(session, rows)
        if n:
            AuditService(session).record(module="Leave", action="leave_balance.accrued", summary=f"{n} credits of {p.accrual_days:g} days {types[p.leave_type_id].code} ({p.accrual_method})",
                                         entity_type="leave_policy", entity_id=p.id, entity_label=types[p.leave_type_id].name)
        credited += n
    carried = await run_carry_forward(session, year, start_month, types)
    await session.commit()
    return {"credited": credited, "carriedForward": carried}


def _months_end(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1) - timedelta(days=1)


async def run_carry_forward(session: AsyncSession, year: int, start_month: int, types: dict) -> int:
    old = year - 1
    _, old_end = leave_year_bounds(old, start_month)
    policies = [p for p in (await session.scalars(select(LeavePolicy).where(LeavePolicy.carry_forward_allowed.is_(True)))).all() if p.leave_type_id in types]
    if not policies:
        return 0
    sums_rows = (await session.execute(
        select(LeaveLedgerEntry.employee_id, LeaveLedgerEntry.leave_type_id, func.sum(LeaveLedgerEntry.days), func.sum(case((LeaveLedgerEntry.entry_type == "lapse", 1), else_=0)))
        .where(LeaveLedgerEntry.leave_year == old).group_by(LeaveLedgerEntry.employee_id, LeaveLedgerEntry.leave_type_id)
    )).all()
    count = 0
    for emp_id, type_id, total, lapses in sums_rows:
        if lapses:
            continue  # this year-end was already processed
        employee = await session.get(Employee, emp_id)
        policy = next((p for p in policies if p.leave_type_id == type_id and policy_applies(p, employee, old_end)), None)
        if policy is None:
            continue
        remaining = max(float(total or 0), 0.0)
        carry = remaining if policy.carry_forward_max_days is None else min(remaining, float(policy.carry_forward_max_days))
        rows = []
        if carry > 0:
            rows.append(dict(employee_id=emp_id, leave_type_id=type_id, leave_year=year, entry_type="carry_forward", days=carry, leave_policy_id=policy.id,
                             period_key=f"carry:{type_id}:{year}", reason=f"Carried forward from {old}"))
        if remaining > 0:
            rows.append(dict(employee_id=emp_id, leave_type_id=type_id, leave_year=old, entry_type="lapse", days=-float(total), leave_policy_id=policy.id,
                             period_key=f"lapse:{type_id}:{old}", reason=f"Year end {old}: {carry:g} days carried forward to {year}, {max(float(total) - carry, 0):g} lapsed"))
        if await _credit(session, rows):
            count += 1
            AuditService(session).record(module="Leave", action="leave_balance.carried_forward", summary=f"{employee.employee_code} {types[type_id].code}: {carry:g} days carried from {old} to {year}",
                                         entity_type="employee", entity_id=emp_id, entity_label=employee.full_name)
    return count
