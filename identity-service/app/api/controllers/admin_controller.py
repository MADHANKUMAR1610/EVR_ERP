"""Administration → users, roles and the permission catalogue (frontend admin.http.ts, contracts G2 and G3)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import AppSettings, CurrentPrincipal, DbSession, Token, require
from app.core.permissions import Perm
from app.schemas.common import Page, PageParams, page_params
from app.schemas.identity_schema import NewUserIn, PasswordResetIn, PermissionModuleOut, RoleIn, RoleOut, UserAccountOut, UserActivityOut, UserIn, UserStatusIn
from app.services.admin_service import AdminService
from app.utils.ids import path_id

router = APIRouter(prefix="/admin", tags=["Users and roles"])
Params = Annotated[PageParams, Depends(page_params)]
USERS_VIEW = [Depends(require(Perm.USERS_VIEW))]
USERS_MANAGE = [Depends(require(Perm.USERS_MANAGE))]
ROLES_VIEW = [Depends(require(Perm.ROLES_VIEW))]
ROLES_MANAGE = [Depends(require(Perm.ROLES_MANAGE))]


def _svc(session, settings, principal, token) -> AdminService:
    return AdminService(session, settings, principal, token)


@router.get("/users", response_model=Page[UserAccountOut], dependencies=USERS_VIEW, summary="User accounts")
async def users(session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token, params: Params,
                status_: Annotated[Literal["active", "inactive", "invited", "locked"] | None, Query(alias="status")] = None,
                role_id: Annotated[str | None, Query(alias="roleId")] = None, department_id: Annotated[str | None, Query(alias="departmentId")] = None,
                employee_id: Annotated[str | None, Query(alias="employeeId")] = None):
    return await _svc(session, settings, principal, token).users(q=params.q, status=status_, role_id=role_id, department_id=department_id, employee_id=employee_id,
                                                                  sort=params.sort, page=params.page, page_size=params.page_size)


@router.get("/users/{user_id}", response_model=UserAccountOut, dependencies=USERS_VIEW, summary="One account")
async def user(user_id: str, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).user(path_id(user_id))


@router.get("/users/{user_id}/activity", response_model=list[UserActivityOut], dependencies=USERS_VIEW, summary="Account history")
async def user_activity(user_id: str, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).activity(path_id(user_id))


@router.post("/users", response_model=UserAccountOut, status_code=status.HTTP_201_CREATED, dependencies=USERS_MANAGE, summary="Create an account with an HR-set first password")
async def create_user(data: NewUserIn, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).create_user(data)


@router.put("/users/{user_id}", response_model=UserAccountOut, dependencies=USERS_MANAGE, summary="Update account details (never a password)")
async def update_user(user_id: str, data: UserIn, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).update_user(path_id(user_id), data)


@router.post("/users/{user_id}/status", response_model=UserAccountOut, dependencies=USERS_MANAGE, summary="Activate or deactivate (deactivation ends sessions)")
async def set_status(user_id: str, data: UserStatusIn, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).set_status(path_id(user_id), data)


@router.post("/users/{user_id}/password", response_model=UserAccountOut, dependencies=USERS_MANAGE, summary="HR resets the password (ends sessions, unlocks)")
async def reset_password(user_id: str, data: PasswordResetIn, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).reset_password(path_id(user_id), data)


@router.get("/permissions", response_model=list[PermissionModuleOut], dependencies=ROLES_VIEW, summary="Permission catalogue (matrix rows)")
async def permissions(session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return _svc(session, settings, principal, token).permission_catalogue()


@router.get("/roles", response_model=list[RoleOut], dependencies=ROLES_VIEW, summary="Roles with user counts")
async def roles(session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).roles()


@router.get("/roles/{role_id}", response_model=RoleOut, dependencies=ROLES_VIEW, summary="One role")
async def role(role_id: str, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).role(path_id(role_id))


@router.get("/roles/{role_id}/users", response_model=list[UserAccountOut], dependencies=[*ROLES_VIEW, *USERS_VIEW], summary="Accounts holding the role")
async def role_users(role_id: str, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).role_users(path_id(role_id))


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED, dependencies=ROLES_MANAGE, summary="Create a role")
async def create_role(data: RoleIn, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).save_role(None, data)


@router.put("/roles/{role_id}", response_model=RoleOut, dependencies=ROLES_MANAGE, summary="Update a role (system roles keep their name)")
async def update_role(role_id: str, data: RoleIn, session: DbSession, settings: AppSettings, principal: CurrentPrincipal, token: Token):
    return await _svc(session, settings, principal, token).save_role(path_id(role_id), data)
