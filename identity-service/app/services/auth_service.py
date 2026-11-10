"""Sign-in, session restore, sign-out and password change (contract B1; G2 lockout and forced change).

- A wrong username or password is a 401 INVALID_CREDENTIALS with one generic message. Unknown users,
  inactive or locked accounts get exactly the same answer (and the same Argon2 work).
- Lockout: after LOCKOUT_ATTEMPTS consecutive failures the account is `locked` for LOCKOUT_MINUTES; it
  unlocks by itself after that, or when HR resets the password. Per-IP rate limit: 429.
- Each sign-in creates a session row; its id is the token's `sid`. Revoking it ends the session everywhere.
- `GET /auth/session` re-reads the user and roles and re-issues the cookie, so role changes apply from
  the next page load (and at the latest at the next sign-in).
- mustChangePassword: the session works, but its token carries no permissions until the password is
  changed through POST /auth/password (an addition; the screen is pending, G-Q5).
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import Principal
from app.core.errors import AppError, RateLimitedError, UnauthenticatedError, ValidationFailedError
from app.core.passwords import hash_password, needs_rehash, policy_problems, verify_password
from app.core.tokens import SessionClaims, TokenService
from app.database.audit_listener import acting_as
from app.models.identity_model import Role, UserAccount, UserAccountEvent, UserSession
from app.schemas.identity_schema import AuthSessionOut, AuthUserOut, LoginIn, PasswordChangeIn
from app.services.audit_service import AuditService

MODULE = "Identity"


class InvalidCredentialsError(AppError):
    status_code = 401
    code = "INVALID_CREDENTIALS"
    default_message = "The username or password is incorrect."


class _IpLimiter:
    """Sign-in attempts per client IP in the last minute (in memory, per process)."""

    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str, limit: int) -> bool:
        now = time.monotonic()
        q = self.hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


ip_limiter = _IpLimiter()


def actor(user: UserAccount) -> Principal:
    return Principal(user_id=str(user.id), name=user.display_name, permissions=frozenset())


async def effective(session: AsyncSession, user: UserAccount) -> tuple[list[Role], list[str]]:
    """The user's active roles and the union of their permission codes."""
    roles = list((await session.scalars(select(Role).where(Role.id.in_(user.role_ids), Role.active.is_(True)).order_by(func.lower(Role.name)))).all()) if user.role_ids else []
    perms = sorted({p for r in roles for p in r.permissions})
    return roles, perms


