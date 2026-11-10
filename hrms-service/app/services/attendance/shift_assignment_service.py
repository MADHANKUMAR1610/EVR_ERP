"""Shift assignments (POST /hr/shifts/{id}/assignments, contract E1 + owner decision 2).

Dated history: an assignment applies from its effective date until the employee's next assignment.
Back-dating (effective date before today) is OFF unless HR switches on `allowBackdatedAssignments`
(policy area `shifts`); then it also needs hr.shifts:assign-backdated and a reason, may not reach
further back than `maxBackdatedDays` (when set), and may not touch a locked (finalized payroll) period.
Every assignment writes an append-only change record with the old and new shift, effective date,
reason, user, time and the attendance days affected; affected stored days are recalculated.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError, PeriodLockedError, ValidationFailedError
from app.core.permissions import P, has_permission
from app.models.attendance_model import ShiftAssignment, ShiftAssignmentChange
from app.models.employee_model import Employee
from app.models.shift_model import Shift
from app.schemas.attendance_schema import ShiftAssignmentIn, ShiftAssignmentOut
from app.services.attendance.attendance_data import is_locked
from app.services.attendance.jobs import enqueue_recalculation
from app.services.attendance.policy_service import policy_values_on
from app.services.audit_service import AuditService
from app.services.employee_scope_service import EmployeeScopeService
from app.services.employee_support import Caller, company_today, parse_date
from app.utils.ids import body_id
from app.utils.validation import FieldErrors


async def record_assignment(session: AsyncSession, employee: Employee, shift_id: uuid.UUID, effective: date, *, reason: str | None, backdated: bool) -> ShiftAssignmentChange:
    """Adds or replaces the assignment at `effective` and writes the change record. Shared with the employee form."""
    rows = list((await session.scalars(select(ShiftAssignment).where(ShiftAssignment.employee_id == employee.id).order_by(ShiftAssignment.effective_from))).all())
    old = next((r.shift_id for r in reversed(rows) if r.effective_from <= effective), None)
    same_day = next((r for r in rows if r.effective_from == effective), None)
    if same_day:
        same_day.shift_id = shift_id
    else:
        session.add(ShiftAssignment(employee_id=employee.id, shift_id=shift_id, effective_from=effective))
    today = company_today()
    next_change = next((r.effective_from for r in rows if r.effective_from > effective), None)
    affected_to = min(next_change - timedelta(days=1) if next_change else today - timedelta(days=1), today - timedelta(days=1))
    affected_from = max(effective, employee.joining_date)
    days = (affected_to - affected_from).days + 1 if affected_to >= affected_from else 0
    change = ShiftAssignmentChange(
        employee_id=employee.id, old_shift_id=old, new_shift_id=shift_id, effective_from=effective, backdated=backdated, reason=reason,
        affected_from=affected_from if days else None, affected_to=affected_to if days else None, affected_days=days,
    )
    session.add(change)
    if effective <= today and (next_change is None or next_change > today):
        employee.shift_id = shift_id  # the shift in force today
    return change


class ShiftAssignmentService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.scope_clause = EmployeeScopeService.clause(caller.scope)

    async def assign(self, shift_id: uuid.UUID, data: ShiftAssignmentIn) -> ShiftAssignmentOut:
        shift = await self.session.get(Shift, shift_id)
        if shift is None:
            raise NotFoundError()
        err = FieldErrors()
        if not shift.active:
            err.add("shiftId", "This shift is no longer active.")
        today = company_today()
        effective = None
        try:
            effective = parse_date(data.effective_from)
        except ValueError:
            pass
        if effective is None:
            err.add("effectiveFrom", "Enter the date the assignment starts.")
        ids = [body_id(x) for x in data.employee_ids]
        unique = list(dict.fromkeys(i for i in ids if i))
        employees = list((await self.session.scalars(select(Employee).where(Employee.id.in_(unique), self.scope_clause))).all()) if unique else []
        if None in ids or len(employees) != len(unique):
            err.add("employeeIds", "Select employees within your organizational scope.")
        backdated = effective is not None and effective < today
        reason = (data.reason or "").strip() or None
        if backdated:
            shifts_policy = await policy_values_on(self.session, today)
            if not shifts_policy.on("shifts", "allowBackdatedAssignments"):
                err.add("effectiveFrom", "Back-dated shift assignments are not allowed. The assignment must start today or later.")
            elif not has_permission(self.caller.principal.permissions, P.SHIFTS_ASSIGN_BACKDATED):
                raise ForbiddenError("You do not have permission to make back-dated shift assignments.")
            else:
                limit = shifts_policy.get("shifts", "maxBackdatedDays")
                if limit and (today - effective).days > limit:
                    err.add("effectiveFrom", f"Assignments can start at most {limit} days back.")
                if not reason:
                    err.add("reason", "Enter the reason for this back-dated assignment.")
        for e in employees:
            if effective and effective < e.joining_date:
                err.add("effectiveFrom", f"The date is before {e.employee_code}'s joining date ({e.joining_date.isoformat()}).")
        err.raise_if_any()
        if backdated and await is_locked(self.session, effective, today - timedelta(days=1)):
            raise PeriodLockedError("The back-dated range includes a finalized payroll period, which can no longer change.")

        audit = AuditService(self.session)
        total_affected = 0
        for e in employees:
            change = await record_assignment(self.session, e, shift.id, effective, reason=reason, backdated=backdated)
            total_affected += change.affected_days
            await self.session.flush()
            audit.record(
                module="Attendance", action="shift.assigned_backdated" if backdated else "shift.assigned",
                summary=f"{e.employee_code} assigned to shift {shift.code} from {effective.isoformat()}" + (f" (back-dated; {change.affected_days} attendance day(s) affected)" if backdated else ""),
                entity_type="employee", entity_id=e.id, entity_label=e.full_name,
                changes=[{"field": "shift", "before": str(change.old_shift_id) if change.old_shift_id else None, "after": str(shift.id)}, {"field": "effectiveFrom", "before": None, "after": effective.isoformat()}]
                + ([{"field": "reason", "before": None, "after": reason}] if reason else []),
            )
            if change.affected_days:
                await enqueue_recalculation(self.session, [e.id], change.affected_from, change.affected_to, reason=f"shift assignment from {effective.isoformat()}")
        await self.session.commit()
        return ShiftAssignmentOut(assigned=len(employees), effective_from=effective.isoformat(), affected_attendance_days=total_affected, backdated=backdated)
