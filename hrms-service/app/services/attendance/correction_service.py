"""Attendance corrections (contract E1 + owner decision 1: configurable approval workflow).

Submit: the employee (own, hr.self:submit-requests) or HR on their behalf (hr.attendance-corrections:submit,
employee in scope). The workflow in force for `attendance_correction` on the submission date is
copied onto the request. With no workflow published, contract E applies: the reporting manager
(with hr.approvals:act) decides for direct reports.

Decide: HR with hr.attendance-corrections:approve (employee in scope) may decide at any step
(oversight); otherwise only the current step's approver (or its fallback once escalated).
Nobody decides their own request. Approving the last step replaces that day's punches.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import false, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ForbiddenError, InvalidTransitionError, NotFoundError, PeriodLockedError, StaleVersionError, ValidationFailedError
from app.core.permissions import P, has_permission
from app.models.attendance_model import AttendanceCorrection, AttendanceCorrectionEvent
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import text_match
from app.schemas.attendance_schema import CorrectionIn, CorrectionOut, DecisionIn
from app.schemas.common import Page, PageParams
from app.services.attendance.attendance_data import AttendanceData, company_tz, is_locked
from app.services.attendance.correction_view import correction_out
from app.services.attendance.jobs import enqueue_recalculation
from app.services.attendance.policy_service import policy_values_on
from app.services.attendance.workflow_service import WorkflowEngine
from app.services.audit_service import AuditService
from app.services.employee_scope_service import EmployeeScopeService, caller_employee_id
from app.services.employee_support import Caller, company_today, parse_date
from app.utils.ids import body_id
from app.utils.validation import FieldErrors

SORTS = {"submittedAt": AttendanceCorrection.created_at, "date": AttendanceCorrection.date, "status": AttendanceCorrection.status, "employee": func.lower(Employee.full_name)}


def _parse_instant(raw: str | None) -> datetime | None:
    """ISO date-time with an offset (or Z). Raises ValueError otherwise."""
    if raw is None or raw == "":
        return None
    value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("no offset")
    return value


class CorrectionService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.audit = AuditService(session)
        self.engine = WorkflowEngine(session)
        self.scope_clause = EmployeeScopeService.clause(caller.scope)

    def has(self, code: str) -> bool:
        return has_permission(self.caller.principal.permissions, code)

    async def _departments(self) -> dict:
        return {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}

    async def _in_scope(self, employee_id: uuid.UUID) -> bool:
        return await self.session.scalar(select(Employee.id).where(Employee.id == employee_id, self.scope_clause)) is not None

    async def _visible(self, correction_id: uuid.UUID) -> tuple[AttendanceCorrection, Employee]:
        c = await self.session.get(AttendanceCorrection, correction_id)
        if c is None:
            raise NotFoundError()
        employee = await self.session.get(Employee, c.employee_id)
        me = caller_employee_id(self.caller.principal)
        visible = (self.has(P.ATTENDANCE_CORRECTIONS_VIEW) and await self._in_scope(c.employee_id)) or me == c.employee_id
        if not visible and c.status == "pending" and c.current_step is not None and c.steps:
            visible = await self.engine.is_step_approver(c.steps[c.current_step], self.caller.principal, employee, c.escalated)
        if not visible and me and employee.reporting_manager_id == me and self.has(P.APPROVALS_ACT):
            visible = True
        if not visible:
            raise NotFoundError()
        return c, employee

    async def _out(self, c: AttendanceCorrection, employee: Employee) -> CorrectionOut:
        return await correction_out(self.session, c, employee, await self._departments())

    def _event(self, c: AttendanceCorrection, action: str, comment: str | None = None, step: str | None = None) -> None:
        self.session.add(AttendanceCorrectionEvent(correction_id=c.id, action=action, comment=comment, step_name=step))

    # ---- List and detail ------------------------------------------------------------------------------

    async def list(self, params: PageParams, *, status: str | None, department_id: str | None) -> Page:
        if not self.has(P.ATTENDANCE_CORRECTIONS_VIEW):
            raise ForbiddenError()
        sort = params.sort or "submittedAt:desc"
        name, _, direction = sort.partition(":")
        if name not in SORTS or (direction or "asc") not in ("asc", "desc"):
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": f"Use one of: {', '.join(SORTS)} with :asc or :desc."}])
        column = SORTS[name]
        stmt = select(AttendanceCorrection, Employee).join(Employee, Employee.id == AttendanceCorrection.employee_id).where(self.scope_clause)
        if status:
            stmt = stmt.where(AttendanceCorrection.status == status)
        if department_id:
            stmt = stmt.where(Employee.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        if params.q:
            stmt = stmt.where(text_match(params.q))
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc(), AttendanceCorrection.id).limit(params.page_size).offset((params.page - 1) * params.page_size)
        rows = (await self.session.execute(stmt)).all()
        departments = await self._departments()
        items = [await correction_out(self.session, c, e, departments) for c, e in rows]
        return Page.build(PageResult(rows, params.page, params.page_size, total), items)

    async def get(self, correction_id: uuid.UUID) -> CorrectionOut:
        c, employee = await self._visible(correction_id)
        return await self._out(c, employee)

    # ---- Submit -------------------------------------------------------------------------------------------

    async def submit(self, data: CorrectionIn) -> CorrectionOut:
        employee_id = body_id(data.employee_id)
        employee = await self.session.get(Employee, employee_id) if employee_id else None
        me = caller_employee_id(self.caller.principal)
        own = employee is not None and me == employee.id and self.has(P.SELF_SUBMIT_REQUESTS)
        on_behalf = employee is not None and self.has(P.ATTENDANCE_CORRECTIONS_SUBMIT) and await self._in_scope(employee.id)
        if employee is None or not (own or on_behalf):
            if employee is None or not (self.has(P.ATTENDANCE_CORRECTIONS_SUBMIT) or self.has(P.SELF_SUBMIT_REQUESTS)):
                raise ForbiddenError()
            raise ValidationFailedError(details=[{"field": "employeeId", "message": "You can request corrections only for yourself or for employees within your organizational scope."}])

        err = FieldErrors()
        today = company_today()
        tz = company_tz()
        day = None
        try:
            day = parse_date(data.date)
        except ValueError:
            pass
        if day is None:
            err.add("date", "Enter the date as YYYY-MM-DD.")
        elif day > today:
            err.add("date", "A correction cannot be requested for a future date.")
        elif day < employee.joining_date:
            err.add("date", "The date is before the employee's joining date.")
        requested_in = requested_out = None
        try:
            requested_in = _parse_instant(data.requested_in)
        except ValueError:
            err.add("requestedIn", "Enter the in-time as a date and time with its time zone.")
        try:
            requested_out = _parse_instant(data.requested_out)
        except ValueError:
            err.add("requestedOut", "Enter the out-time as a date and time with its time zone.")
        if not err.has("requestedIn") and not err.has("requestedOut") and not requested_in and not requested_out:
            err.add("requestedIn", "Enter the corrected in-time, out-time or both.")
        if requested_in and requested_out and requested_out <= requested_in:
            err.add("requestedOut", "Out-time must be after in-time.")
        if day and requested_in and requested_in.astimezone(tz).date() != day:
            err.add("requestedIn", "The in-time must be on the corrected date.")
        if day and requested_out and requested_out.astimezone(tz).date() not in (day, date.fromordinal(day.toordinal() + 1)):
            err.add("requestedOut", "The out-time must be on the corrected date or the next day.")
        reason = data.reason.strip()
        if len(reason) < 10:
            err.add("reason", "Explain the correction in at least 10 characters.")
        elif len(reason) > 500:
            err.add("reason", "Keep the reason under 500 characters.")
        if day and not err.has("date"):
            window = (await policy_values_on(self.session, today)).get("attendance", "correctionWindowDays")
            if window and (today - day).days > window:
                err.add("date", f"Corrections can be requested up to {window} days back.")
            pending = await self.session.scalar(select(AttendanceCorrection.id).where(AttendanceCorrection.employee_id == employee.id, AttendanceCorrection.date == day, AttendanceCorrection.status == "pending"))
            if pending:
                err.add("date", "A correction for this date is already waiting for a decision.")
        err.raise_if_any()
        if await is_locked(self.session, day, day):
            raise PeriodLockedError("This date is in a finalized payroll period and can no longer be corrected.")

        current = (await AttendanceData(self.session).compute([employee], day, day))[employee.id].days.get(day)
        workflow = await self.engine.in_force("attendance_correction", today)
        steps = self.engine.applicable_steps(workflow.published["steps"], {"daysSinceDate": (today - day).days}) if workflow else []
        correction = AttendanceCorrection(
            employee_id=employee.id, date=day, original_in=current.first_in if current else None, original_out=current.last_out if current else None,
            requested_in=requested_in, requested_out=requested_out, reason=reason, status="pending",
            workflow_id=workflow.id if workflow else None, workflow_version=workflow.published["version"] if workflow else None, steps=steps,
            current_step=await self.engine.first_step(steps, employee) if steps else None, step_started_at=datetime.now(UTC),
        )
        self.session.add(correction)
        try:
            await self.session.flush()
        except IntegrityError:
            raise ValidationFailedError(details=[{"field": "date", "message": "A correction for this date is already waiting for a decision."}]) from None
        self._event(correction, "submitted", reason)
        self.audit.record(module="Attendance", action="attendance_correction.submitted", summary=f"Correction for {employee.employee_code} on {day.isoformat()} submitted",
                          entity_type="attendance_correction", entity_id=correction.id, entity_label=employee.full_name)
        await self.session.commit()
        return await self._out(correction, employee)

    # ---- Decide -------------------------------------------------------------------------------------------

    async def decide(self, correction_id: uuid.UUID, data: DecisionIn) -> CorrectionOut:
        c, employee = await self._visible(correction_id)
        if caller_employee_id(self.caller.principal) == employee.id:
            raise ForbiddenError("You cannot decide your own request.")
        if c.status != "pending":
            raise InvalidTransitionError("This request has already been decided.")
        oversight = self.has(P.ATTENDANCE_CORRECTIONS_APPROVE) and await self._in_scope(employee.id)
        step = c.steps[c.current_step] if c.status == "pending" and c.steps and c.current_step is not None else None
        if step is not None:
            step_approver = await self.engine.is_step_approver(step, self.caller.principal, employee, c.escalated)
        else:
            me = caller_employee_id(self.caller.principal)  # no workflow: contract E rule
            step_approver = not c.steps and me is not None and employee.reporting_manager_id == me and self.has(P.APPROVALS_ACT)
        if not (oversight or step_approver):
            raise ForbiddenError("You are not an approver for this request.")
        if data.version != c.version:
            raise StaleVersionError()
        comment = (data.comment or "").strip() or None
        if data.decision == "reject" and not comment:
            raise ValidationFailedError(details=[{"field": "comment", "message": "Enter a comment explaining the rejection."}])
        if step is None:
            step_name = None
        elif oversight and not step_approver:
            step_name = f"{step['name']} (HR oversight)"
        else:
            step_name = step["name"]
        now = datetime.now(UTC)
        if data.decision == "reject":
            c.status = "rejected"
            self._event(c, "rejected", comment, step_name)
        else:
            next_step = None
            if step is not None and step_approver and not oversight:
                next_step = await self.engine.first_step(c.steps, employee, c.current_step + 1)
            if next_step is not None:
                self._event(c, "approved", comment, step_name)
                c.current_step, c.step_started_at, c.escalated = next_step, now, False
            else:
                if await is_locked(self.session, c.date, c.date):
                    raise PeriodLockedError("This date is in a finalized payroll period and can no longer be corrected.")
                c.status = "approved"
                self._event(c, "approved", comment, step_name)
        if c.status != "pending":
            c.reviewed_by_name, c.reviewed_at, c.review_comment, c.current_step = self.caller.principal.name, now, comment, None
        await self.session.flush()
        self.audit.record(
            module="Attendance", action=f"attendance_correction.{'rejected' if data.decision == 'reject' else ('approved' if c.status == 'approved' else 'step_approved')}",
            summary=f"Correction for {employee.employee_code} on {c.date.isoformat()}: {data.decision}" + (" (HR oversight)" if oversight and not step_approver else ""),
            entity_type="attendance_correction", entity_id=c.id, entity_label=employee.full_name,
        )
        if c.status == "approved" and c.date < company_today():
            await enqueue_recalculation(self.session, [employee.id], c.date, c.date, reason=f"correction {c.id}")
        await self.session.commit()
        return await self._out(c, employee)


async def escalate_overdue(session: AsyncSession) -> int:
    """Worker task: marks overdue workflow steps as escalated so their fallback approvers may act."""
    engine = WorkflowEngine(session)
    now = datetime.now(UTC)
    count = 0
    rows = (await session.scalars(select(AttendanceCorrection).where(AttendanceCorrection.status == "pending", AttendanceCorrection.escalated.is_(False), AttendanceCorrection.current_step.is_not(None)))).all()
    for c in rows:
        step = c.steps[c.current_step]
        if engine.overdue(step, c.step_started_at, now):
            c.escalated = True
            fb = step["fallback"]
            session.add(AttendanceCorrectionEvent(correction_id=c.id, action="escalated", step_name=step["name"], comment=f"to {fb['type']} {fb.get('roleId') or fb.get('userId')} after {step['escalateAfterHours']} h"))
            AuditService(session).record(module="Attendance", action="attendance_correction.escalated", summary=f"Correction {c.id} escalated at step '{step['name']}'", entity_type="attendance_correction", entity_id=c.id)
            count += 1
    await session.commit()
    return count
