"""Leave approval workflows (contract H3): configuration, validation, history and routing selection.

- Only `active` workflows route requests. A department workflow takes precedence over the company
  default for its departments. Two active workflows competing for the same requests in an
  overlapping period are refused (the frontend's `findWorkflowConflicts`, re-checked here).
- Owner decision 1: requests keep the routing they were given at submission. Saving, changing or
  deactivating a workflow affects only new requests (the routing is copied onto each request).
- Every save is recorded in the workflow's append-only history and in the audit log.
- No workflow is pre-filled. Without an active one, the contract E rule routes requests.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.models.attendance_model import Workflow
from app.models.department_model import Department
from app.models.employee_access_scope_model import EmployeeAccessScope
from app.models.leave_model import LeaveApprovalWorkflow, LeaveWorkflowHistory
from app.schemas.employee_schema import NamedRefOut
from app.schemas.leave_schema import (
    ApproverRefOut,
    EscalationOut,
    LeaveWorkflowHistoryOut,
    LeaveWorkflowIn,
    LeaveWorkflowOptionsOut,
    LeaveWorkflowOut,
    NotificationsOut,
)
from app.services.audit_service import AuditService, diff
from app.services.employee_support import parse_date
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

MAX_AFTER = {"hours": 720, "days": 30, "working_days": 30}


def _overlaps(a_from: date, a_to: date | None, b_from: date, b_to: date | None) -> bool:
    return a_from <= (b_to or date.max) and b_from <= (a_to or date.max)


def snapshot(w: LeaveApprovalWorkflow) -> dict:
    """The routing settings copied onto a request at submission (never re-routed)."""
    return {"id": str(w.id), "name": w.name, "version": w.version, "firstApprover": w.first_approver, "fallbackApprover": w.fallback_approver,
            "escalation": w.escalation, "notifications": w.notifications}


class LeaveWorkflowService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.audit = AuditService(session)

    async def _departments(self) -> dict[uuid.UUID, str]:
        return {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}

    async def _out(self, w: LeaveApprovalWorkflow, departments: dict | None = None) -> LeaveWorkflowOut:
        departments = departments if departments is not None else await self._departments()
        history = (await self.session.scalars(select(LeaveWorkflowHistory).where(LeaveWorkflowHistory.workflow_id == w.id).order_by(LeaveWorkflowHistory.created_at, LeaveWorkflowHistory.id))).all()
        esc = w.escalation
        fb = w.fallback_approver
        return LeaveWorkflowOut(
            id=str(w.id), name=w.name, status=w.status, scope=w.scope, departments=[NamedRefOut(id=str(d), name=departments.get(d, "")) for d in w.department_ids],
            first_approver=w.first_approver, fallback_approver=ApproverRefOut(**fb) if fb else None,
            escalation=EscalationOut(enabled=esc["enabled"], after=esc.get("after"), unit=esc.get("unit", "hours"), reminder_hours_before=esc.get("reminderHoursBefore"),
                                     recipient=ApproverRefOut(**esc["recipient"]) if esc.get("recipient") else None),
            notifications=NotificationsOut(on_submit=w.notifications["onSubmit"], before_deadline=w.notifications["beforeDeadline"], on_escalation=w.notifications["onEscalation"], on_decision=w.notifications["onDecision"]),
            effective_from=w.effective_from.isoformat(), effective_to=w.effective_to.isoformat() if w.effective_to else None,
            history=[LeaveWorkflowHistoryOut(version=h.workflow_version, at=h.created_at, by=h.created_by_name, action=h.action, note=h.note) for h in history],
            version=w.version, updated_at=w.updated_at, updated_by=w.updated_by_name,
        )

    async def list(self) -> list[LeaveWorkflowOut]:
        departments = await self._departments()
        rows = (await self.session.scalars(select(LeaveApprovalWorkflow).order_by(LeaveApprovalWorkflow.name, LeaveApprovalWorkflow.id))).all()
        return [await self._out(w, departments) for w in rows]

    async def options(self) -> LeaveWorkflowOptionsOut:
        """Roles and users already used in HRMS configuration (until an Identity API exists)."""
        roles: dict[str, str] = {}
        users: dict[str, str] = {}
        for code in (await self.session.scalars(select(EmployeeAccessScope.role_code).distinct())).all():
            roles.setdefault(code, code)
        for w in (await self.session.scalars(select(LeaveApprovalWorkflow))).all():
            for ref in (w.fallback_approver, (w.escalation or {}).get("recipient")):
                if ref:
                    (roles if ref["type"] == "role" else users).setdefault(ref["id"], ref["name"])
        for w in (await self.session.scalars(select(Workflow))).all():
            for step in w.steps:
                if step.get("roleId"):
                    roles.setdefault(step["roleId"], step["roleId"])
                if step.get("userId"):
                    users.setdefault(step["userId"], step["userId"])
                fb = step.get("fallback") or {}
                if fb.get("roleId"):
                    roles.setdefault(fb["roleId"], fb["roleId"])
                if fb.get("userId"):
                    users.setdefault(fb["userId"], fb["userId"])
        return LeaveWorkflowOptionsOut(
            roles=[NamedRefOut(id=k, name=v) for k, v in sorted(roles.items(), key=lambda kv: kv[1].lower())],
            users=[NamedRefOut(id=k, name=v) for k, v in sorted(users.items(), key=lambda kv: kv[1].lower())],
            working_days=list(get_settings().company_working_days),
        )

    async def save(self, workflow_id: uuid.UUID | None, data: LeaveWorkflowIn) -> LeaveWorkflowOut:
        err = FieldErrors()
        departments = await self._departments()
        name = data.name.strip()
        if len(name) < 3:
            err.add("name", "Enter a name of at least 3 characters.")
        elif len(name) > 120:
            err.add("name", "Keep the name under 120 characters.")
        dept_ids = [body_id(d) for d in data.department_ids]
        if data.scope == "departments":
            if not dept_ids:
                err.add("departmentIds", "Choose at least one department.")
            elif any(d not in departments for d in dept_ids):
                err.add("departmentIds", "Choose existing departments.")
        else:
            dept_ids = []
        start = end = None
        try:
            start = parse_date(data.effective_from)
        except ValueError:
            pass
        if start is None:
            err.add("effectiveFrom", "Enter the date the workflow takes effect.")
        try:
            end = parse_date(data.effective_to)
        except ValueError:
            err.add("effectiveTo", "Enter a valid date.")
        if start and end and end < start:
            err.add("effectiveTo", "The end date must be on or after the start date.")
        fb = data.fallback_approver
        if fb and not fb.id.strip():
            err.add("fallbackApprover", "Choose the fallback approver.")
        esc = data.escalation
        if esc.enabled:
            if esc.unit == "working_days" and not get_settings().company_working_days:
                err.add("unit", "Company working days are not configured yet, so working days cannot be used. Use hours or days.")
            if not esc.after or esc.after < 1:
                err.add("after", "Enter how long the approver has before escalation.")
            elif esc.after > MAX_AFTER[esc.unit]:
                err.add("after", "Use at most 720 hours." if esc.unit == "hours" else "Use at most 30 days.")
            if esc.recipient is None or not esc.recipient.id.strip():
                err.add("recipient", "Choose who receives escalated requests.")
            deadline_hours = (esc.after or 0) * (1 if esc.unit == "hours" else 24)
            if esc.reminder_hours_before is not None and (esc.reminder_hours_before < 1 or (deadline_hours and esc.reminder_hours_before >= deadline_hours)):
                err.add("reminderHoursBefore", "The reminder must come before the deadline.")
        err.raise_if_any()

        if data.status == "active":
            others = (await self.session.scalars(select(LeaveApprovalWorkflow).where(LeaveApprovalWorkflow.status == "active", LeaveApprovalWorkflow.scope == data.scope,
                                                                                    LeaveApprovalWorkflow.id != (workflow_id or uuid.uuid4())))).all()
            conflicts = [o for o in others if _overlaps(o.effective_from, o.effective_to, start, end) and (data.scope == "company" or set(o.department_ids) & set(dept_ids))]
            if conflicts:
                names = ", ".join(f'"{c.name}"' for c in conflicts)
                field = "scope" if data.scope == "company" else "departmentIds"
                err.add(field, f"Conflicts with active workflow {names} for the same {'scope' if data.scope == 'company' else 'departments'} and period.")
                err.raise_if_any(code="WORKFLOW_CONFLICT")

        values = dict(
            name=name, status=data.status, scope=data.scope, department_ids=dept_ids, first_approver=data.first_approver,
            fallback_approver={"type": fb.type, "id": fb.id.strip(), "name": fb.name.strip() or fb.id.strip()} if fb else None,
            escalation={"enabled": esc.enabled, "after": esc.after, "unit": esc.unit, "reminderHoursBefore": esc.reminder_hours_before,
                        "recipient": {"type": esc.recipient.type, "id": esc.recipient.id.strip(), "name": esc.recipient.name.strip() or esc.recipient.id.strip()} if esc.recipient else None},
            notifications={"onSubmit": data.notifications.on_submit, "beforeDeadline": data.notifications.before_deadline, "onEscalation": data.notifications.on_escalation, "onDecision": data.notifications.on_decision},
            effective_from=start, effective_to=end,
        )
        if workflow_id is None:
            w = LeaveApprovalWorkflow(**values)
            self.session.add(w)
            action, before = "created", {}
        else:
            w = await self.session.get(LeaveApprovalWorkflow, workflow_id)
            if w is None:
                raise NotFoundError()
            ensure_version(w, data.version)
            before = (await self._out(w, departments)).model_dump(exclude={"history", "version", "updated_at", "updated_by"})
            if data.status == "active" and w.status != "active":
                action = "activated"
            elif data.status != "active" and w.status == "active":
                action = "deactivated"
            else:
                action = "updated"
            for k, v in values.items():
                setattr(w, k, v)
        await self.session.flush()
        self.session.add(LeaveWorkflowHistory(workflow_id=w.id, workflow_version=w.version, action=action, note=None))
        await self.session.flush()
        out = await self._out(w, departments)
        self.audit.record(module="Leave", action=f"leave_workflow.{action}", summary=f"Leave approval workflow '{w.name}' {action}", entity_type="leave_approval_workflow", entity_id=w.id, entity_label=w.name,
                          changes=diff(before, out.model_dump(exclude={"history", "version", "updated_at", "updated_by"})) if before else None)
        await self.session.commit()
        return out


async def select_workflow(session: AsyncSession, department_id: uuid.UUID, on: date) -> tuple[LeaveApprovalWorkflow | None, bool]:
    """The active workflow routing a request: department workflow first, then the company default.
    Returns (workflow, conflict); a conflict (two matches) can only exist if data was changed outside
    the API, and is routed by the default rule with a warning."""
    live = [w for w in (await session.scalars(select(LeaveApprovalWorkflow).where(LeaveApprovalWorkflow.status == "active"))).all()
            if w.effective_from <= on and (w.effective_to is None or on <= w.effective_to)]
    dept = [w for w in live if w.scope == "departments" and department_id in w.department_ids]
    if len(dept) > 1:
        return None, True
    if dept:
        return dept[0], False
    company = [w for w in live if w.scope == "company"]
    if len(company) > 1:
        return None, True
    return (company[0] if company else None), False
