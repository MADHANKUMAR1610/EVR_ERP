"""Leave requests (contract E2 + H3 + the owner's Module 6 decisions).

Apply: the employee (own, hr.self:submit-requests) or someone on their behalf (hr.leave:apply-on-behalf,
employee in organizational scope). Days are charged per the leave calendar; the application is
refused (422) on an overlap, an invalid range, a half day not allowed, no working days, a notice
or back-dating window set by HR, or a balance shortfall (decision 3: blocked unless HR switches
on `allowNegativeBalance`). Routing is fixed at submission (decision 1).

Decide (decision 2): the original approver, the escalation recipient after escalation, and HR
with hr.leave:approve in scope may all decide. The decision locks the request row, then checks it
is still pending (409 INVALID_TRANSITION) and the version (409 STALE_VERSION): the first valid
decision wins. Usage ledger entries carry a per-request period key, so usage can never be
charged twice. Nobody decides their own request (403).

Every event is recorded in the request's append-only history and in the audit log (decision 5).
"""

from __future__ import annotations

import hashlib
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, false, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import malware_scan, storage
from app.core.config import get_settings
from app.core.crypto import EncryptionUnavailableError
from app.core.errors import BadRequestError, ForbiddenError, InvalidTransitionError, NotFoundError, PeriodLockedError, ServiceUnavailableError, StaleVersionError, ValidationFailedError
from app.core.file_inspection import detect, extension_of, safe_file_name
from app.core.permissions import P
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.models.leave_model import LeaveLedgerEntry, LeaveRequest, LeaveRequestAttachment, LeaveRoutingEvent, LeaveType, RequestEvent
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import text_match
from app.schemas.attendance_schema import DecisionIn
from app.schemas.common import Page, PageParams
from app.schemas.leave_schema import (
    CancellationIn,
    CommentIn,
    ExcludedDateOut,
    LeaveEstimateOut,
    LeaveRequestOut,
    LeaveSummaryOut,
    LowBalanceOut,
    OnLeaveTodayOut,
    OverlapOut,
    UpcomingLeaveOut,
)
from app.services.attendance.attendance_data import locked_dates
from app.services.attendance.attendance_read_service import employee_ref
from app.services.attendance.jobs import enqueue_recalculation
from app.services.attendance.policy_service import policy_values_on
from app.services.audit_service import AuditService
from app.services.employee_scope_service import EmployeeScopeService, caller_employee_id
from app.services.employee_support import Caller, company_today, parse_date
from app.services.leave import notifications
from app.services.leave.balance_service import available_days
from app.services.leave.calendar import LeaveCalendar, leave_year_of, leave_year_start_month
from app.services.leave.request_view import leave_request_out
from app.services.leave.setup_service import policy_for
from app.services.leave.workflow_service import select_workflow, snapshot
from app.utils.ids import body_id
from app.utils.validation import FieldErrors

MODULE = "Leave"
ALLOWED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")  # frontend ATTACHMENT_RULES (L14)
MAX_RANGE_DAYS = 366
SORTS = {"submittedAt": LeaveRequest.created_at, "from": LeaveRequest.from_date, "to": LeaveRequest.to_date, "days": LeaveRequest.days, "status": LeaveRequest.status,
         "employee": func.lower(Employee.full_name)}
APPROVER_LABEL = {"reporting_manager": "reporting manager", "department_head": "department head", "role": "role", "user": "user"}


@dataclass
class Upload:
    file_name: str | None
    content: bytes


@dataclass
class ApplicationInput:
    employee_id: str | None
    leave_type_id: str | None
    from_: str | None
    to: str | None
    portion: str | None
    reason: str | None = None
    attachments: list[Upload] = field(default_factory=list)


