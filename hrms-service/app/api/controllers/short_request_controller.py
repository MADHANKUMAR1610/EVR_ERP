"""HR → Permission (short absence) and overtime requests (frontend leave.http.ts, Part B of Module 6)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.permissions import P
from app.schemas.attendance_schema import DecisionIn
from app.schemas.common import Page, PageParams, page_params
from app.schemas.leave_schema import OvertimeIn, OvertimeRequestOut, PermissionIn, PermissionRequestOut
from app.services.employee_support import caller_context
from app.services.leave.short_request_service import OvertimeRequestService, PermissionRequestService
from app.utils.ids import path_id

permission_router = APIRouter(prefix="/hr/permission-requests", tags=["Permission requests"])
overtime_router = APIRouter(prefix="/hr/overtime-requests", tags=["Overtime requests"])
Params = Annotated[PageParams, Depends(page_params)]
Status = Annotated[Literal["pending", "approved", "rejected", "cancelled"] | None, Query(alias="status")]
Dept = Annotated[str | None, Query(alias="departmentId")]
SUBMIT = [Depends(require(P.SELF_SUBMIT_REQUESTS, P.LEAVE_APPLY_ON_BEHALF))]


async def _permission(session, principal) -> PermissionRequestService:
    return PermissionRequestService(session, await caller_context(session, principal))


async def _overtime(session, principal) -> OvertimeRequestService:
    return OvertimeRequestService(session, await caller_context(session, principal))


@permission_router.get("", response_model=Page[PermissionRequestOut], summary="Permission requests (HR in scope, own, or direct reports)")
async def list_permission(session: DbSession, principal: CurrentPrincipal, params: Params, scope: Annotated[str | None, Query()] = None, status_: Status = None, department_id: Dept = None):
    return await (await _permission(session, principal)).list(params, scope=scope, status=status_, department_id=department_id)


@permission_router.get("/{request_id}", response_model=PermissionRequestOut)
async def get_permission(request_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _permission(session, principal)).get(path_id(request_id))


@permission_router.post("", response_model=PermissionRequestOut, status_code=status.HTTP_201_CREATED, dependencies=SUBMIT)
async def submit_permission(data: PermissionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _permission(session, principal)).submit(data)


@permission_router.post("/{request_id}/decision", response_model=PermissionRequestOut, dependencies=[Depends(require(P.PERMISSION_REQUESTS_APPROVE, P.APPROVALS_ACT))])
async def decide_permission(request_id: str, data: DecisionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _permission(session, principal)).decide(path_id(request_id), data)


@overtime_router.get("", response_model=Page[OvertimeRequestOut], summary="Overtime requests (HR in scope, own, or direct reports)")
async def list_overtime(session: DbSession, principal: CurrentPrincipal, params: Params, scope: Annotated[str | None, Query()] = None, status_: Status = None, department_id: Dept = None):
    return await (await _overtime(session, principal)).list(params, scope=scope, status=status_, department_id=department_id)


@overtime_router.get("/{request_id}", response_model=OvertimeRequestOut)
async def get_overtime(request_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _overtime(session, principal)).get(path_id(request_id))


@overtime_router.post("", response_model=OvertimeRequestOut, status_code=status.HTTP_201_CREATED, dependencies=SUBMIT)
async def submit_overtime(data: OvertimeIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _overtime(session, principal)).submit(data)


@overtime_router.post("/{request_id}/decision", response_model=OvertimeRequestOut, dependencies=[Depends(require(P.OVERTIME_APPROVE, P.APPROVALS_ACT))])
async def decide_overtime(request_id: str, data: DecisionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _overtime(session, principal)).decide(path_id(request_id), data)
