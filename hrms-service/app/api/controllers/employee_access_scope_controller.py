"""/hr/setup/employee-access-scopes: organizational scope per Identity role (decision Q12)."""

from fastapi import APIRouter, Depends, status

from app.api.dependencies import DbSession, require
from app.core.permissions import P
from app.schemas.employee_schema import AccessScopeIn, AccessScopeOut
from app.services.employee_access_scope_service import EmployeeAccessScopeService
from app.utils.ids import path_id

router = APIRouter(prefix="/hr/setup/employee-access-scopes", tags=["HR setup"])


@router.get("", response_model=list[AccessScopeOut], dependencies=[Depends(require(P.SETTINGS_VIEW, P.SETTINGS_MANAGE))])
async def list_scopes(session: DbSession):
    return await EmployeeAccessScopeService(session).list()


@router.post("", response_model=AccessScopeOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(P.SETTINGS_MANAGE))])
async def create_scope(data: AccessScopeIn, session: DbSession):
    return await EmployeeAccessScopeService(session).create(data)


@router.put("/{scope_id}", response_model=AccessScopeOut, dependencies=[Depends(require(P.SETTINGS_MANAGE))])
async def update_scope(scope_id: str, data: AccessScopeIn, session: DbSession):
    return await EmployeeAccessScopeService(session).update(path_id(scope_id), data)
