"""Approval workflow configuration (contract G5) and the engine that runs them.

Configuration: drafts are saved freely (shape checks only); publishing validates and freezes the
steps into `published`, which is what the engine uses; saving a published workflow makes a new
draft while the published version stays in force; publishing archives any other published
workflow of the same process from the new effectiveFrom.

Engine (`WorkflowEngine`): picks the workflow in force on the request date, copies its steps onto
the request (requests keep the version they started with), resolves approvers, skips optional steps
without an approver, escalates overdue steps to their fallback, and decides who may act.
Only `attendance_correction` is executed in Module 5; other processes run when their modules exist.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import Principal
from app.core.errors import NotFoundError, ValidationFailedError
from app.core.permissions import P, has_permission
from app.models.attendance_model import Workflow, WorkflowHistory
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.schemas.workflow_schema import ConditionFieldOut, ProcessDefinitionOut, WorkflowHistoryOut, WorkflowIn, WorkflowOut, WorkflowStep
from app.services.audit_service import AuditService
from app.services.employee_scope_service import caller_employee_id
from app.services.employee_support import parse_date
from app.utils.validation import FieldErrors, ensure_version

PROCESSES = {
    "attendance_correction": ("Attendance corrections", [ConditionFieldOut(field="daysSinceDate", label="Days since the corrected date", unit="days")]),
    "overtime": ("Overtime requests", []),
    "payroll": ("Payroll approval", []),
    "performance_review": ("Performance reviews", []),
}


def _workflow_out(w: Workflow, history: list[WorkflowHistory]) -> WorkflowOut:
    return WorkflowOut(
        id=str(w.id), name=w.name, description=w.description, process=w.process, status=w.status, version=w.version,
        effective_from=w.effective_from.isoformat() if w.effective_from else None, effective_to=w.effective_to.isoformat() if w.effective_to else None,
        steps=[WorkflowStep.model_validate(s) for s in w.steps],
        history=[WorkflowHistoryOut(version=h.workflow_version, status=h.status, at=h.created_at, by=h.created_by_name, note=h.note) for h in history],
        updated_at=w.updated_at, updated_by=w.updated_by_name,
    )


class WorkflowService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.audit = AuditService(session)

    @staticmethod
    def processes() -> list[ProcessDefinitionOut]:
        return [ProcessDefinitionOut(process=p, label=label, condition_fields=fields) for p, (label, fields) in PROCESSES.items()]

    async def _history(self, workflow_id: uuid.UUID) -> list[WorkflowHistory]:
        return list((await self.session.scalars(select(WorkflowHistory).where(WorkflowHistory.workflow_id == workflow_id).order_by(WorkflowHistory.created_at))).all())

    async def _get(self, workflow_id: uuid.UUID) -> Workflow:
        w = await self.session.get(Workflow, workflow_id)
        if w is None:
            raise NotFoundError()
        return w

    async def list(self) -> list[WorkflowOut]:
        rows = (await self.session.scalars(select(Workflow).order_by(Workflow.process, Workflow.name))).all()
        return [_workflow_out(w, await self._history(w.id)) for w in rows]

    async def get(self, workflow_id: uuid.UUID) -> WorkflowOut:
        w = await self._get(workflow_id)
        return _workflow_out(w, await self._history(w.id))

    @staticmethod
    def _dates(data: WorkflowIn, err: FieldErrors) -> tuple[date | None, date | None]:
        out = []
        for field, raw in (("effectiveFrom", data.effective_from), ("effectiveTo", data.effective_to)):
            try:
                out.append(parse_date(raw))
            except ValueError:
                err.add(field, "Enter a valid date.")
                out.append(None)
        return out[0], out[1]

    async def save(self, workflow_id: uuid.UUID | None, data: WorkflowIn) -> WorkflowOut:
        """Saves a draft. Shape checks only (G5); full validation runs at publication."""
        if data.process not in PROCESSES:
            raise ValidationFailedError(details=[{"field": "process", "message": "Leave routing is configured under Leave approval workflows."}])
        err = FieldErrors()
        effective_from, effective_to = self._dates(data, err)
        if len({s.id for s in data.steps}) != len(data.steps):
            err.add("steps", "Each step needs a different id.")
        err.raise_if_any()
        steps = [s.model_dump(by_alias=True) for s in data.steps]
        if workflow_id is None:
            w = Workflow(name=data.name.strip(), description=data.description.strip(), process=data.process, status="draft", effective_from=effective_from, effective_to=effective_to, steps=steps)
            self.session.add(w)
        else:
            w = await self._get(workflow_id)
            ensure_version(w, data.version)
            if w.status == "archived":
                raise ValidationFailedError("An archived workflow cannot be changed. Create a new one.")
            if data.process != w.process:
                raise ValidationFailedError(details=[{"field": "process", "message": "The process of a workflow cannot be changed."}])
            w.name, w.description, w.effective_from, w.effective_to, w.steps = data.name.strip(), data.description.strip(), effective_from, effective_to, steps
            w.status = "draft"  # a published version stays in force (w.published) until this draft is published
        await self.session.flush()
        self.audit.record(module="Workflows", action="workflow.saved", summary=f"Workflow '{w.name}' saved as draft", entity_type="workflow", entity_id=w.id, entity_label=w.name)
        await self.session.commit()
        return await self.get(w.id)

    def _validate_for_publication(self, w: Workflow) -> None:
        err = FieldErrors()
        steps = [WorkflowStep.model_validate(s) for s in w.steps]
        if not steps:
            err.add("steps", "Add at least one step.")
        elif not any(s.required for s in steps):
            err.add("steps", "At least one step must be required.")
        allowed = {f.field for f in PROCESSES[w.process][1]}
        for i, s in enumerate(steps):
            if s.approver_type == "role" and not (s.role_id or "").strip():
                err.add(f"steps.{i}.roleId", "Choose the approving role.")
            if s.approver_type == "user" and not (s.user_id or "").strip():
                err.add(f"steps.{i}.userId", "Choose the approving user.")
            if s.condition and s.condition.field not in allowed:
                err.add(f"steps.{i}.condition", "This condition is not available for this process.")
            if (s.fallback is None) != (s.escalate_after_hours is None):
                err.add(f"steps.{i}.fallback", "A fallback needs an escalation time, and an escalation time needs a fallback.")
            if s.fallback and s.fallback.type == "role" and not (s.fallback.role_id or "").strip():
                err.add(f"steps.{i}.fallback", "Choose the fallback role.")
            if s.fallback and s.fallback.type == "user" and not (s.fallback.user_id or "").strip():
                err.add(f"steps.{i}.fallback", "Choose the fallback user.")
        if w.effective_from is None:
            err.add("effectiveFrom", "Enter the date the workflow takes effect.")
        if w.effective_to and w.effective_from and w.effective_to < w.effective_from:
            err.add("effectiveTo", "The end date must be on or after the start date.")
        err.raise_if_any()

    async def publish(self, workflow_id: uuid.UUID, version: int, note: str) -> WorkflowOut:
        w = await self._get(workflow_id)
        ensure_version(w, version)
        if w.status == "archived":
            raise ValidationFailedError("An archived workflow cannot be published.")
        self._validate_for_publication(w)
        others = (await self.session.scalars(select(Workflow).where(Workflow.process == w.process, Workflow.id != w.id, Workflow.published.is_not(None)))).all()
        new_end = w.effective_from - timedelta(days=1)
        for other in others:
            # "Archived from the new effectiveFrom" (G5): it stays in force until the day before.
            other_from = date.fromisoformat(other.published["effectiveFrom"])
            current_to = date.fromisoformat(other.published["effectiveTo"]) if other.published.get("effectiveTo") else None
            if new_end < other_from:
                other.published = None
            else:
                other.published = {**other.published, "effectiveTo": (min(current_to, new_end) if current_to else new_end).isoformat()}
            other.status = "archived"
            self.session.add(WorkflowHistory(workflow_id=other.id, workflow_version=other.version, status="archived", note=f"Replaced by '{w.name}' from {w.effective_from.isoformat()}"))
        published_version = w.version + 1  # this update is the publication; the version moves once
        w.status = "published"
        w.published = {"version": published_version, "effectiveFrom": w.effective_from.isoformat(), "effectiveTo": w.effective_to.isoformat() if w.effective_to else None, "steps": w.steps}
        self.session.add(WorkflowHistory(workflow_id=w.id, workflow_version=published_version, status="published", note=note.strip()))
        await self.session.flush()
        self.audit.record(module="Workflows", action="workflow.published", summary=f"Workflow '{w.name}' published (version {w.version})", entity_type="workflow", entity_id=w.id, entity_label=w.name)
        await self.session.commit()
        return await self.get(w.id)

    async def archive(self, workflow_id: uuid.UUID, version: int, note: str) -> WorkflowOut:
        w = await self._get(workflow_id)
        ensure_version(w, version)
        w.status = "archived"
        w.published = None  # no longer used for new requests; requests in progress keep their copied steps
        self.session.add(WorkflowHistory(workflow_id=w.id, workflow_version=w.version, status="archived", note=note.strip()))
        await self.session.flush()
        self.audit.record(module="Workflows", action="workflow.archived", summary=f"Workflow '{w.name}' archived", entity_type="workflow", entity_id=w.id, entity_label=w.name)
        await self.session.commit()
        return await self.get(w.id)


class WorkflowEngine:
    """Runs a published workflow for one request (Module 5: attendance corrections)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def in_force(self, process: str, on: date) -> Workflow | None:
        candidates = (await self.session.scalars(select(Workflow).where(Workflow.process == process, Workflow.published.is_not(None)))).all()
        live = [w for w in candidates if w.published and date.fromisoformat(w.published["effectiveFrom"]) <= on and (not w.published.get("effectiveTo") or on <= date.fromisoformat(w.published["effectiveTo"]))]
        return max(live, key=lambda w: w.published["effectiveFrom"], default=None)

    @staticmethod
    def applicable_steps(steps: list[dict], facts: dict[str, float]) -> list[dict]:
        out = []
        for s in steps:
            c = s.get("condition")
            if c:
                value = facts.get(c["field"])
                ops = {"gt": lambda a, b: a > b, "gte": lambda a, b: a >= b, "lt": lambda a, b: a < b, "lte": lambda a, b: a <= b}
                if value is None or not ops[c["operator"]](value, c["value"]):
                    continue
            out.append(s)
        return out

    async def approver_exists(self, step: dict, employee: Employee) -> bool:
        if step["approverType"] == "reporting_manager":
            return employee.reporting_manager_id is not None
        if step["approverType"] == "department_head":
            dept = await self.session.get(Department, employee.department_id)
            return bool(dept and dept.head_employee_id and dept.head_employee_id != employee.id)
        return True  # a role or named user always exists as configured (Identity owns them)

    async def first_step(self, steps: list[dict], employee: Employee, start: int = 0) -> int | None:
        """Index of the next step that needs a decision: optional steps without an approver are skipped (G5)."""
        for i in range(start, len(steps)):
            if steps[i]["required"] or await self.approver_exists(steps[i], employee):
                return i
        return None

    async def is_step_approver(self, step: dict, principal: Principal, employee: Employee, escalated: bool) -> bool:
        if not has_permission(principal.permissions, P.APPROVALS_ACT):
            return False
        me = caller_employee_id(principal)
        if escalated and step.get("fallback"):
            fb = step["fallback"]
            return (fb["type"] == "role" and fb.get("roleId") in principal.roles) or (fb["type"] == "user" and fb.get("userId") == principal.user_id)
        kind = step["approverType"]
        if kind == "reporting_manager":
            return me is not None and employee.reporting_manager_id == me
        if kind == "department_head":
            dept = await self.session.get(Department, employee.department_id)
            return me is not None and dept is not None and dept.head_employee_id == me
        if kind == "role":
            return step.get("roleId") in principal.roles
        return step.get("userId") == principal.user_id

    @staticmethod
    def overdue(step: dict, started: datetime | None, now: datetime) -> bool:
        hours = step.get("escalateAfterHours")
        return bool(hours and step.get("fallback") and started and now - started >= timedelta(hours=hours))


