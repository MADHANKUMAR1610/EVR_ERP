"""FastAPI dependencies: database session, the signed-in caller (verified token + active session), permission guard,
and service-client authentication for internal endpoints."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.context import Principal, principal_var
from app.core.errors import ForbiddenError, UnauthenticatedError
from app.core.permissions import has_any
from app.core.tokens import INTERNAL_AUDIENCE, TokenService
from app.database.session import get_db_session, get_session_factory
from app.services.audit_service import record_denial
from app.services.auth_service import AuthService

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_audit_session_factory() -> async_sessionmaker[AsyncSession]:
    return get_session_factory()


def token_from(request: Request, settings: Settings) -> str | None:
    cookie = request.cookies.get(settings.auth_cookie_name)
    if cookie:
        return cookie
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


async def get_token(request: Request, settings: AppSettings) -> str | None:
    return token_from(request, settings)


Token = Annotated[str | None, Depends(get_token)]


async def get_current_principal(session: DbSession, settings: AppSettings, token: Token) -> Principal:
    if not token:
        raise UnauthenticatedError()
    claims = TokenService(settings).decode(token)
    if not await AuthService(session, settings).session_active(str(claims.get("sid") or "")):
        raise UnauthenticatedError()
    perms = claims.get("permissions")
    if not isinstance(perms, list):
        raise UnauthenticatedError()
    principal = Principal(user_id=str(claims["sub"]), name=str(claims.get("name") or claims["sub"]), permissions=frozenset(perms),
                          roles=frozenset(claims.get("roles") or []), employee_id=claims.get("employeeId"), session_id=str(claims.get("sid")))
    principal_var.set(principal)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require(*codes: str) -> Callable:
    """The caller needs at least one of `codes`. Denials are audited."""

    async def _guard(request: Request, principal: CurrentPrincipal, factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_audit_session_factory)]) -> Principal:
        if has_any(principal.permissions, codes):
            return principal
        await record_denial(factory, principal, " or ".join(codes), request.url.path)
        raise ForbiddenError()

    return _guard


def require_service(scope: str) -> Callable:
    """Internal endpoints: a service token (aud evr-internal) carrying `scope`."""

    async def _guard(request: Request, settings: AppSettings) -> Principal:
        scheme, _, value = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not value.strip():
            raise UnauthenticatedError()
        claims = TokenService(settings).decode(value.strip(), audience=INTERNAL_AUDIENCE)
        perms = claims.get("permissions") or []
        if scope not in perms and "*" not in perms:
            raise ForbiddenError()
        principal = Principal(user_id=str(claims["sub"]), name=str(claims["sub"]), permissions=frozenset(perms))
        principal_var.set(principal)
        return principal

    return _guard
