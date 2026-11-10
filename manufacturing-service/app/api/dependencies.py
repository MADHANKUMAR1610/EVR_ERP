"""FastAPI dependencies shared by every controller: database session, caller identity, permissions."""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.context import Principal, principal_var
from app.core.errors import ForbiddenError, UnauthenticatedError
from app.core.permissions import has_any
from app.core.security import TokenVerifier
from app.database.session import get_db_session, get_session_factory
from app.services.audit_service import record_denial

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_token_verifier(request: Request) -> TokenVerifier:
    return request.app.state.token_verifier


def get_audit_session_factory() -> async_sessionmaker[AsyncSession]:
    """Separate sessions for writing access denials (overridden in tests)."""
    return get_session_factory()


def _token_from(request: Request, settings: Settings) -> str | None:
    cookie = request.cookies.get(settings.auth_cookie_name)
    if cookie:
        return cookie
    auth = request.headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() == "bearer" and value.strip():
        return value.strip()
    return None


async def get_current_principal(
    request: Request,
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Principal:
    token = _token_from(request, settings)
    if not token:
        raise UnauthenticatedError()
    principal = verifier.decode(token)
    await verifier.ensure_active(principal)
    principal_var.set(principal)
    return principal


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


def require(*codes: str) -> Callable:
    """Endpoint guard: the caller needs at least one of `codes`. Denials are audited.

    Record- and field-level checks (own records, assigned approver, restricted fields) are done in
    the services, because they depend on the data.
    """

    async def _guard(
        request: Request,
        principal: CurrentPrincipal,
        factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_audit_session_factory)],
    ) -> Principal:
        if has_any(principal.permissions, codes):
            return principal
        await record_denial(factory, principal, " or ".join(codes), request.url.path)
        raise ForbiddenError()

    return _guard


def bearer(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


async def get_session_token(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> str | None:
    """The caller's own session token, forwarded to Identity and HRMS so they apply their own permissions."""
    return _token_from(request, settings)


SessionToken = Annotated[str | None, Depends(get_session_token)]


def require_service(scope: str) -> Callable:
    """Internal endpoints: a service token (aud evr-internal) carrying `scope`."""

    async def _guard(request: Request, verifier: Annotated[TokenVerifier, Depends(get_token_verifier)]) -> Principal:
        token = bearer(request)
        if not token:
            raise UnauthenticatedError()
        principal = verifier.decode_service(token)
        if scope not in principal.permissions and "*" not in principal.permissions:
            raise ForbiddenError()
        principal_var.set(principal)
        return principal

    return _guard
