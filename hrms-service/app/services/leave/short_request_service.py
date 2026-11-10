"""Part B: permission (short absence) and overtime requests (contract E2 + E).

Submit: the employee (hr.self:submit-requests) or someone on their behalf (hr.leave:apply-on-behalf,
employee in scope), as the frontend's `canApplyOnBehalf`. No limit on permission minutes or
overtime is applied (L30): only the frontend's own form rules.

Decide (no self-decisions, 403; rejection needs a comment; the row is locked and the first valid
decision wins, 409 otherwise):
- permission: HR with hr.permission-requests:approve in scope, or the reporting manager with
  hr.approvals:act (contract E);
- overtime: the published G5 workflow for process `overtime` (Module 5 engine: steps copied onto
  the request, optional steps without an approver skipped, escalation to the step's fallback),
  with HR oversight by hr.overtime:approve in scope. Without a published workflow, contract E.
Overtime is a time record only; `recordedMinutes` is attendance's time beyond the shift.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ForbiddenError, InvalidTransitionError, NotFoundError, StaleVersionError, ValidationFailedError
from app.core.permissions import P
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.models.leave_model import OvertimeRequest, PermissionRequest, RequestEvent
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import text_match
from app.schemas.attendance_schema import DecisionIn
from app.schemas.common import Page, PageParams
from app.schemas.leave_schema import OvertimeIn, OvertimeRequestOut, PermissionIn, PermissionRequestOut
from app.services.attendance.attendance_data import AttendanceData
from app.services.attendance.attendance_read_service import employee_ref
from app.services.attendance.workflow_service import WorkflowEngine
from app.services.audit_service import AuditService
from app.services.employee_scope_service import EmployeeScopeService, caller_employee_id
from app.services.employee_support import Caller, company_today, parse_date
from app.services.leave.request_view import history_out
from app.utils.ids import body_id
from app.utils.validation import FieldErrors

TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SORTS = {"submittedAt": "created_at", "date": "date", "status": "status", "minutes": "minutes"}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class _ShortRequests:
    kind: str
    model: type
    view_permission: str
    approve_permission: str
    label: str

    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.audit = AuditService(session)
        self.scope_clause = EmployeeScopeService.clause(caller.scope)
        self.me = caller_employee_id(caller.principal)

    def has(self, code: str) -> bool:
        return self.caller.has(code)

    async def _departments(self) -> dict:
        return {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}

    async def _in_scope(self, employee_id: uuid.UUID) -> bool:
        return await self.session.scalar(select(Employee.id).where(Employee.id == employee_id, self.scope_clause)) is not None

    def _manager_clause(self):
        return Employee.reporting_manager_id == self.me if self.me and self.has(P.APPROVALS_ACT) else false()

    def _extra_visible_clause(self):
        return false()

    def _visible_clause(self):
        conds = [self._manager_clause(), self._extra_visible_clause()]
        if self.has(self.view_permission) or self.has(self.approve_permission):
            conds.append(self.scope_clause)
        if self.me:
            conds.append(self.model.employee_id == self.me)
        return or_(*conds)

    async def _extra_visible(self, r, employee: Employee) -> bool:
        return False

    async def _load(self, request_id: uuid.UUID, *, lock: bool = False):
        r = await self.session.get(self.model, request_id, with_for_update=lock or None, populate_existing=lock)
        if r is None:
            raise NotFoundError()
        employee = await self.session.get(Employee, r.employee_id)
        visible = (
            self.me == r.employee_id
            or ((self.has(self.view_permission) or self.has(self.approve_permission)) and await self._in_scope(r.employee_id))
            or (self.me is not None and employee.reporting_manager_id == self.me and self.has(P.APPROVALS_ACT))
            or await self._extra_visible(r, employee)
        )
        if not visible:
            raise NotFoundError()
        return r, employee

    def _event(self, r, action: str, comment: str | None) -> None:
        self.session.add(RequestEvent(request_kind=self.kind, request_id=r.id, action=action, comment=comment))

    async def _applicant(self, raw_id: str | None) -> Employee:
        employee_id = body_id(raw_id) if raw_id else self.me
        employee = await self.session.get(Employee, employee_id) if employee_id else None
        own = employee is not None and self.me == employee.id and self.has(P.SELF_SUBMIT_REQUESTS)
        on_behalf = employee is not None and self.has(P.LEAVE_APPLY_ON_BEHALF) and await self._in_scope(employee.id)
        if own or on_behalf:
            return employee
        if not (self.has(P.LEAVE_APPLY_ON_BEHALF) or self.has(P.SELF_SUBMIT_REQUESTS)):
            raise ForbiddenError()
        message = "Choose the employee." if raw_id is None and self.me is None else "You can submit requests only for yourself or for employees within your organizational scope."
        raise ValidationFailedError(details=[{"field": "employeeId", "message": message}])

    @staticmethod
    def _reason(raw: str, err: FieldErrors) -> str:
        reason = raw.strip()
        if len(reason) < 3:
            err.add("reason", "Enter a reason.")
        elif len(reason) > 300:
            err.add("reason", "Keep the reason under 300 characters.")
        return reason

    async def list(self, params: PageParams, *, scope: str | None, status: str | None, department_id: str | None) -> Page:
        if scope not in (None, "all", "mine"):
            raise ValidationFailedError(details=[{"field": "scope", "message": "Use all or mine."}])
        if scope != "mine" and not (self.has(self.view_permission) or self.has(self.approve_permission) or self.has(P.APPROVALS_ACT)):
            raise ForbiddenError()
        sort = params.sort or "submittedAt:desc"
        name, _, direction = sort.partition(":")
        if name not in SORTS and name != "employee" or (direction or "asc") not in ("asc", "desc"):
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": "Use one of: submittedAt, date, status, minutes, employee with :asc or :desc."}])
        column = func.lower(Employee.full_name) if name == "employee" else getattr(self.model, SORTS[name])
        stmt = select(self.model, Employee).join(Employee, Employee.id == self.model.employee_id).where(self._visible_clause())
        if scope == "mine":
            stmt = stmt.where(self.model.employee_id == self.me) if self.me else stmt.where(false())
        if status:
            stmt = stmt.where(self.model.status == status)
        if department_id:
            stmt = stmt.where(Employee.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        if params.q:
            stmt = stmt.where(text_match(params.q))
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc(), self.model.id).limit(params.page_size).offset((params.page - 1) * params.page_size)
        rows = (await self.session.execute(stmt)).all()
        departments = await self._departments()
        return Page.build(PageResult(rows, params.page, params.page_size, total), [await self._out(r, e, departments) for r, e in rows])

    async def get(self, request_id: uuid.UUID):
        r, employee = await self._load(request_id)
        return await self._out(r, employee, await self._departments())

    async def _authority(self, r, employee: Employee) -> tuple[bool, bool, dict | None]:
        """(HR oversight, approver by routing, current workflow step)."""
        oversight = self.has(self.approve_permission) and await self._in_scope(employee.id)
        manager = self.me is not None and employee.reporting_manager_id == self.me and self.has(P.APPROVALS_ACT)
        return oversight, manager, None

    async def decide(self, request_id: uuid.UUID, data: DecisionIn):
        r, employee = await self._load(request_id, lock=True)
        if self.me == employee.id:
            raise ForbiddenError("You cannot decide your own request.")
        if r.status != "pending":
            raise InvalidTransitionError("This request has already been decided.")
        oversight, approver, step = await self._authority(r, employee)
        if not (oversight or approver):
            raise ForbiddenError("You are not an approver for this request.")
        if data.version != r.version:
            raise StaleVersionError()
        comment = (data.comment or "").strip() or None
        if data.decision == "reject" and not comment:
            raise ValidationFailedError(details=[{"field": "comment", "message": "Enter a comment explaining the rejection."}])
        final = await self._advance(r, employee, data.decision, oversight, approver, step, comment)
        if final:
            r.status = "approved" if data.decision == "approve" else "rejected"
            r.reviewed_by_name, r.reviewed_at, r.review_comment = self.caller.principal.name, datetime.now(UTC), comment
        await self.session.flush()
        outcome = r.status if final else "step_approved"
        self.audit.record(module="Leave", action=f"{self.kind}_request.{outcome}", summary=f"{self.label} of {employee.employee_code} on {r.date.isoformat()}: {data.decision}" + (" (HR oversight)" if oversight and not approver else ""),
                          entity_type=f"{self.kind}_request", entity_id=r.id, entity_label=employee.full_name)
        await self.session.commit()
        return await self._out(r, employee, await self._departments())

    async def _advance(self, r, employee, decision, oversight, approver, step, comment) -> bool:
        self._event(r, "approved" if decision == "approve" else "rejected", comment)
        return True


class PermissionRequestService(_ShortRequests):
    kind, model, label = "permission", PermissionRequest, "Permission request"
    view_permission, approve_permission = P.PERMISSION_REQUESTS_VIEW, P.PERMISSION_REQUESTS_APPROVE

    async def _out(self, r: PermissionRequest, employee: Employee, departments: dict) -> PermissionRequestOut:
        return PermissionRequestOut(
            id=str(r.id), employee=employee_ref(employee, departments), date=r.date.isoformat(), **{"from": r.from_time}, to=r.to_time, minutes=r.minutes, reason=r.reason, status=r.status,
            submitted_at=r.created_at, submitted_by=r.created_by_name, reviewed_by=r.reviewed_by_name, review_comment=r.review_comment, history=await history_out(self.session, "permission", r.id), version=r.version,
        )

    async def submit(self, data: PermissionIn) -> PermissionRequestOut:
        employee = await self._applicant(data.employee_id)
        err = FieldErrors()
        day = None
        try:
            day = parse_date(data.date)
        except ValueError:
            pass
        if day is None:
            err.add("date", "Enter the date.")
        elif day < employee.joining_date:
            err.add("date", "The date is before the employee's joining date.")
        if not TIME.match(data.from_ or ""):
            err.add("from", "Enter the start time.")
        if not TIME.match(data.to or ""):
            err.add("to", "Enter the end time.")
        if not err.has("from") and not err.has("to") and data.to <= data.from_:
            err.add("to", "The end time must be after the start time.")
        reason = self._reason(data.reason, err)
        err.raise_if_any()
        await self.session.execute(select(Employee.id).where(Employee.id == employee.id).with_for_update())
        clash = await self.session.scalar(select(PermissionRequest.id).where(PermissionRequest.employee_id == employee.id, PermissionRequest.date == day, PermissionRequest.status.in_(("pending", "approved")),
                                                                            PermissionRequest.from_time < data.to, PermissionRequest.to_time > data.from_))
        if clash:
            raise ValidationFailedError(details=[{"field": "from", "message": "This overlaps with another permission request on the same day."}])
        r = PermissionRequest(employee_id=employee.id, date=day, from_time=data.from_, to_time=data.to, minutes=_minutes(data.to) - _minutes(data.from_), reason=reason, status="pending")
        self.session.add(r)
        await self.session.flush()
        self._event(r, "submitted", reason)
        self.audit.record(module="Leave", action="permission_request.submitted", summary=f"Permission request of {employee.employee_code} on {day.isoformat()} {data.from_}-{data.to} submitted",
                          entity_type="permission_request", entity_id=r.id, entity_label=employee.full_name)
        await self.session.commit()
        return await self._out(r, employee, await self._departments())


class OvertimeRequestService(_ShortRequests):
    kind, model, label = "overtime", OvertimeRequest, "Overtime request"
    view_permission, approve_permission = P.OVERTIME_VIEW, P.OVERTIME_APPROVE

    def __init__(self, session: AsyncSession, caller: Caller):
        super().__init__(session, caller)
        self.engine = WorkflowEngine(session)
        self._recorded: dict = {}

    async def _recorded_minutes(self, r: OvertimeRequest, employee: Employee) -> int | None:
        key = (employee.id, r.date)
        if key not in self._recorded:
            day = (await AttendanceData(self.session).compute([employee], r.date, r.date))[employee.id].days.get(r.date)
            self._recorded[key] = day.beyond_shift_minutes if day and day.worked_minutes is not None else None
        return self._recorded[key]

    async def _out(self, r: OvertimeRequest, employee: Employee, departments: dict) -> OvertimeRequestOut:
        return OvertimeRequestOut(
            id=str(r.id), employee=employee_ref(employee, departments), date=r.date.isoformat(), minutes=r.minutes, recorded_minutes=await self._recorded_minutes(r, employee), reason=r.reason,
            status=r.status, submitted_at=r.created_at, submitted_by=r.created_by_name, reviewed_by=r.reviewed_by_name, review_comment=r.review_comment,
            history=await history_out(self.session, "overtime", r.id), version=r.version,
        )

    def _extra_visible_clause(self):
        return false()  # step approvers by role/user see their requests through the approval inbox and detail

    async def _extra_visible(self, r: OvertimeRequest, employee: Employee) -> bool:
        if r.status == "pending" and r.current_step is not None and r.steps:
            return await self.engine.is_step_approver(r.steps[r.current_step], self.caller.principal, employee, r.escalated)
        return False

    async def submit(self, data: OvertimeIn) -> OvertimeRequestOut:
        employee = await self._applicant(data.employee_id)
        err = FieldErrors()
        today = company_today()
        day = None
        try:
            day = parse_date(data.date)
        except ValueError:
            pass
        if day is None:
            err.add("date", "Enter the date.")
        elif day > today:
            err.add("date", "Overtime can only be claimed for a date that has started.")
        elif day < employee.joining_date:
            err.add("date", "The date is before the employee's joining date.")
        if data.minutes <= 0:
            err.add("minutes", "Enter the overtime worked.")
        elif data.minutes > 960:
            err.add("minutes", "Overtime for one day cannot exceed 16 hours.")
        reason = self._reason(data.reason, err)
        err.raise_if_any()
        await self.session.execute(select(Employee.id).where(Employee.id == employee.id).with_for_update())
        if await self.session.scalar(select(OvertimeRequest.id).where(OvertimeRequest.employee_id == employee.id, OvertimeRequest.date == day, OvertimeRequest.status == "pending")):
            raise ValidationFailedError(details=[{"field": "date", "message": "An overtime request for this date is already waiting for a decision."}])
        workflow = await self.engine.in_force("overtime", today)
        steps = self.engine.applicable_steps(workflow.published["steps"], {}) if workflow else []
        r = OvertimeRequest(employee_id=employee.id, date=day, minutes=data.minutes, reason=reason, status="pending", workflow_id=workflow.id if workflow else None,
                            workflow_version=workflow.published["version"] if workflow else None, steps=steps,
                            current_step=await self.engine.first_step(steps, employee) if steps else None, step_started_at=datetime.now(UTC))
        self.session.add(r)
        await self.session.flush()
        self._event(r, "submitted", reason)
        self.audit.record(module="Leave", action="overtime_request.submitted", summary=f"Overtime of {data.minutes} min for {employee.employee_code} on {day.isoformat()} submitted",
                          entity_type="overtime_request", entity_id=r.id, entity_label=employee.full_name)
        await self.session.commit()
        return await self._out(r, employee, await self._departments())

    async def _authority(self, r: OvertimeRequest, employee: Employee):
        oversight = self.has(P.OVERTIME_APPROVE) and await self._in_scope(employee.id)
        step = r.steps[r.current_step] if r.steps and r.current_step is not None else None
        if step is not None:
            approver = await self.engine.is_step_approver(step, self.caller.principal, employee, r.escalated)
        else:  # no workflow: contract E rule
            approver = not r.steps and self.me is not None and employee.reporting_manager_id == self.me and self.has(P.APPROVALS_ACT)
        return oversight, approver, step

    async def _advance(self, r: OvertimeRequest, employee, decision, oversight, approver, step, comment) -> bool:
        label = None if step is None else (f"{step['name']} (HR oversight)" if oversight and not approver else step["name"])
        text = f"{label}: {comment}" if label and comment else (label or comment)
        if decision == "reject":
            self._event(r, "rejected", text)
            r.current_step = None
            return True
        if step is not None and approver and not oversight:
            nxt = await self.engine.first_step(r.steps, employee, r.current_step + 1)
            if nxt is not None:
                self._event(r, "approved", text)
                r.current_step, r.step_started_at, r.escalated = nxt, datetime.now(UTC), False
                return False
        self._event(r, "approved", text)
        r.current_step = None
        return True


async def escalate_overtime(session: AsyncSession) -> int:
    """Worker task (with `workflow.escalate`): overdue overtime steps go to their fallback approver."""
    engine = WorkflowEngine(session)
    now = datetime.now(UTC)
    count = 0
    rows = (await session.scalars(select(OvertimeRequest).where(OvertimeRequest.status == "pending", OvertimeRequest.escalated.is_(False), OvertimeRequest.current_step.is_not(None)))).all()
    for r in rows:
        step = r.steps[r.current_step]
        if engine.overdue(step, r.step_started_at, now):
            r.escalated = True
            fb = step["fallback"]
            session.add(RequestEvent(request_kind="overtime", request_id=r.id, action="commented", comment=f"Escalated at step '{step['name']}' to {fb['type']} {fb.get('roleId') or fb.get('userId')} after {step['escalateAfterHours']} h"))
            AuditService(session).record(module="Leave", action="overtime_request.escalated", summary=f"Overtime request {r.id} escalated at step '{step['name']}'", entity_type="overtime_request", entity_id=r.id)
            count += 1
    await session.commit()
    return count

