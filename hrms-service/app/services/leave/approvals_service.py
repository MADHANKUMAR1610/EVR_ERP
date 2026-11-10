"""The caller's approval inbox (contract E3): pending requests the caller may decide NOW, across
leave, permission, overtime and attendance-correction requests. Decisions are posted to each
type's own decision endpoint. Oldest first. `counts` are per type, unfiltered.

The same rules as the decision endpoints decide what is listed: HR oversight (each type's approve
permission, employee in scope), the assigned or escalated approver (with hr.approvals:act), or the
reporting manager where the contract E rule applies. Never the caller's own requests.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import P
from app.models.attendance_model import AttendanceCorrection
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.models.leave_model import LeaveRequest, LeaveType, OvertimeRequest, PermissionRequest
from app.schemas.common import PageMeta
from app.schemas.leave_schema import ApprovalCountsOut, ApprovalInboxOut, ApprovalItemOut
from app.services.attendance.attendance_read_service import employee_ref
from app.services.attendance.workflow_service import WorkflowEngine
from app.services.employee_scope_service import EmployeeScopeService, caller_employee_id
from app.services.employee_support import Caller
from app.services.leave.request_service import LeaveRequestService

TYPES = ("leave", "permission", "overtime", "attendance_correction")


@dataclass
class _Item:
    type: str
    request_id: uuid.UUID
    employee_id: uuid.UUID
    summary: str
    date: str
    submitted_at: datetime
    version: int


def _fmt(d) -> str:
    return d.strftime("%d %b")


class ApprovalsService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.scope_clause = EmployeeScopeService.clause(caller.scope)
        self.me = caller_employee_id(caller.principal)
        self.engine = WorkflowEngine(session)

    def has(self, code: str) -> bool:
        return self.caller.has(code)

    def _not_own(self, column):
        return column != self.me if self.me else column.is_not(None)

    def _manager(self):
        return Employee.reporting_manager_id == self.me if self.me and self.has(P.APPROVALS_ACT) else false()

    async def _leave(self) -> list[_Item]:
        clause = LeaveRequestService(self.session, self.caller)._awaiting_clause()
        rows = (await self.session.execute(select(LeaveRequest, LeaveType.name).join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id).where(clause))).all()
        out = []
        for r, type_name in rows:
            span = _fmt(r.from_date) if r.from_date == r.to_date else f"{_fmt(r.from_date)}–{_fmt(r.to_date)}"
            out.append(_Item("leave", r.id, r.employee_id, f"{type_name} · {float(r.days):g} {'day' if float(r.days) == 1 else 'days'} · {span}", r.from_date.isoformat(), r.created_at, r.version))
        return out

    async def _permission(self) -> list[_Item]:
        conds = [self._manager()]
        if self.has(P.PERMISSION_REQUESTS_APPROVE):
            conds.append(self.scope_clause)
        rows = (await self.session.scalars(select(PermissionRequest).join(Employee, Employee.id == PermissionRequest.employee_id)
                                           .where(PermissionRequest.status == "pending", self._not_own(PermissionRequest.employee_id), or_(*conds)))).all()
        return [_Item("permission", r.id, r.employee_id, f"Permission · {r.from_time}–{r.to_time} ({r.minutes} min) · {_fmt(r.date)}", r.date.isoformat(), r.created_at, r.version) for r in rows]

    async def _workflow_rows(self, model, approve_permission: str) -> list:
        """Pending requests decided through a G5 workflow (overtime, corrections): HR oversight in
        scope, the current step's approver, or (no workflow) the reporting manager."""
        stmt = select(model, Employee).join(Employee, Employee.id == model.employee_id).where(model.status == "pending", self._not_own(model.employee_id))
        oversight_ids = set()
        if self.has(approve_permission):
            oversight_ids = set((await self.session.scalars(select(model.id).join(Employee, Employee.id == model.employee_id).where(model.status == "pending", self.scope_clause))).all())
        if not self.has(P.APPROVALS_ACT):
            stmt = stmt.where(model.id.in_(oversight_ids) if oversight_ids else false())
        out = []
        for r, e in (await self.session.execute(stmt)).all():
            if r.id in oversight_ids:
                out.append(r)
            elif r.steps and r.current_step is not None:
                if await self.engine.is_step_approver(r.steps[r.current_step], self.caller.principal, e, r.escalated):
                    out.append(r)
            elif not r.steps and self.me and e.reporting_manager_id == self.me:
                out.append(r)
        return out

    async def _overtime(self) -> list[_Item]:
        rows = await self._workflow_rows(OvertimeRequest, P.OVERTIME_APPROVE)
        return [_Item("overtime", r.id, r.employee_id, f"Overtime · {r.minutes // 60}h {r.minutes % 60:02d}m · {_fmt(r.date)}", r.date.isoformat(), r.created_at, r.version) for r in rows]

    async def _corrections(self) -> list[_Item]:
        rows = await self._workflow_rows(AttendanceCorrection, P.ATTENDANCE_CORRECTIONS_APPROVE)
        return [_Item("attendance_correction", r.id, r.employee_id, f"Attendance correction · {_fmt(r.date)}", r.date.isoformat(), r.created_at, r.version) for r in rows]

    async def inbox(self, *, type_: str | None, page: int, page_size: int) -> ApprovalInboxOut:
        by_type = {"leave": await self._leave(), "permission": await self._permission(), "overtime": await self._overtime(), "attendance_correction": await self._corrections()}
        counts = ApprovalCountsOut(**{t: len(v) for t, v in by_type.items()})
        items = by_type[type_] if type_ else [i for t in TYPES for i in by_type[t]]
        items.sort(key=lambda i: (i.submitted_at, str(i.request_id)))
        total = len(items)
        page_items = items[(page - 1) * page_size: page * page_size]
        employees = {e.id: e for e in (await self.session.scalars(select(Employee).where(Employee.id.in_([i.employee_id for i in page_items])))).all()} if page_items else {}
        departments = {d.id: d.name for d in (await self.session.scalars(select(Department))).all()}
        return ApprovalInboxOut(
            items=[ApprovalItemOut(id=f"{i.type}:{i.request_id}", type=i.type, request_id=str(i.request_id), employee=employee_ref(employees[i.employee_id], departments), summary=i.summary,
                                   date=i.date, submitted_at=i.submitted_at, version=i.version) for i in page_items],
            meta=PageMeta(page=page, page_size=page_size, total_items=total, total_pages=math.ceil(total / page_size)),
            counts=counts,
        )
