"""Builds the CorrectionRequest response (shared by corrections, the day detail and the summary)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attendance_model import AttendanceCorrection, AttendanceCorrectionEvent
from app.models.employee_model import Employee
from app.schemas.attendance_schema import CorrectionOut, EmployeeRefOut, PunchPairOut, WorkflowEventOut
from app.schemas.employee_schema import NamedRefOut

# The frontend's WorkflowEvent has no "escalated" action; escalation is shown as a comment.
PUBLIC_ACTION = {"escalated": "commented"}


async def correction_out(session: AsyncSession, c: AttendanceCorrection, employee: Employee, departments: dict) -> CorrectionOut:
    events = (await session.scalars(select(AttendanceCorrectionEvent).where(AttendanceCorrectionEvent.correction_id == c.id).order_by(AttendanceCorrectionEvent.created_at, AttendanceCorrectionEvent.id))).all()
    history = []
    for ev in events:
        comment = ev.comment
        if ev.action == "escalated":
            comment = f"Escalated: {comment}" if comment else "Escalated"
        elif ev.step_name and ev.action in ("approved", "rejected"):
            comment = f"{ev.step_name}: {comment}" if comment else ev.step_name
        history.append(WorkflowEventOut(id=str(ev.id), action=PUBLIC_ACTION.get(ev.action, ev.action), at=ev.created_at, by=ev.created_by_name, comment=comment))
    return CorrectionOut(
        id=str(c.id),
        employee=EmployeeRefOut(id=str(employee.id), employee_code=employee.employee_code, full_name=employee.full_name, department=NamedRefOut(id=str(employee.department_id), name=departments.get(employee.department_id, ""))),
        date=c.date.isoformat(),
        original=PunchPairOut(**{"in": c.original_in, "out": c.original_out}),
        requested=PunchPairOut(**{"in": c.requested_in, "out": c.requested_out}),
        reason=c.reason, status=c.status, submitted_at=c.created_at, submitted_by=c.created_by_name,
        reviewed_by=c.reviewed_by_name, reviewed_at=c.reviewed_at, review_comment=c.review_comment, history=history, version=c.version,
    )
