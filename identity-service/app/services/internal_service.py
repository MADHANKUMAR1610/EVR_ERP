"""Service-to-service features (hrms-service docs/AUTH_INTEGRATION.md sections 2 and 4).

- Client-credentials: a service presents its client id and secret and receives a short-lived service
  token (aud evr-internal) with the scopes configured for it. Secrets are configured as SHA-256 hashes.
- Session state, user and role lists for HRMS (revocation checks, approver pickers, names).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import Principal
from app.core.errors import UnauthenticatedError
from app.core.tokens import TokenService
from app.database.audit_listener import acting_as
from app.models.identity_model import Role, ServiceTokenIssue, UserAccount
from app.schemas.identity_schema import InternalRoleOut, InternalUserOut, ServiceTokenIn, ServiceTokenOut


class InternalService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.s = settings

    async def service_token(self, data: ServiceTokenIn) -> ServiceTokenOut:
        expected = self.s.service_clients.get(data.client_id)
        given = hashlib.sha256(data.client_secret.encode()).hexdigest()
        if not expected or not hmac.compare_digest(expected.lower(), given):
            raise UnauthenticatedError("The client id or secret is incorrect.")
        token, jti, exp = TokenService(self.s).issue_service(data.client_id, self.s.service_client_scopes.get(data.client_id, []))
        with acting_as(Principal(user_id=data.client_id, name=data.client_id, permissions=frozenset())):
            self.session.add(ServiceTokenIssue(client_id=data.client_id, jti=jti, expires_at=exp))
            await self.session.commit()
        return ServiceTokenOut(access_token=token, expires_in=self.s.service_token_minutes * 60)

    async def users(self, *, ids: list[str], q: str | None, limit: int, employee_ids: list[str] | None = None, role_ids: list[str] | None = None, active_only: bool = False) -> list[InternalUserOut]:
        stmt = select(UserAccount)
        if employee_ids or role_ids:
            parts = []
            if employee_ids:
                parts.append(UserAccount.employee_id.in_(employee_ids))
            roles = []
            for r in role_ids or []:
                try:
                    roles.append(uuid.UUID(r))
                except ValueError:
                    continue
            if roles:
                parts.append(UserAccount.role_ids.overlap(roles))
            stmt = stmt.where(or_(*parts)) if parts else stmt.where(UserAccount.id.is_(None))
        if active_only:
            stmt = stmt.where(UserAccount.status.in_(("active", "invited")))
        if ids:
            parsed = []
            for i in ids:
                try:
                    parsed.append(uuid.UUID(i))
                except ValueError:
                    continue
            stmt = stmt.where(UserAccount.id.in_(parsed))
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(UserAccount.display_name).like(like), func.lower(UserAccount.username).like(like)))
        rows = (await self.session.scalars(stmt.order_by(func.lower(UserAccount.display_name)).limit(limit))).all()
        return [InternalUserOut(id=str(u.id), name=u.display_name, employee_id=u.employee_id, active=u.status in ("active", "invited"), role_ids=[str(r) for r in u.role_ids]) for u in rows]

    async def roles(self) -> list[InternalRoleOut]:
        rows = (await self.session.scalars(select(Role).where(Role.active.is_(True)).order_by(func.lower(Role.name)))).all()
        return [InternalRoleOut(id=str(r.id), name=r.name) for r in rows]


    async def overview_counts(self) -> dict:
        from app.core.permissions import ROLES_MANAGE, has_permission

        rows = dict((await self.session.execute(select(UserAccount.status, func.count()).group_by(UserAccount.status))).all())
        roles = (await self.session.scalars(select(Role))).all()
        return {"users": {"total": sum(rows.values()), **{k: rows.get(k, 0) for k in ("active", "invited", "inactive", "locked")}},
                "roles": {"total": len(roles), "administrators": sum(1 for r in roles if r.active and has_permission(r.permissions, ROLES_MANAGE))}}
