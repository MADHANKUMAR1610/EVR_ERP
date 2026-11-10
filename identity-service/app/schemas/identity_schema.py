"""Identity (frontend auth/types.ts and admin.service.ts, contracts B1, G2, G3). Field names match the frontend exactly.
No schema ever carries a password hash; passwords appear only in request bodies."""

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel, ResponseModel, UtcDateTime

UserStatus = Literal["active", "inactive", "invited", "locked"]


# --- Session (B1) --------------------------------------------------------------------------------------


class LoginIn(CamelModel):
    username: str = Field(max_length=254)
    password: str = Field(max_length=256)


class AuthUserOut(ResponseModel):
    id: str
    username: str
    display_name: str
    email: str | None = None
    roles: list[str]
    permissions: list[str]
    # Additions the frontend can ignore: the linked employee and the forced password change (G-Q5).
    employee_id: str | None = None
    must_change_password: bool = False


class AuthSessionOut(ResponseModel):
    user: AuthUserOut
    expires_at: UtcDateTime | None = None


class PasswordChangeIn(CamelModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


# --- Users (G2) ------------------------------------------------------------------------------------------


class NamedRefOut(ResponseModel):
    id: str
    name: str


class EmployeeLinkOut(ResponseModel):
    id: str
    employee_code: str
    full_name: str


class ManagerOut(ResponseModel):
    id: str
    full_name: str


class UserAccountOut(ResponseModel):
    id: str
    username: str
    display_name: str
    email: str
    status: UserStatus
    roles: list[NamedRefOut]
    department: NamedRefOut | None
    employee: EmployeeLinkOut | None
    reporting_manager: ManagerOut | None
    last_login_at: UtcDateTime | None
    password_set_at: UtcDateTime | None
    must_change_password: bool
    created_at: UtcDateTime
    version: int


class UserIn(CamelModel):
    username: str = Field(max_length=60)
    display_name: str = Field(max_length=120)
    email: str = Field(max_length=254)
    role_ids: list[str] = Field(default_factory=list, max_length=50)
    department_id: str | None = Field(default=None, max_length=60)
    employee_id: str | None = Field(default=None, max_length=60)
    version: int | None = None


class NewUserIn(UserIn):
    password: str = Field(max_length=256)
    must_change_password: bool


class UserStatusIn(CamelModel):
    status: Literal["active", "inactive"]
    reason: str = Field(max_length=500)
    version: int


class PasswordResetIn(CamelModel):
    password: str = Field(max_length=256)
    must_change_password: bool
    version: int


class UserActivityOut(ResponseModel):
    id: str
    at: UtcDateTime
    action: str
    summary: str
    by: str


# --- Roles and permissions (G3) --------------------------------------------------------------------------


class PermissionActionsOut(ResponseModel):
    view: str | None = None
    create: str | None = None
    edit: str | None = None
    delete: str | None = None
    approve: str | None = None
    reject: str | None = None
    export: str | None = None
    configure: str | None = None


class PermissionExtraOut(ResponseModel):
    code: str
    label: str


class PermissionModuleOut(ResponseModel):
    id: str
    group: str
    label: str
    actions: dict[str, str]
    extra: list[PermissionExtraOut]


class RoleOut(ResponseModel):
    id: str
    name: str
    description: str
    permissions: list[str]
    system: bool
    active: bool
    user_count: int
    grants_administration: bool
    updated_at: UtcDateTime
    updated_by: str
    version: int


class RoleIn(CamelModel):
    name: str = Field(max_length=80)
    description: str = Field(default="", max_length=1000)
    permissions: list[str] = Field(default_factory=list, max_length=500)
    active: bool = True
    version: int | None = None


# --- Internal (service-to-service; hrms-service docs/AUTH_INTEGRATION.md section 4) -------------------------


class ServiceTokenIn(CamelModel):
    client_id: str = Field(max_length=60)
    client_secret: str = Field(max_length=256)


class ServiceTokenOut(ResponseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int


class SessionStateOut(ResponseModel):
    active: bool


class InternalUserOut(ResponseModel):
    id: str
    name: str
    employee_id: str | None
    active: bool
    role_ids: list[str]


class InternalRoleOut(ResponseModel):
    id: str
    name: str
