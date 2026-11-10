"""Builds LeaveRequest responses (history, attachments, routing and escalation state)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_model import Employee
from app.models.leave_model import LeaveRequest, LeaveRequestAttachment, LeaveRoutingEvent, LeaveType, RequestEvent
from app.schemas.attendance_schema import WorkflowEventOut
from app.schemas.leave_schema import ApproverStateOut, LeaveApprovalStateOut, LeaveAttachmentOut, LeaveRequestOut, RoutingEventOut, WorkflowRefOut
from app.services.attendance.attendance_read_service import employee_ref
from app.services.leave.setup_service import type_ref


def escalation_status(r: LeaveRequest, now: datetime) -> str:
    if r.status != "pending":
        return "not_applicable"
    if r.escalated_at is not None:
        return "escalated"
    if r.escalation_due_at is None:
        return "not_configured"
    if now >= r.escalation_due_at:
        return "overdue"
    hours = ((r.workflow_snapshot or {}).get("escalation") or {}).get("reminderHoursBefore")
    if hours and now >= r.escalation_due_at - timedelta(hours=hours):
        return "due_soon"
    return "on_track"


def current_approver(r: LeaveRequest) -> ApproverStateOut | None:
    if r.status != "pending":
        return None
    if r.stage == "escalated" and r.recipient_kind:
        return ApproverStateOut(type=r.recipient_kind, name=r.recipient_name or r.recipient_ref or "")
    if r.approver_kind:
        return ApproverStateOut(type=r.approver_kind, name=r.approver_name or r.approver_ref or "")
    return None


async def history_out(session: AsyncSession, kind: str, request_id: uuid.UUID) -> list[WorkflowEventOut]:
    rows = (await session.scalars(select(RequestEvent).where(RequestEvent.request_kind == kind, RequestEvent.request_id == request_id).order_by(RequestEvent.created_at, RequestEvent.id))).all()
    return [WorkflowEventOut(id=str(e.id), action=e.action, at=e.created_at, by=e.created_by_name, comment=e.comment) for e in rows]


async def leave_request_out(session: AsyncSession, r: LeaveRequest, employee: Employee, departments: dict, types: dict[uuid.UUID, LeaveType] | None = None) -> LeaveRequestOut:
    leave_type = types[r.leave_type_id] if types else await session.get(LeaveType, r.leave_type_id)
    attachments = (await session.scalars(select(LeaveRequestAttachment).where(LeaveRequestAttachment.leave_request_id == r.id).order_by(LeaveRequestAttachment.created_at))).all()
    events = (await session.scalars(select(LeaveRoutingEvent).where(LeaveRoutingEvent.leave_request_id == r.id).order_by(LeaveRoutingEvent.created_at, LeaveRoutingEvent.id))).all()
    snap = r.workflow_snapshot
    approval = LeaveApprovalStateOut(
        workflow=WorkflowRefOut(id=snap["id"], name=snap["name"]) if snap else None,
        stage=r.stage, current_approver=current_approver(r),
        escalation_due_at=r.escalation_due_at if r.status == "pending" and r.escalated_at is None else None,
        escalation=escalation_status(r, datetime.now(UTC)), escalated_at=r.escalated_at,
        events=[RoutingEventOut(at=e.created_at, action=e.action, detail=e.detail) for e in events],
    )
    return LeaveRequestOut(
        id=str(r.id), employee=employee_ref(employee, departments), leave_type=type_ref(leave_type), **{"from": r.from_date.isoformat()}, to=r.to_date.isoformat(),
        portion=r.portion, days=float(r.days), reason=r.reason, status=r.status,
        attachments=[LeaveAttachmentOut(id=str(a.id), file_name=a.file_name, size_bytes=a.size_bytes) for a in attachments],
        submitted_at=r.created_at, submitted_by=r.created_by_name, reviewed_by=r.reviewed_by_name, reviewed_at=r.reviewed_at, review_comment=r.review_comment,
        history=await history_out(session, "leave", r.id), version=r.version, approval=approval,
    )
