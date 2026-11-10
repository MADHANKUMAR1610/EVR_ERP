"""Users, roles and the permission catalogue (contract G2, G3).

- HR sets the first password and resets forgotten ones; only the Argon2id hash is stored, and no response,
  log or audit entry ever contains a password.
- Username and email are unique (case-insensitive); an employee is linked to at most one account.
- Safeguards (409): no one deactivates their own account; no change may leave zero active users holding
  admin:roles.manage through an active role.
- Deactivating an account, or resetting its password, ends its sessions. A reset unlocks the account.
- Built-in (system) roles cannot be renamed. There is no delete: roles are deactivated.
- Employee, department and manager names are read from HRMS with the caller's session (snapshot on save).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import Principal
from app.core.errors import BadRequestError, ConflictError, NotFoundError, ValidationFailedError
from app.core.passwords import hash_password, policy_problems
from app.core.permissions import ROLES_MANAGE, catalogue, has_permission
from app.models.identity_model import Role, UserAccount, UserAccountEvent, UserSession
from app.repositories.base_repository import PageResult
from app.schemas.common import Page
from app.schemas.identity_schema import (
    EmployeeLinkOut,
    ManagerOut,
    NamedRefOut,
    NewUserIn,
    PasswordResetIn,
    PermissionModuleOut,
    RoleIn,
    RoleOut,
    UserAccountOut,
    UserActivityOut,
    UserIn,
    UserStatusIn,
)
from app.services.audit_service import AuditService, diff
from app.services.hrms_client import HrmsClient
from app.utils.validation import FieldErrors, ensure_version

MODULE = "Identity"
USERNAME = re.compile(r"^[A-Za-z0-9._@-]{3,60}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CODE = re.compile(r"^(\*|[a-z0-9.\-]+:(\*|[a-z0-9.\-]+))$")
USER_SORTS = {"displayName": func.lower(UserAccount.display_name), "username": func.lower(UserAccount.username), "status": UserAccount.status,
              "lastLoginAt": UserAccount.last_login_at, "createdAt": UserAccount.created_at}


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


class AdminService:
    def __init__(self, session: AsyncSession, settings: Settings, caller: Principal, token: str | None):
        self.session = session
        self.s = settings
        self.caller = caller
        self.audit = AuditService(session)
        self.hrms = HrmsClient(token)

    # ---- Output --------------------------------------------------------------------------------------------

    async def _roles(self) -> dict[uuid.UUID, Role]:
        return {r.id: r for r in (await self.session.scalars(select(Role))).all()}

    def _user_out(self, u: UserAccount, roles: dict[uuid.UUID, Role]) -> UserAccountOut:
        return UserAccountOut(
            id=str(u.id), username=u.username, display_name=u.display_name, email=u.email, status=u.status,
            roles=[NamedRefOut(id=str(roles[r].id), name=roles[r].name) for r in u.role_ids if r in roles],
            department=NamedRefOut(id=u.department_id, name=u.department_name or "") if u.department_id else None,
            employee=EmployeeLinkOut(id=u.employee_id, employee_code=u.employee_code or "", full_name=u.employee_name or "") if u.employee_id else None,
            reporting_manager=ManagerOut(id=u.manager_id, full_name=u.manager_name or "") if u.manager_id else None,
            last_login_at=u.last_login_at, password_set_at=u.password_set_at, must_change_password=u.must_change_password, created_at=u.created_at, version=u.version,
        )

    def _event(self, user: UserAccount, action: str, summary: str) -> None:
        self.session.add(UserAccountEvent(user_id=user.id, action=action, summary=summary))

    # ---- Safeguard ------------------------------------------------------------------------------------------

    async def _ensure_an_administrator(self) -> None:
        """After the pending change (flushed), at least one active user must hold admin:roles.manage through an active role."""
        await self.session.flush()
        admin_roles = [r.id for r in (await self.session.scalars(select(Role).where(Role.active.is_(True)))).all() if has_permission(r.permissions, ROLES_MANAGE)]
        if admin_roles:
            holders = await self.session.scalar(select(func.count()).select_from(UserAccount).where(UserAccount.status.in_(("active", "invited", "locked")), UserAccount.role_ids.overlap(admin_roles)))
            if holders:
                return
        await self.session.rollback()
        raise ConflictError("This change would leave no active user who can manage roles. Give another active user an administrator role first.")

    # ---- Users ------------------------------------------------------------------------------------------------

    async def users(self, *, q, status, role_id, department_id, employee_id, sort, page: int, page_size: int) -> Page:
        stmt = select(UserAccount)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(UserAccount.display_name).like(like), func.lower(UserAccount.username).like(like), func.lower(UserAccount.email).like(like),
                                  func.lower(UserAccount.employee_code).like(like)))
        if status:
            stmt = stmt.where(UserAccount.status == status)
        if role_id:
            rid = _uuid(role_id)
            stmt = stmt.where(UserAccount.role_ids.any(rid)) if rid else stmt.where(false())
        if department_id:
            stmt = stmt.where(UserAccount.department_id == department_id)
        if employee_id:
            stmt = stmt.where(UserAccount.employee_id == employee_id)
        name, _, direction = (sort or "displayName:asc").partition(":")
        if name not in USER_SORTS or direction not in ("", "asc", "desc"):
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": f"Use {', '.join(USER_SORTS)} with :asc or :desc."}])
        col = USER_SORTS[name]
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = list((await self.session.scalars(stmt.order_by(col.desc().nulls_last() if direction == "desc" else col.asc().nulls_last(), UserAccount.id).limit(page_size).offset((page - 1) * page_size))).all())
        roles = await self._roles()
        return Page.build(PageResult(rows, page, page_size, total), [self._user_out(u, roles) for u in rows])

    async def _user(self, user_id: uuid.UUID, *, for_update: bool = False) -> UserAccount:
        stmt = select(UserAccount).where(UserAccount.id == user_id)
        u = await self.session.scalar(stmt.with_for_update() if for_update else stmt)
        if u is None:
            raise NotFoundError()
        return u

    async def user(self, user_id: uuid.UUID) -> UserAccountOut:
        return self._user_out(await self._user(user_id), await self._roles())

    async def activity(self, user_id: uuid.UUID) -> list[UserActivityOut]:
        await self._user(user_id)
        rows = (await self.session.scalars(select(UserAccountEvent).where(UserAccountEvent.user_id == user_id).order_by(UserAccountEvent.created_at.desc(), UserAccountEvent.id.desc()).limit(200))).all()
        return [UserActivityOut(id=str(e.id), at=e.created_at, action=e.action, summary=e.summary, by=e.created_by_name) for e in rows]

    async def _validate(self, data: UserIn, existing: UserAccount | None) -> tuple[FieldErrors, dict]:
        err = FieldErrors()
        username, email, name = data.username.strip(), data.email.strip(), data.display_name.strip()
        if not USERNAME.match(username):
            err.add("username", "Use 3-60 letters, digits, '.', '_', '-' or '@'.")
        if not EMAIL.match(email):
            err.add("email", "Enter a valid email address.")
        if not 2 <= len(name) <= 120:
            err.add("displayName", "Enter a name of 2-120 characters.")
        other = existing.id if existing else uuid.uuid4()
        if not err.has("username") and await self.session.scalar(select(UserAccount.id).where(func.lower(UserAccount.username) == username.lower(), UserAccount.id != other)):
            err.add("username", "Another account already uses this username.")
        if not err.has("email") and await self.session.scalar(select(UserAccount.id).where(func.lower(UserAccount.email) == email.lower(), UserAccount.id != other)):
            err.add("email", "Another account already uses this email address.")
        roles = await self._roles()
        role_ids = [_uuid(r) for r in data.role_ids]
        if any(r is None or r not in roles for r in role_ids):
            err.add("roleIds", "Choose existing roles.")
        elif len(set(role_ids)) != len(role_ids):
            err.add("roleIds", "Each role can be chosen once.")
        elif any(not roles[r].active for r in role_ids if existing is None or r not in existing.role_ids):
            err.add("roleIds", "Inactive roles cannot be assigned.")
        values = {"username": username, "email": email, "display_name": name, "role_ids": [r for r in role_ids if r],
                  "employee_id": None, "employee_code": None, "employee_name": None, "manager_id": None, "manager_name": None,
                  "department_id": data.department_id or None, "department_name": None}
        if data.employee_id:
            if await self.session.scalar(select(UserAccount.id).where(UserAccount.employee_id == data.employee_id, UserAccount.id != other)):
                err.add("employeeId", "This employee is already linked to another account.")
            elif self.hrms.enabled:
                info = await self.hrms.employee(data.employee_id)
                if info is None:
                    err.add("employeeId", "Choose an existing employee you can see in HRMS.")
                else:
                    values.update(employee_id=info.id, employee_code=info.code, employee_name=info.name, manager_id=info.manager_id, manager_name=info.manager_name)
                    if not data.department_id:
                        values.update(department_id=info.department_id, department_name=info.department_name)
                    elif data.department_id == info.department_id:
                        values["department_name"] = info.department_name
            else:
                values["employee_id"] = data.employee_id
        if values["department_id"] and values["department_name"] is None and self.hrms.enabled:
            dept = await self.hrms.department_name(values["department_id"])
            if dept is None:
                err.add("departmentId", "Choose an existing department.")
            values["department_name"] = dept
        return err, values

    async def create_user(self, data: NewUserIn) -> UserAccountOut:
        err, values = await self._validate(data, None)
        for p in policy_problems(data.password, values["username"], self.s):
            err.add("password", p)
        err.raise_if_any()
        now = datetime.now(UTC)
        u = UserAccount(**values, status="active", password_hash=hash_password(data.password), password_set_at=now, must_change_password=data.must_change_password)
        self.session.add(u)
        await self.session.flush()
        self._event(u, "created", "Account created; HR set the first password")
        self.audit.record(module=MODULE, action="user.created", summary=f"Account {u.username} created", entity_type="user_account", entity_id=u.id, entity_label=u.display_name,
                          changes=diff({}, {"username": u.username, "email": u.email, "displayName": u.display_name, "roles": ", ".join(sorted(str(r) for r in u.role_ids)), "password": "set"}))
        await self.session.commit()
        return self._user_out(u, await self._roles())

    async def update_user(self, user_id: uuid.UUID, data: UserIn) -> UserAccountOut:
        u = await self._user(user_id, for_update=True)
        ensure_version(u, data.version)
        err, values = await self._validate(data, u)
        err.raise_if_any()
        before = {"username": u.username, "email": u.email, "displayName": u.display_name, "roles": sorted(str(r) for r in u.role_ids), "employee": u.employee_id, "department": u.department_id}
        for k, v in values.items():
            setattr(u, k, v)
        after = {"username": u.username, "email": u.email, "displayName": u.display_name, "roles": sorted(str(r) for r in u.role_ids), "employee": u.employee_id, "department": u.department_id}
        await self._ensure_an_administrator()
        self._event(u, "updated", "Account details updated")
        self.audit.record(module=MODULE, action="user.updated", summary=f"Account {u.username} updated", entity_type="user_account", entity_id=u.id, entity_label=u.display_name, changes=diff(before, after))
        await self.session.commit()
        await self.session.refresh(u)
        return self._user_out(u, await self._roles())

    async def _end_sessions(self, u: UserAccount, reason: str) -> None:
        await self.session.execute(update(UserSession).where(UserSession.user_id == u.id, UserSession.revoked_at.is_(None)).values(revoked_at=datetime.now(UTC), revoked_reason=reason))

    async def set_status(self, user_id: uuid.UUID, data: UserStatusIn) -> UserAccountOut:
        u = await self._user(user_id, for_update=True)
        ensure_version(u, data.version)
        reason = data.reason.strip()
        if len(reason) < 3:
            raise ValidationFailedError(details=[{"field": "reason", "message": "Enter the reason for the change."}])
        if data.status == "inactive" and str(u.id) == self.caller.user_id:
            raise ConflictError("You cannot deactivate your own account.")
        before = u.status
        if data.status == "inactive":
            u.status = "inactive"
            await self._end_sessions(u, "deactivated")
        else:
            u.status, u.failed_attempts, u.locked_until = "active", 0, None
        await self._ensure_an_administrator()
        self._event(u, "status_changed", f"Status {before} → {u.status}: {reason}")
        self.audit.record(module=MODULE, action="user.status_changed", summary=f"Account {u.username}: {before} → {u.status} ({reason})", entity_type="user_account", entity_id=u.id,
                          entity_label=u.display_name, changes=diff({"status": before}, {"status": u.status}))
        await self.session.commit()
        await self.session.refresh(u)
        return self._user_out(u, await self._roles())

    async def reset_password(self, user_id: uuid.UUID, data: PasswordResetIn) -> UserAccountOut:
        u = await self._user(user_id, for_update=True)
        ensure_version(u, data.version)
        problems = policy_problems(data.password, u.username, self.s)
        if problems:
            raise ValidationFailedError(details=[{"field": "password", "message": " ".join(problems)}])
        u.password_hash, u.password_set_at, u.must_change_password = hash_password(data.password), datetime.now(UTC), data.must_change_password
        u.failed_attempts, u.locked_until = 0, None
        if u.status in ("invited", "locked"):
            u.status = "active"
        await self._end_sessions(u, "password_reset")
        self._event(u, "password_reset", "HR reset the password" + ("; it must be changed at the next sign-in" if data.must_change_password else ""))
        self.audit.record(module=MODULE, action="user.password_reset", summary=f"Password of {u.username} reset by HR", entity_type="user_account", entity_id=u.id, entity_label=u.display_name,
                          changes=[{"field": "password", "before": "••••", "after": "••••"}])
        await self.session.commit()
        await self.session.refresh(u)
        return self._user_out(u, await self._roles())

    # ---- Roles -----------------------------------------------------------------------------------------------------

    def permission_catalogue(self) -> list[PermissionModuleOut]:
        return [PermissionModuleOut(**row) for row in catalogue()]

    async def _counts(self) -> dict[uuid.UUID, int]:
        rows = (await self.session.execute(select(func.unnest(UserAccount.role_ids).label("rid"), func.count()).group_by("rid"))).all()
        return {rid: n for rid, n in rows}

    def _role_out(self, r: Role, counts: dict) -> RoleOut:
        return RoleOut(id=str(r.id), name=r.name, description=r.description, permissions=list(r.permissions), system=r.system, active=r.active, user_count=counts.get(r.id, 0),
                       grants_administration=has_permission(r.permissions, ROLES_MANAGE), updated_at=r.updated_at, updated_by=r.updated_by_name, version=r.version)

    async def roles(self) -> list[RoleOut]:
        counts = await self._counts()
        return [self._role_out(r, counts) for r in (await self.session.scalars(select(Role).order_by(func.lower(Role.name)))).all()]

    async def _role(self, role_id: uuid.UUID, *, for_update: bool = False) -> Role:
        stmt = select(Role).where(Role.id == role_id)
        r = await self.session.scalar(stmt.with_for_update() if for_update else stmt)
        if r is None:
            raise NotFoundError()
        return r

    async def role(self, role_id: uuid.UUID) -> RoleOut:
        return self._role_out(await self._role(role_id), await self._counts())

    async def role_users(self, role_id: uuid.UUID) -> list[UserAccountOut]:
        await self._role(role_id)
        rows = (await self.session.scalars(select(UserAccount).where(UserAccount.role_ids.any(role_id)).order_by(func.lower(UserAccount.display_name)))).all()
        roles = await self._roles()
        return [self._user_out(u, roles) for u in rows]

    async def save_role(self, role_id: uuid.UUID | None, data: RoleIn) -> RoleOut:
        err = FieldErrors()
        name = data.name.strip()
        if not 2 <= len(name) <= 80:
            err.add("name", "Enter a name of 2-80 characters.")
        elif await self.session.scalar(select(Role.id).where(func.lower(Role.name) == name.lower(), Role.id != (role_id or uuid.uuid4()))):
            err.add("name", "Another role already uses this name.")
        perms = [p.strip() for p in data.permissions]
        bad = [p for p in perms if not CODE.match(p)]
        if bad:
            err.add("permissions", f"Not a permission code: {', '.join(bad[:5])}.")
        err.raise_if_any()
        perms = sorted(set(perms))  # stored as given; unknown codes are kept (G3)
        if role_id is None:
            r = Role(name=name, description=data.description.strip(), permissions=perms, active=data.active, system=False)
            self.session.add(r)
            before: dict = {}
        else:
            r = await self._role(role_id, for_update=True)
            ensure_version(r, data.version)
            if r.system and name != r.name:
                raise ValidationFailedError(details=[{"field": "name", "message": "Built-in roles cannot be renamed."}])
            before = {"name": r.name, "description": r.description, "permissions": ", ".join(r.permissions), "active": r.active}
            r.name, r.description, r.permissions, r.active = name, data.description.strip(), perms, data.active
        await self._ensure_an_administrator() if role_id is not None else await self.session.flush()
        self.audit.record(module=MODULE, action="role.created" if role_id is None else "role.updated", summary=f"Role {name} saved", entity_type="role", entity_id=r.id, entity_label=name,
                          changes=diff(before, {"name": r.name, "description": r.description, "permissions": ", ".join(r.permissions), "active": r.active}))
        await self.session.commit()
        await self.session.refresh(r)
        return self._role_out(r, await self._counts())
