"""HR → Leave (frontend leave.http.ts, contracts E2 and H3)."""

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response, status
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.config import get_settings
from app.core.errors import BadRequestError, LengthRequiredError, PayloadTooLargeError
from app.core.permissions import P
from app.schemas.attendance_schema import DecisionIn
from app.schemas.common import Page, PageParams, page_params
from app.schemas.leave_schema import (
    CancellationIn,
    CommentIn,
    EmployeeBalancesOut,
    HolidayOut,
    LeaveEstimateOut,
    LeavePolicyOut,
    LeaveRequestOut,
    LeaveSummaryOut,
    LeaveTypeOut,
    LeaveWorkflowIn,
    LeaveWorkflowOptionsOut,
    LeaveWorkflowOut,
)
from app.services.employee_support import caller_context
from app.services.leave.balance_service import BalanceService
from app.services.leave.request_service import ApplicationInput, LeaveRequestService, Upload
from app.services.leave.setup_service import LeaveSetupService
from app.services.leave.workflow_service import LeaveWorkflowService
from app.utils.ids import path_id

lookups_router = APIRouter(prefix="/hr", tags=["Leave"])
router = APIRouter(prefix="/hr/leave", tags=["Leave"])
Params = Annotated[PageParams, Depends(page_params)]
FORM_OVERHEAD = 64 * 1024

APPLY_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["leaveTypeId", "from", "to", "portion", "reason"],
                    "properties": {
                        "employeeId": {"type": "string", "description": "Omitted for the signed-in employee's own request"},
                        "leaveTypeId": {"type": "string"},
                        "from": {"type": "string", "format": "date"},
                        "to": {"type": "string", "format": "date"},
                        "portion": {"type": "string", "enum": ["full", "first_half", "second_half"]},
                        "reason": {"type": "string", "minLength": 3, "maxLength": 500},
                        "attachments": {"type": "array", "items": {"type": "string", "format": "binary"}},
                    },
                }
            }
        },
    }
}


async def _requests(session, principal) -> LeaveRequestService:
    return LeaveRequestService(session, await caller_context(session, principal))


# ---- Lookups (any signed-in user) -------------------------------------------------------------------------


@lookups_router.get("/leave-types", response_model=list[LeaveTypeOut], summary="Leave types (any signed-in user)")
async def leave_types(session: DbSession, principal: CurrentPrincipal):
    return await LeaveSetupService(session, principal).leave_types()


@lookups_router.get("/holidays", response_model=list[HolidayOut], summary="Holidays of a year: the caller's applicable holidays, or all for HR")
async def holidays(session: DbSession, principal: CurrentPrincipal, year: Annotated[int | None, Query(ge=2000, le=2100)] = None):
    return await LeaveSetupService(session, principal).holidays_for_caller(year)


@lookups_router.get("/me/leave/balances", response_model=EmployeeBalancesOut, summary="The signed-in employee's balances")
async def my_balances(session: DbSession, principal: CurrentPrincipal, year: Annotated[int | None, Query(ge=2000, le=2100)] = None):
    return await BalanceService(session, await caller_context(session, principal)).mine(year)


@router.get("/policies", response_model=list[LeavePolicyOut], dependencies=[Depends(require(P.LEAVE_POLICIES_VIEW, P.LEAVE_POLICIES_MANAGE))], summary="Leave policies (read-only)")
async def policies(session: DbSession):
    return await LeaveSetupService(session).policies()


@router.get("/summary", response_model=LeaveSummaryOut, dependencies=[Depends(require(P.LEAVE_VIEW))], summary="Leave dashboard")
async def summary(session: DbSession, principal: CurrentPrincipal):
    return await (await _requests(session, principal)).summary()


@router.get("/balances", response_model=Page[EmployeeBalancesOut], dependencies=[Depends(require(P.LEAVE_BALANCES_VIEW))], summary="Balances per employee (organizational scope)")
async def balances(session: DbSession, principal: CurrentPrincipal, params: Params, year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
                   department_id: Annotated[str | None, Query(alias="departmentId")] = None):
    return await BalanceService(session, await caller_context(session, principal)).list(year=year, department_id=department_id, q=params.q, page=params.page, page_size=params.page_size)


# ---- Requests ------------------------------------------------------------------------------------------------


@router.get("/requests", response_model=Page[LeaveRequestOut], summary="Leave requests (HR in scope, own, or assigned to the caller)")
async def list_requests(
    session: DbSession, principal: CurrentPrincipal, params: Params, scope: Annotated[str | None, Query()] = None,
    status_: Annotated[Literal["pending", "approved", "rejected", "cancelled"] | None, Query(alias="status")] = None,
    leave_type_id: Annotated[str | None, Query(alias="leaveTypeId")] = None, department_id: Annotated[str | None, Query(alias="departmentId")] = None,
    from_: Annotated[str | None, Query(alias="from")] = None, to: Annotated[str | None, Query()] = None,
    escalated: Annotated[bool | None, Query()] = None, awaiting_me: Annotated[bool | None, Query(alias="awaitingMe")] = None,
):
    return await (await _requests(session, principal)).list(params, scope=scope, status=status_, leave_type_id=leave_type_id, department_id=department_id, start=from_, end=to,
                                                           escalated=escalated, awaiting_me=awaiting_me)