@dataclass
class IssuedSession:
    token: str
    out: AuthSessionOut
    max_age: int


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.s = settings
        self.tokens = TokenService(settings)
        self.audit = AuditService(session)

    def _event(self, user: UserAccount, action: str, summary: str) -> None:
        self.session.add(UserAccountEvent(user_id=user.id, action=action, summary=summary))

    async def _issue(self, user: UserAccount, sess: UserSession) -> IssuedSession:
        roles, perms = await effective(self.session, user)
        token = self.tokens.issue_session(SessionClaims(user_id=str(user.id), name=user.display_name, session_id=str(sess.id), employee_id=user.employee_id,
                                                        roles=[str(r.id) for r in roles], permissions=perms, must_change_password=user.must_change_password, expires_at=sess.expires_at))
        out = AuthSessionOut(user=AuthUserOut(id=str(user.id), username=user.username, display_name=user.display_name, email=user.email, roles=[r.name for r in roles],
                                              permissions=[] if user.must_change_password else perms, employee_id=user.employee_id, must_change_password=user.must_change_password),
                             expires_at=sess.expires_at)
        return IssuedSession(token, out, max(0, int((sess.expires_at - datetime.now(UTC)).total_seconds())))

    # ---- Sign-in ----------------------------------------------------------------------------------------------

    async def login(self, data: LoginIn, *, ip: str, user_agent: str | None) -> IssuedSession:
        if not ip_limiter.allow(ip, self.s.login_rate_per_ip_per_minute):
            raise RateLimitedError("Too many sign-in attempts. Wait a minute and try again.")
        username = data.username.strip()
        if not username or not data.password:
            verify_password(None, data.password or "x")
            raise InvalidCredentialsError()
        user = await self.session.scalar(select(UserAccount).where(func.lower(UserAccount.username) == username.lower()).with_for_update())
        ok = verify_password(user.password_hash if user else None, data.password)
        now = datetime.now(UTC)
        if user is None:
            raise InvalidCredentialsError()
        with acting_as(actor(user)):
            if user.status == "locked" and user.locked_until is not None and user.locked_until <= now:
                user.failed_attempts = 0  # the lock has expired: count afresh
            locked = user.status == "locked" and user.locked_until is not None and user.locked_until > now
            if user.status == "inactive" or locked or (user.status == "locked" and user.locked_until is None):
                self.audit.record(module=MODULE, action="auth.login_refused", summary=f"Sign-in refused for {user.username} ({user.status})", result="failure", entity_type="user_account", entity_id=user.id)
                await self.session.commit()
                raise InvalidCredentialsError()
            if not ok:
                user.failed_attempts += 1
                if user.failed_attempts >= self.s.lockout_attempts:
                    user.status, user.locked_until = "locked", now + timedelta(minutes=self.s.lockout_minutes)
                    self._event(user, "locked", f"Locked for {self.s.lockout_minutes} minutes after {user.failed_attempts} failed sign-in attempts")
                self.audit.record(module=MODULE, action="auth.login_failed", summary=f"Failed sign-in for {user.username}", result="failure", entity_type="user_account", entity_id=user.id)
                await self.session.commit()
                raise InvalidCredentialsError()
            if needs_rehash(user.password_hash):
                user.password_hash = hash_password(data.password)
            user.failed_attempts, user.locked_until, user.last_login_at = 0, None, now
            if user.status in ("locked", "invited"):
                user.status = "active"
            sess = UserSession(id=uuid.uuid4(), user_id=user.id, expires_at=now + timedelta(hours=self.s.session_hours), client_ip=ip[:64], user_agent=(user_agent or "")[:300] or None)
            self.session.add(sess)
            self._event(user, "signed_in", "Signed in")
            self.audit.record(module=MODULE, action="auth.login", summary=f"{user.username} signed in", entity_type="user_account", entity_id=user.id)
            await self.session.flush()
            issued = await self._issue(user, sess)
            await self.session.commit()
            return issued

    # ---- Session --------------------------------------------------------------------------------------------------

    async def _active(self, token: str) -> tuple[UserAccount, UserSession]:
        claims = self.tokens.decode(token)
        try:
            sid = uuid.UUID(str(claims.get("sid")))
        except ValueError:
            raise UnauthenticatedError() from None
        sess = await self.session.get(UserSession, sid)
        now = datetime.now(UTC)
        if sess is None or sess.revoked_at is not None or sess.expires_at <= now or str(sess.user_id) != str(claims["sub"]):
            raise UnauthenticatedError()
        user = await self.session.get(UserAccount, sess.user_id)
        if user is None or user.status not in ("active", "invited"):
            raise UnauthenticatedError()
        return user, sess

    async def restore(self, token: str | None) -> IssuedSession:
        if not token:
            raise UnauthenticatedError()
        user, sess = await self._active(token)
        return await self._issue(user, sess)

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        try:
            user, sess = await self._active(token)
        except UnauthenticatedError:
            return
        with acting_as(actor(user)):
            sess.revoked_at, sess.revoked_reason = datetime.now(UTC), "signed_out"
            self._event(user, "signed_out", "Signed out")
            await self.session.commit()

    async def change_password(self, token: str | None, data: PasswordChangeIn) -> IssuedSession:
        if not token:
            raise UnauthenticatedError()
        user, sess = await self._active(token)
        with acting_as(actor(user)):
            if not verify_password(user.password_hash, data.current_password):
                raise ValidationFailedError(details=[{"field": "currentPassword", "message": "The current password is incorrect."}])
            problems = policy_problems(data.new_password, user.username, self.s)
            if data.new_password == data.current_password:
                problems.append("Choose a password different from the current one.")
            if problems:
                raise ValidationFailedError(details=[{"field": "newPassword", "message": " ".join(problems)}])
            now = datetime.now(UTC)
            user.password_hash, user.password_set_at, user.must_change_password = hash_password(data.new_password), now, False
            # Other sessions end; this one continues with a fresh token.
            await self.session.execute(update(UserSession).where(UserSession.user_id == user.id, UserSession.id != sess.id, UserSession.revoked_at.is_(None))
                                       .values(revoked_at=now, revoked_reason="password_changed"))
            self._event(user, "password_changed", "Changed their password")
            self.audit.record(module=MODULE, action="auth.password_changed", summary=f"{user.username} changed their password", entity_type="user_account", entity_id=user.id)
            await self.session.flush()
            issued = await self._issue(user, sess)
            await self.session.commit()
            return issued

    async def session_active(self, sid: str) -> bool:
        try:
            sess = await self.session.get(UserSession, uuid.UUID(sid))
        except ValueError:
            return False
        if sess is None or sess.revoked_at is not None or sess.expires_at <= datetime.now(UTC):
            return False
        user = await self.session.get(UserAccount, sess.user_id)
        return user is not None and user.status in ("active", "invited")