@dataclass
class Evaluation:
    days: float = 0.0
    charged: list[date] = field(default_factory=list)
    excluded: list[tuple[date, str]] = field(default_factory=list)
    days_by_year: dict[str, float] = field(default_factory=dict)
    available_before: float | None = None
    overlapping: list[tuple[LeaveRequest, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocks: list[tuple[str, str]] = field(default_factory=list)
    attachment_after_days: int | None = None


def _d(n: float) -> str:
    return f"{n:g}"


class LeaveRequestService:
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

    # ---- Who may see and decide ---------------------------------------------------------------------------

    def _approver_clause(self):
        """Requests where the caller is the assigned approver or (after escalation) the recipient."""
        if not self.has(P.APPROVALS_ACT):
            return false()
        p = self.caller.principal
        roles = list(p.roles)
        conds = [and_(LeaveRequest.approver_kind == "user", LeaveRequest.approver_ref == p.user_id),
                 and_(LeaveRequest.escalated_at.is_not(None), LeaveRequest.recipient_kind == "user", LeaveRequest.recipient_ref == p.user_id)]
        if self.me:
            conds.append(and_(LeaveRequest.approver_kind.in_(("reporting_manager", "department_head")), LeaveRequest.approver_employee_id == self.me))
        if roles:
            conds += [and_(LeaveRequest.approver_kind == "role", LeaveRequest.approver_ref.in_(roles)),
                      and_(LeaveRequest.escalated_at.is_not(None), LeaveRequest.recipient_kind == "role", LeaveRequest.recipient_ref.in_(roles))]
        return or_(*conds)

    def _visible_clause(self):
        conds = [self._approver_clause()]
        if self.has(P.LEAVE_VIEW) or self.has(P.LEAVE_APPROVE):
            conds.append(self.scope_clause)
        if self.me:
            conds.append(LeaveRequest.employee_id == self.me)
        return or_(*conds)

    def _awaiting_clause(self):
        conds = [self._approver_clause()]
        if self.has(P.LEAVE_APPROVE):
            conds.append(self.scope_clause)
        own = LeaveRequest.employee_id != self.me if self.me else true()
        return and_(LeaveRequest.status == "pending", own, or_(*conds))

    def _is_approver(self, r: LeaveRequest) -> bool:
        if not self.has(P.APPROVALS_ACT):
            return False
        p = self.caller.principal
        if r.approver_kind in ("reporting_manager", "department_head") and self.me and r.approver_employee_id == self.me:
            return True
        if (r.approver_kind == "role" and r.approver_ref in p.roles) or (r.approver_kind == "user" and r.approver_ref == p.user_id):
            return True
        if r.escalated_at is not None:  # stays set after the decision, so a late decision gets 409, not 404
            return (r.recipient_kind == "role" and r.recipient_ref in p.roles) or (r.recipient_kind == "user" and r.recipient_ref == p.user_id)
        return False

    async def _load(self, request_id: uuid.UUID, *, lock: bool = False) -> tuple[LeaveRequest, Employee]:
        r = await self.session.get(LeaveRequest, request_id, with_for_update=lock or None, populate_existing=lock)
        if r is None:
            raise NotFoundError()
        employee = await self.session.get(Employee, r.employee_id)
        visible = self.me == r.employee_id or self._is_approver(r) or ((self.has(P.LEAVE_VIEW) or self.has(P.LEAVE_APPROVE)) and await self._in_scope(r.employee_id))
        if not visible:
            raise NotFoundError()
        return r, employee

    async def _out(self, r: LeaveRequest, employee: Employee) -> LeaveRequestOut:
        return await leave_request_out(self.session, r, employee, await self._departments())

    def _event(self, r: LeaveRequest, action: str, comment: str | None = None) -> None:
        self.session.add(RequestEvent(request_kind="leave", request_id=r.id, action=action, comment=comment))

    def _routing(self, r: LeaveRequest, action: str, detail: str) -> None:
        self.session.add(LeaveRoutingEvent(leave_request_id=r.id, action=action, detail=detail[:500]))

    # ---- List, detail, attachments ------------------------------------------------------------------------

    async def list(self, params: PageParams, *, scope: str | None, status: str | None, leave_type_id: str | None, department_id: str | None, start: str | None, end: str | None,
                   escalated: bool | None, awaiting_me: bool | None) -> Page:
        if scope not in (None, "all", "mine"):
            raise ValidationFailedError(details=[{"field": "scope", "message": "Use all or mine."}])
        if scope != "mine" and not (self.has(P.LEAVE_VIEW) or self.has(P.LEAVE_APPROVE) or self.has(P.APPROVALS_VIEW) or self.has(P.APPROVALS_ACT)):
            raise ForbiddenError()
        sort = params.sort or "submittedAt:desc"
        name, _, direction = sort.partition(":")
        if name not in SORTS or (direction or "asc") not in ("asc", "desc"):
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": f"Use one of: {', '.join(SORTS)} with :asc or :desc."}])
        stmt = select(LeaveRequest, Employee).join(Employee, Employee.id == LeaveRequest.employee_id).where(self._visible_clause())
        if scope == "mine":
            stmt = stmt.where(LeaveRequest.employee_id == self.me) if self.me else stmt.where(false())
        err = FieldErrors()
        try:
            d_from, d_to = parse_date(start), parse_date(end)
        except ValueError:
            d_from = d_to = None
            err.add("from", "Enter dates as YYYY-MM-DD.")
        err.raise_if_any()
        if status:
            stmt = stmt.where(LeaveRequest.status == status)
        for raw, column in ((leave_type_id, LeaveRequest.leave_type_id), (department_id, Employee.department_id)):
            if raw:
                stmt = stmt.where(column == body_id(raw)) if body_id(raw) else stmt.where(false())
        if d_from:
            stmt = stmt.where(LeaveRequest.to_date >= d_from)
        if d_to:
            stmt = stmt.where(LeaveRequest.from_date <= d_to)
        if escalated:
            stmt = stmt.where(LeaveRequest.escalated_at.is_not(None))
        if awaiting_me:
            stmt = stmt.where(self._awaiting_clause())
        if params.q:
            stmt = stmt.where(text_match(params.q))
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        column = SORTS[name]
        stmt = stmt.order_by(column.desc() if direction == "desc" else column.asc(), LeaveRequest.id).limit(params.page_size).offset((params.page - 1) * params.page_size)
        rows = (await self.session.execute(stmt)).all()
        departments = await self._departments()
        types = {t.id: t for t in (await self.session.scalars(select(LeaveType))).all()}
        items = [await leave_request_out(self.session, r, e, departments, types) for r, e in rows]
        return Page.build(PageResult(rows, params.page, params.page_size, total), items)

    async def get(self, request_id: uuid.UUID) -> LeaveRequestOut:
        r, employee = await self._load(request_id)
        return await self._out(r, employee)

    async def attachment(self, request_id: uuid.UUID, attachment_id: uuid.UUID) -> tuple[bytes, LeaveRequestAttachment]:
        r, employee = await self._load(request_id)
        a = await self.session.get(LeaveRequestAttachment, attachment_id)
        if a is None or a.leave_request_id != r.id:
            raise NotFoundError()
        try:
            content = storage.get(a.storage_key)
        except (storage.StorageError, EncryptionUnavailableError):
            raise ServiceUnavailableError("This attachment cannot be opened right now.") from None
        if hashlib.sha256(content).hexdigest() != a.sha256:
            raise ServiceUnavailableError("This attachment cannot be opened right now.")
        self.audit.record(module=MODULE, action="leave_request.attachment_downloaded", summary=f"Attachment of leave request {r.id} opened", entity_type="leave_request", entity_id=r.id,
                          entity_label=employee.full_name, changes=[{"field": "attachmentId", "before": None, "after": str(a.id)}])
        await self.session.commit()
        return content, a

    # ---- Estimate and apply ------------------------------------------------------------------------------------

    async def _applicant(self, raw_id: str | None, *, for_estimate: bool) -> Employee:
        employee_id = body_id(raw_id) if raw_id else self.me
        employee = await self.session.get(Employee, employee_id) if employee_id else None
        own = employee is not None and self.me == employee.id and self.has(P.SELF_SUBMIT_REQUESTS)
        on_behalf = employee is not None and self.has(P.LEAVE_APPLY_ON_BEHALF) and await self._in_scope(employee.id)
        if own or on_behalf:
            return employee
        if not (self.has(P.LEAVE_APPLY_ON_BEHALF) or self.has(P.SELF_SUBMIT_REQUESTS)):
            raise ForbiddenError()
        message = "Choose the employee." if raw_id is None and self.me is None else "You can apply only for yourself or for employees within your organizational scope."
        raise ValidationFailedError(details=[{"field": "employeeId", "message": message}])

    def _shape(self, data: ApplicationInput, err: FieldErrors) -> tuple[date | None, date | None]:
        if not data.leave_type_id:
            err.add("leaveTypeId", "Choose a leave type.")
        start = end = None
        try:
            start = parse_date(data.from_)
        except ValueError:
            pass
        try:
            end = parse_date(data.to)
        except ValueError:
            pass
        if start is None:
            err.add("from", "Enter the first day.")
        if end is None:
            err.add("to", "Enter the last day.")
        if data.portion not in ("full", "first_half", "second_half"):
            err.add("portion", "Choose a full day or a half day.")
        if start and end:
            if end < start:
                err.add("to", "The last day cannot be before the first day.")
            elif (end - start).days + 1 > MAX_RANGE_DAYS:
                err.add("to", f"A request can cover at most {MAX_RANGE_DAYS} days.")
            if data.portion in ("first_half", "second_half") and start != end:
                err.add("portion", "Half days are only possible when the first and last day are the same.")
        return start, end

    async def _evaluate(self, employee: Employee, leave_type: LeaveType, start: date, end: date, portion: str) -> Evaluation:
        ev = Evaluation()
        today = company_today()
        values = await policy_values_on(self.session, today)
        policy = await policy_for(self.session, employee, leave_type.id, start)
        allow_half = leave_type.allow_half_day if policy is None or policy.allow_half_day is None else policy.allow_half_day
        ev.attachment_after_days = policy.attachment_after_days if policy and policy.attachment_after_days is not None else leave_type.attachment_after_days
        if not leave_type.active:
            ev.blocks.append(("leaveTypeId", "This leave type is no longer in use."))
        if portion != "full" and not allow_half:
            ev.blocks.append(("portion", "This leave type cannot be taken as a half day."))
        if start < employee.joining_date:
            ev.blocks.append(("from", "Leave cannot start before the employee's joining date."))

        days = await LeaveCalendar(self.session).range_days(employee, start, end, count_offs=values.on("leave", "countOffsWithinLeave"))
        ev.charged, ev.excluded, ev.warnings = days.charged, days.excluded, list(days.warnings)
        start_month = await leave_year_start_month(self.session)
        by_year: dict[str, float] = defaultdict(float)
        for d in ev.charged:
            by_year[str(leave_year_of(d, start_month))] += 0.5 if portion != "full" else 1.0
        ev.days_by_year = dict(by_year)
        ev.days = sum(by_year.values())
        if ev.days == 0:
            ev.blocks.append(("from", "There are no working days in this range."))

        overlapping = (await self.session.execute(
            select(LeaveRequest, LeaveType.name).join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
            .where(LeaveRequest.employee_id == employee.id, LeaveRequest.status.in_(("pending", "approved")), LeaveRequest.from_date <= end, LeaveRequest.to_date >= start)
            .order_by(LeaveRequest.from_date)
        )).all()
        for other, type_name in overlapping:
            # Two different half days of the same date do not overlap.
            if other.from_date == other.to_date == start == end and {other.portion, portion} == {"first_half", "second_half"}:
                continue
            ev.overlapping.append((other, type_name))
        if ev.overlapping:
            o = ev.overlapping[0][0]
            ev.blocks.append(("from", f"This overlaps with another leave request ({o.from_date.isoformat()} to {o.to_date.isoformat()})."))

        notice = values.get("leave", "minimumNoticeDays")
        window = values.get("leave", "backdatedWindowDays")
        if notice and start >= today and (start - today).days < notice:
            ev.blocks.append(("from", f"Leave must be applied at least {notice} days before it starts."))
        if window and start < today and (today - start).days > window:
            ev.blocks.append(("from", f"Leave can be applied up to {window} days back."))

        if leave_type.balance_tracked and ev.days:
            shortfall = []
            for year, needed in sorted(ev.days_by_year.items()):
                available = await available_days(self.session, employee.id, leave_type.id, int(year))
                if year == str(leave_year_of(start, start_month)):
                    ev.available_before = available
                if needed > available:
                    shortfall.append((year, needed, available))
            for year, needed, available in shortfall:
                suffix = f" in leave year {year}" if len(ev.days_by_year) > 1 else ""
                message = f"This request needs {_d(needed)} days but only {_d(available)} are available{suffix}."
                if values.on("leave", "allowNegativeBalance"):
                    ev.warnings.append(message + " The balance will become negative.")
                else:
                    ev.warnings.append(message)
                    ev.blocks.append(("leaveTypeId", message))
        if ev.attachment_after_days is not None and ev.days > ev.attachment_after_days:
            ev.warnings.append(f"A supporting document is expected for this leave type when the leave is longer than {ev.attachment_after_days} days.")
        return ev

    async def estimate(self, data: ApplicationInput) -> LeaveEstimateOut:
        employee = await self._applicant(data.employee_id, for_estimate=True)
        err = FieldErrors()
        start, end = self._shape(data, err)
        leave_type = await self.session.get(LeaveType, body_id(data.leave_type_id)) if data.leave_type_id and body_id(data.leave_type_id) else None
        if data.leave_type_id and leave_type is None:
            err.add("leaveTypeId", "Choose a leave type.")
        err.raise_if_any()
        ev = await self._evaluate(employee, leave_type, start, end, data.portion)
        warnings = list(ev.warnings)
        for _field, message in ev.blocks:
            if message not in warnings:
                warnings.append(message)
        return LeaveEstimateOut(
            days=ev.days, excluded_dates=[ExcludedDateOut(date=d.isoformat(), reason=reason) for d, reason in ev.excluded], available_before=ev.available_before,
            overlapping=[OverlapOut(id=str(o.id), **{"from": o.from_date.isoformat()}, to=o.to_date.isoformat(), status=o.status, leave_type_name=name) for o, name in ev.overlapping],
            warnings=warnings,
        )

    def _check_files(self, uploads: list[Upload], err: FieldErrors) -> list[tuple[str, bytes, str]]:
        settings = get_settings()
        checked = []
        if len(uploads) > settings.leave_max_attachments:
            err.add("attachments", f"Attach at most {settings.leave_max_attachments} files.")
            return checked
        limit_mb = settings.leave_attachment_max_bytes / (1024 * 1024)
        for u in uploads:
            name = safe_file_name(u.file_name)
            ext = extension_of(name)
            if not u.content:
                err.add("attachments", f"{name} is empty.")
            elif ext not in ALLOWED_EXTENSIONS:
                err.add("attachments", f"{name}: only PDF, JPG and PNG files can be attached.")
            elif len(u.content) > settings.leave_attachment_max_bytes:
                err.add("attachments", f"{name} is larger than {limit_mb:g} MB.")
            else:
                detected = detect(u.content)
                if detected is None or ext not in detected.extensions:
                    err.add("attachments", f"The content of {name} is not a valid {ext} file.")
                else:
                    checked.append((name, u.content, detected.content_type))
        return checked

    async def _resolve_first(self, employee: Employee, kind: str) -> Employee | None:
        if kind == "reporting_manager":
            return await self.session.get(Employee, employee.reporting_manager_id) if employee.reporting_manager_id else None
        dept = await self.session.get(Department, employee.department_id)
        if dept and dept.head_employee_id and dept.head_employee_id != employee.id:
            return await self.session.get(Employee, dept.head_employee_id)
        return None

    async def _route(self, r: LeaveRequest, employee: Employee, now: datetime) -> tuple[str, dict]:
        """Copies the routing onto the request (decision 1: never re-routed). Returns (detail, workflow notifications)."""
        workflow, conflict = await select_workflow(self.session, employee.department_id, company_today())
        if workflow is None:
            manager = await self._resolve_first(employee, "reporting_manager")
            if manager:
                r.approver_kind, r.approver_employee_id, r.approver_name = "reporting_manager", manager.id, manager.full_name
                detail = f"Assigned to {manager.full_name} (reporting manager); no leave approval workflow is active."
            else:
                detail = "No reporting manager and no active leave approval workflow: HR with leave approval permission decides."
            if conflict:
                detail = "Two active leave approval workflows match this employee; routed by the default rule. " + detail
            return detail, {}
        r.workflow_id, r.workflow_snapshot = workflow.id, snapshot(workflow)
        first = await self._resolve_first(employee, workflow.first_approver)
        fb = workflow.fallback_approver
        if first:
            r.approver_kind, r.approver_employee_id, r.approver_name = workflow.first_approver, first.id, first.full_name
            detail = f"Assigned to {first.full_name} ({APPROVER_LABEL[workflow.first_approver]}) by workflow '{workflow.name}'."
        elif fb:
            r.approver_kind, r.approver_ref, r.approver_name = fb["type"], fb["id"], fb["name"]
            detail = f"No {APPROVER_LABEL[workflow.first_approver]} found; assigned to fallback approver {fb['name']} by workflow '{workflow.name}'."
        else:
            detail = f"No {APPROVER_LABEL[workflow.first_approver]} found and workflow '{workflow.name}' has no fallback approver: HR with leave approval permission decides."
        esc = workflow.escalation or {}
        if esc.get("enabled") and esc.get("after") and esc.get("recipient"):
            rec = esc["recipient"]
            r.recipient_kind, r.recipient_ref, r.recipient_name = rec["type"], rec["id"], rec["name"]
            r.escalation_due_at = await LeaveCalendar(self.session).deadline(now, esc["after"], esc.get("unit", "hours"), employee.work_location_id)
            if esc.get("reminderHoursBefore") and workflow.notifications.get("beforeDeadline"):
                r.reminder_at = r.escalation_due_at - timedelta(hours=esc["reminderHoursBefore"])
            detail += f" Escalates to {rec['name']} if not decided by {r.escalation_due_at.astimezone(UTC).strftime('%Y-%m-%d %H:%M')} UTC."
        return detail, workflow.notifications

    def _notify_approver(self, r: LeaveRequest, employee: Employee, title: str, message: str, category: str) -> None:
        notify_approver(self.session, r, title, message, category)

    async def apply(self, data: ApplicationInput) -> LeaveRequestOut:
        employee = await self._applicant(data.employee_id, for_estimate=False)
        err = FieldErrors()
        start, end = self._shape(data, err)
        reason = (data.reason or "").strip()
        if len(reason) < 3:
            err.add("reason", "Enter a reason.")
        elif len(reason) > 500:
            err.add("reason", "Keep the reason under 500 characters.")
        leave_type = await self.session.get(LeaveType, body_id(data.leave_type_id)) if data.leave_type_id and body_id(data.leave_type_id) else None
        if data.leave_type_id and leave_type is None:
            err.add("leaveTypeId", "Choose a leave type.")
        files = self._check_files(data.attachments, err)
        err.raise_if_any()

        # One application at a time per employee: serializes the overlap and balance checks.
        await self.session.execute(select(Employee.id).where(Employee.id == employee.id).with_for_update())
        ev = await self._evaluate(employee, leave_type, start, end, data.portion)
        for f, message in ev.blocks:
            if not err.has(f):
                err.add(f, message)
        err.raise_if_any()

        for name, content, _ in files:
            try:
                await malware_scan.scan(content)
            except malware_scan.MalwareFound:
                self.audit.record(module=MODULE, action="leave_request.attachment_rejected_malware", summary=f"Leave attachment for {employee.employee_code} refused by the virus scan",
                                  entity_type="employee", entity_id=employee.id, entity_label=employee.full_name)
                await self.session.commit()
                raise ValidationFailedError(details=[{"field": "attachments", "message": f"{name} was rejected by the virus scan."}]) from None

        now = datetime.now(UTC)
        r = LeaveRequest(employee_id=employee.id, leave_type_id=leave_type.id, from_date=start, to_date=end, portion=data.portion, days=ev.days, days_by_year=ev.days_by_year,
                         charged_dates=ev.charged, reason=reason, status="pending", stage="first_level")
        detail, notify = await self._route(r, employee, now)
        self.session.add(r)
        await self.session.flush()
        keys: list[str] = []
        try:
            for name, content, content_type in files:
                key = storage.put(content)
                keys.append(key)
                self.session.add(LeaveRequestAttachment(leave_request_id=r.id, file_name=name, content_type=content_type, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), storage_key=key))
            self._event(r, "submitted", reason)
            self._routing(r, "assigned", detail)
            self.audit.record(module=MODULE, action="leave_request.submitted", summary=f"{leave_type.code} leave for {employee.employee_code} {start.isoformat()} to {end.isoformat()} ({_d(ev.days)} days) submitted",
                              entity_type="leave_request", entity_id=r.id, entity_label=employee.full_name)
            if notify.get("onSubmit"):
                self._notify_approver(r, employee, "Leave request to review", f"{employee.full_name} applied for {leave_type.name}: {start.isoformat()} to {end.isoformat()} ({_d(ev.days)} days).", "leave.submitted")
            await self.session.commit()
        except (OSError, EncryptionUnavailableError):
            for k in keys:
                storage.delete(k)
            raise ServiceUnavailableError("Attachments cannot be stored right now.") from None
        except BaseException:
            for k in keys:
                storage.delete(k)  # never leave an unreferenced file behind
            raise
        return await self._out(r, employee)

    # ---- Decide, cancel, comment ---------------------------------------------------------------------------------

    async def _ledger(self, r: LeaveRequest, entry_type: str, sign: int, reason: str) -> None:
        for year, days in r.days_by_year.items():
            self.session.add(LeaveLedgerEntry(employee_id=r.employee_id, leave_type_id=r.leave_type_id, leave_year=int(year), entry_type=entry_type, days=sign * days, leave_request_id=r.id,
                                              reason=reason, period_key=f"{entry_type}:{r.id}:{year}"))

    async def _recalculate(self, r: LeaveRequest, employee: Employee) -> None:
        today = company_today()
        past = [d for d in r.charged_dates if d < today]
        if past:
            await enqueue_recalculation(self.session, [employee.id], min(past), max(past), reason=f"leave {r.id}")

    async def decide(self, request_id: uuid.UUID, data: DecisionIn) -> LeaveRequestOut:
        r, employee = await self._load(request_id, lock=True)  # row lock: the first valid decision wins
        if self.me == employee.id:
            raise ForbiddenError("You cannot decide your own request.")
        if r.status != "pending":
            raise InvalidTransitionError("This request has already been decided.")
        oversight = self.has(P.LEAVE_APPROVE) and await self._in_scope(employee.id)
        approver = self._is_approver(r)
        if not (oversight or approver):
            raise ForbiddenError("You are not an approver for this request.")
        if data.version != r.version:
            raise StaleVersionError()
        comment = (data.comment or "").strip() or None
        if data.decision == "reject" and not comment:
            raise ValidationFailedError(details=[{"field": "comment", "message": "Enter a comment explaining the rejection."}])
        leave_type = await self.session.get(LeaveType, r.leave_type_id)
        if data.decision == "approve":
            if await locked_dates(self.session, min(r.charged_dates), max(r.charged_dates)) & set(r.charged_dates):
                raise PeriodLockedError("Some of these dates are in a finalized payroll period, so this leave can no longer be approved.")
            r.status = "approved"
            await self._ledger(r, "usage", -1, f"Leave {r.from_date.isoformat()} to {r.to_date.isoformat()} approved")
        else:
            r.status = "rejected"
        role = "HR oversight" if oversight and not approver else ("escalation recipient" if r.escalated_at is not None and r.approver_employee_id != self.me else "approver")
        r.stage, r.reviewed_by_name, r.reviewed_at, r.review_comment = "completed", self.caller.principal.name, datetime.now(UTC), comment
        self._event(r, r.status, comment)
        await self.session.flush()
        self.audit.record(module=MODULE, action=f"leave_request.{r.status}", summary=f"{leave_type.code} leave of {employee.employee_code} {r.from_date.isoformat()} to {r.to_date.isoformat()} {r.status} ({role})",
                          entity_type="leave_request", entity_id=r.id, entity_label=employee.full_name)
        if (r.workflow_snapshot or {}).get("notifications", {}).get("onDecision"):
            notifications.queue(self.session, category=f"leave.{r.status}", title=f"Leave {r.status}", message=f"Your {leave_type.name} from {r.from_date.isoformat()} to {r.to_date.isoformat()} was {r.status}." + (f" Comment: {comment}" if comment else ""),
                                link="/hr/me/leave", employee_ids=[employee.id])
        if r.status == "approved":
            await self._recalculate(r, employee)
        await self.session.commit()
        return await self._out(r, employee)

    async def cancel(self, request_id: uuid.UUID, data: CancellationIn) -> LeaveRequestOut:
        r, employee = await self._load(request_id, lock=True)
        own = self.me == employee.id
        on_behalf = self.has(P.LEAVE_APPLY_ON_BEHALF) and await self._in_scope(employee.id)
        if not (own or on_behalf):
            raise ForbiddenError("Only the employee or HR can cancel this request.")
        if r.status == "approved" and r.from_date <= company_today():
            raise InvalidTransitionError("Leave that has started cannot be cancelled.")
        if r.status not in ("pending", "approved"):
            raise InvalidTransitionError("This request can no longer be cancelled.")
        if data.version != r.version:
            raise StaleVersionError()
        comment = (data.comment or "").strip() or None
        was = r.status
        leave_type = await self.session.get(LeaveType, r.leave_type_id)
        if was == "approved":
            await self._ledger(r, "usage_reversal", 1, f"Approved leave {r.from_date.isoformat()} to {r.to_date.isoformat()} cancelled")
        r.status, r.stage = "cancelled", "withdrawn"
        self._event(r, "cancelled", comment)
        await self.session.flush()
        self.audit.record(module=MODULE, action="leave_request.cancelled", summary=f"{was.capitalize()} {leave_type.code} leave of {employee.employee_code} {r.from_date.isoformat()} to {r.to_date.isoformat()} cancelled",
                          entity_type="leave_request", entity_id=r.id, entity_label=employee.full_name)
        flags = (r.workflow_snapshot or {}).get("notifications", {})
        if was == "pending" and flags.get("onSubmit"):
            self._notify_approver(r, employee, "Leave request withdrawn", f"{employee.full_name} withdrew the {leave_type.name} request for {r.from_date.isoformat()} to {r.to_date.isoformat()}.", "leave.cancelled")
        if not own and flags.get("onDecision"):
            notifications.queue(self.session, category="leave.cancelled", title="Leave cancelled", message=f"Your {leave_type.name} from {r.from_date.isoformat()} to {r.to_date.isoformat()} was cancelled by HR.",
                                link="/hr/me/leave", employee_ids=[employee.id])
        await self.session.commit()
        return await self._out(r, employee)

    async def comment(self, request_id: uuid.UUID, data: CommentIn) -> LeaveRequestOut:
        r, employee = await self._load(request_id, lock=True)
        if not (self._is_approver(r) or ((self.has(P.LEAVE_VIEW) or self.has(P.LEAVE_APPROVE)) and await self._in_scope(employee.id))):
            raise ForbiddenError("Only reviewers can comment on this request.")
        if data.version != r.version:
            raise StaleVersionError()
        text = data.comment.strip()
        if not text:
            raise ValidationFailedError(details=[{"field": "comment", "message": "Enter a comment."}])
        if len(text) > 1000:
            raise ValidationFailedError(details=[{"field": "comment", "message": "Keep the comment under 1000 characters."}])
        self._event(r, "commented", text)
        r.updated_at = datetime.now(UTC)  # moves the version: a decision based on the older view is stale
        await self.session.flush()
        self.audit.record(module=MODULE, action="leave_request.commented", summary=f"Comment on leave request of {employee.employee_code}", entity_type="leave_request", entity_id=r.id, entity_label=employee.full_name)
        await self.session.commit()
        return await self._out(r, employee)

    # ---- Summary -------------------------------------------------------------------------------------------------

    async def summary(self) -> LeaveSummaryOut:
        today = company_today()
        values = await policy_values_on(self.session, today)
        departments = await self._departments()
        types = {t.id: t for t in (await self.session.scalars(select(LeaveType))).all()}
        base = select(LeaveRequest, Employee).join(Employee, Employee.id == LeaveRequest.employee_id).where(self.scope_clause)
        on_leave = (await self.session.execute(base.where(LeaveRequest.status == "approved", LeaveRequest.from_date <= today, LeaveRequest.to_date >= today, LeaveRequest.charged_dates.any(today))
                                               .order_by(func.lower(Employee.full_name)).limit(100))).all()
        pending = await self.session.scalar(select(func.count()).select_from(LeaveRequest).join(Employee, Employee.id == LeaveRequest.employee_id).where(self.scope_clause, LeaveRequest.status == "pending")) or 0
        window = values.get("leave", "upcomingWindowDays")
        upcoming = []
        if window:
            upcoming = (await self.session.execute(base.where(LeaveRequest.status == "approved", LeaveRequest.from_date > today, LeaveRequest.from_date <= today + timedelta(days=window))
                                                   .order_by(LeaveRequest.from_date).limit(100))).all()
        awaiting = await self.session.scalar(select(func.count()).select_from(LeaveRequest).where(self._awaiting_clause())) or 0
        threshold = values.get("leave", "lowBalanceThreshold")
        low = []
        if threshold is not None:
            year = leave_year_of(today, await leave_year_start_month(self.session))
            tracked = [t.id for t in types.values() if t.balance_tracked and t.active]
            sums = (await self.session.execute(
                select(LeaveLedgerEntry.employee_id, LeaveLedgerEntry.leave_type_id, func.sum(LeaveLedgerEntry.days))
                .join(Employee, Employee.id == LeaveLedgerEntry.employee_id)
                .where(self.scope_clause, LeaveLedgerEntry.leave_year == year, LeaveLedgerEntry.leave_type_id.in_(tracked))
                .group_by(LeaveLedgerEntry.employee_id, LeaveLedgerEntry.leave_type_id)
            )).all()
            pend: dict = defaultdict(float)
            for emp, typ, by_year in (await self.session.execute(select(LeaveRequest.employee_id, LeaveRequest.leave_type_id, LeaveRequest.days_by_year).where(LeaveRequest.status == "pending"))).all():
                pend[(emp, typ)] += float(by_year.get(str(year), 0))
            candidates = sorted(((float(total) - pend[(emp, typ)], emp, typ) for emp, typ, total in sums if float(total) - pend[(emp, typ)] <= threshold), key=lambda x: x[0])[:50]
            employees = {e.id: e for e in (await self.session.scalars(select(Employee).where(Employee.id.in_([c[1] for c in candidates])))).all()} if candidates else {}
            low = [LowBalanceOut(employee=employee_ref(employees[emp], departments), leave_type_name=types[typ].name, available=round(avail, 2)) for avail, emp, typ in candidates]
        return LeaveSummaryOut(
            on_leave_today=[OnLeaveTodayOut(employee=employee_ref(e, departments), leave_type_name=types[r.leave_type_id].name, to=r.to_date.isoformat(), portion=r.portion) for r, e in on_leave],
            pending_requests=pending,
            upcoming=[UpcomingLeaveOut(id=str(r.id), employee=employee_ref(e, departments), leave_type_name=types[r.leave_type_id].name, **{"from": r.from_date.isoformat()}, to=r.to_date.isoformat(), days=float(r.days))
                      for r, e in upcoming],
            upcoming_window_days=int(window or 0), awaiting_my_action=awaiting, low_balances=low, low_balance_threshold=float(threshold or 0), as_of=datetime.now(UTC),
        )


# ---- Worker: reminders and escalation (`leave.escalate`) ---------------------------------------------------------------


async def escalate_leave(session: AsyncSession) -> dict:
    """Sends due reminders and escalates overdue requests to their recipient. Escalation never
    decides a request (H3). The original approver may still decide (decision 2)."""
    now = datetime.now(UTC)
    audit = AuditService(session)
    reminders = escalated = 0
    due = (await session.scalars(select(LeaveRequest).where(LeaveRequest.status == "pending", LeaveRequest.reminder_at.is_not(None), LeaveRequest.reminder_at <= now,
                                                            LeaveRequest.reminder_sent_at.is_(None), LeaveRequest.escalated_at.is_(None),
                                                            LeaveRequest.escalation_due_at > now).with_for_update(skip_locked=True))).all()  # an overdue request is escalated instead
    for r in due:
        employee = await session.get(Employee, r.employee_id)
        r.reminder_sent_at = now
        session.add(LeaveRoutingEvent(leave_request_id=r.id, action="reminder_sent", detail=f"Reminder sent to {r.approver_name or 'the approver'}: escalates at {r.escalation_due_at.strftime('%Y-%m-%d %H:%M')} UTC."))
        audit.record(module=MODULE, action="leave_request.reminder_sent", summary=f"Reminder for leave request of {employee.employee_code}", entity_type="leave_request", entity_id=r.id, entity_label=employee.full_name)
        notify_approver(session, r, "Leave request waiting for you", f"The leave request of {employee.full_name} escalates if not decided by {r.escalation_due_at.strftime('%Y-%m-%d %H:%M')} UTC.", "leave.reminder")
        reminders += 1
    overdue = (await session.scalars(select(LeaveRequest).where(LeaveRequest.status == "pending", LeaveRequest.escalation_due_at.is_not(None), LeaveRequest.escalation_due_at <= now,
                                                                LeaveRequest.escalated_at.is_(None)).with_for_update(skip_locked=True))).all()
    for r in overdue:
        employee = await session.get(Employee, r.employee_id)
        r.escalated_at, r.stage = now, "escalated"
        session.add(LeaveRoutingEvent(leave_request_id=r.id, action="escalated", detail=f"Not decided by the deadline; escalated to {r.recipient_name}. {r.approver_name or 'The original approver'} can still decide."))
        audit.record(module=MODULE, action="leave_request.escalated", summary=f"Leave request of {employee.employee_code} escalated to {r.recipient_name}", entity_type="leave_request", entity_id=r.id, entity_label=employee.full_name)
        if (r.workflow_snapshot or {}).get("notifications", {}).get("onEscalation"):
            targets = {"role_codes": [r.recipient_ref]} if r.recipient_kind == "role" else {"user_ids": [r.recipient_ref]}
            notifications.queue(session, category="leave.escalated", title="Escalated leave request", message=f"The leave request of {employee.full_name} was not decided in time and is escalated to you.",
                                link=f"/hr/leave/requests?open={r.id}", **targets)
            notify_approver(session, r, "Leave request escalated", f"The leave request of {employee.full_name} was escalated to {r.recipient_name}. You can still decide it.", "leave.escalated")
        escalated += 1
    await session.commit()
    return {"reminders": reminders, "escalated": escalated}


def notify_approver(session: AsyncSession, r: LeaveRequest, title: str, message: str, category: str) -> None:
    targets: dict = {"employee_ids": [], "user_ids": [], "role_codes": []}
    if r.approver_kind in ("reporting_manager", "department_head") and r.approver_employee_id:
        targets["employee_ids"].append(r.approver_employee_id)
    elif r.approver_kind == "role":
        targets["role_codes"].append(r.approver_ref)
    elif r.approver_kind == "user":
        targets["user_ids"].append(r.approver_ref)
    notifications.queue(session, category=category, title=title, message=message, link=f"/hr/leave/requests?open={r.id}", **targets)