@router.get("/requests/estimate", response_model=LeaveEstimateOut, dependencies=[Depends(require(P.SELF_SUBMIT_REQUESTS, P.LEAVE_APPLY_ON_BEHALF))], summary="Preview of an application")
async def estimate(
    session: DbSession, principal: CurrentPrincipal, employee_id: Annotated[str | None, Query(alias="employeeId")] = None,
    leave_type_id: Annotated[str | None, Query(alias="leaveTypeId")] = None, from_: Annotated[str | None, Query(alias="from")] = None,
    to: Annotated[str | None, Query()] = None, portion: Annotated[str | None, Query()] = "full",
):
    data = ApplicationInput(employee_id=employee_id, leave_type_id=leave_type_id, from_=from_, to=to, portion=portion)
    return await (await _requests(session, principal)).estimate(data)


@router.get("/requests/{request_id}", response_model=LeaveRequestOut, summary="One leave request")
async def get_request(request_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _requests(session, principal)).get(path_id(request_id))


@router.post("/requests", response_model=LeaveRequestOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(P.SELF_SUBMIT_REQUESTS, P.LEAVE_APPLY_ON_BEHALF))],
             summary="Apply for leave (multipart/form-data, attachments optional)", openapi_extra=APPLY_SCHEMA)
async def apply(request: Request, session: DbSession, principal: CurrentPrincipal):
    settings = get_settings()
    limit = settings.leave_attachment_max_bytes
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise LengthRequiredError()
    if int(length) > limit * settings.leave_max_attachments + FORM_OVERHEAD:
        raise PayloadTooLargeError(details=[{"field": "attachments", "message": f"Attach at most {settings.leave_max_attachments} files of up to {limit // (1024 * 1024)} MB each."}])
    try:
        form = await request.form(max_files=settings.leave_max_attachments + 1, max_fields=20)
    except StarletteHTTPException:
        raise BadRequestError("Send the application as multipart/form-data.") from None
    try:
        def text(key: str) -> str | None:
            value = form.get(key)
            return value if isinstance(value, str) else None

        uploads = []
        for item in form.getlist("attachments"):
            if isinstance(item, UploadFile):
                uploads.append(Upload(file_name=item.filename, content=await item.read(limit + 1)))
        data = ApplicationInput(employee_id=text("employeeId") or None, leave_type_id=text("leaveTypeId"), from_=text("from"), to=text("to"), portion=text("portion") or "full",
                                reason=text("reason"), attachments=uploads)
    finally:
        await form.close()
    return await (await _requests(session, principal)).apply(data)


@router.post("/requests/{request_id}/decision", response_model=LeaveRequestOut, dependencies=[Depends(require(P.LEAVE_APPROVE, P.APPROVALS_ACT))], summary="Approve or reject")
async def decide(request_id: str, data: DecisionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _requests(session, principal)).decide(path_id(request_id), data)


@router.post("/requests/{request_id}/cancellation", response_model=LeaveRequestOut, summary="Cancel (pending, or approved and not started)")
async def cancel(request_id: str, data: CancellationIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _requests(session, principal)).cancel(path_id(request_id), data)


@router.post("/requests/{request_id}/comments", response_model=LeaveRequestOut, summary="Review comment without a decision")
async def comment(request_id: str, data: CommentIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _requests(session, principal)).comment(path_id(request_id), data)


@router.get("/requests/{request_id}/attachments/{attachment_id}/content", summary="Download an attachment (same access as the request)",
            responses={200: {"content": {"application/pdf": {}, "image/jpeg": {}, "image/png": {}}, "description": "The file"}})
async def attachment(request_id: str, attachment_id: str, session: DbSession, principal: CurrentPrincipal) -> Response:
    content, a = await (await _requests(session, principal)).attachment(path_id(request_id), path_id(attachment_id))
    ascii_name = a.file_name.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
    return Response(content=content, media_type=a.content_type, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(a.file_name)}",
        "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store, private", "Content-Security-Policy": "default-src 'none'; sandbox",
    })


# ---- Approval workflows (H3) ------------------------------------------------------------------------------------

WF_VIEW = [Depends(require(P.LEAVE_POLICIES_VIEW, P.LEAVE_WORKFLOWS_MANAGE))]
WF_MANAGE = [Depends(require(P.LEAVE_WORKFLOWS_MANAGE))]


@router.get("/approval-workflows", response_model=list[LeaveWorkflowOut], dependencies=WF_VIEW, summary="Leave approval workflows")
async def workflows(session: DbSession):
    return await LeaveWorkflowService(session).list()


@router.get("/approval-workflows/options", response_model=LeaveWorkflowOptionsOut, dependencies=WF_VIEW, summary="Approver options and company working days")
async def workflow_options(session: DbSession):
    return await LeaveWorkflowService(session).options()


@router.post("/approval-workflows", response_model=LeaveWorkflowOut, status_code=status.HTTP_201_CREATED, dependencies=WF_MANAGE)
async def create_workflow(data: LeaveWorkflowIn, session: DbSession):
    return await LeaveWorkflowService(session).save(None, data)


@router.put("/approval-workflows/{workflow_id}", response_model=LeaveWorkflowOut, dependencies=WF_MANAGE)
async def update_workflow(workflow_id: str, data: LeaveWorkflowIn, session: DbSession):
    return await LeaveWorkflowService(session).save(path_id(workflow_id), data)
