"""HR → Approval inbox (frontend approvals.http.ts, contract E3)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.errors import ValidationFailedError
from app.core.permissions import P
from app.schemas.common import ALLOWED_PAGE_SIZES
from app.schemas.leave_schema import ApprovalInboxOut
from app.services.employee_support import caller_context
from app.services.leave.approvals_service import ApprovalsService

router = APIRouter(prefix="/hr/approvals", tags=["Approvals"])
INBOX = [Depends(require(P.APPROVALS_VIEW, P.APPROVALS_ACT, P.LEAVE_APPROVE, P.PERMISSION_REQUESTS_APPROVE, P.OVERTIME_APPROVE, P.ATTENDANCE_CORRECTIONS_APPROVE))]


@router.get("", response_model=ApprovalInboxOut, dependencies=INBOX, summary="Pending requests the caller may decide now, oldest first")
async def inbox(
    session: DbSession, principal: CurrentPrincipal, page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(alias="pageSize")] = 25,
    type_: Annotated[Literal["leave", "permission", "overtime", "attendance_correction"] | None, Query(alias="type")] = None,
):
    if page_size not in ALLOWED_PAGE_SIZES:
        raise ValidationFailedError(details=[{"field": "pageSize", "message": "Use 10, 25, 50 or 100."}])
    return await ApprovalsService(session, await caller_context(session, principal)).inbox(type_=type_, page=page, page_size=page_size)
