"""Sign-in and session (frontend auth.http.ts, contract B1). The session travels in an httpOnly cookie."""

from fastapi import APIRouter, Request, Response, status

from app.api.dependencies import AppSettings, DbSession, Token
from app.core.config import Settings
from app.core.errors import ForbiddenError
from app.middleware.csrf_origin import _origin_of
from app.schemas.identity_schema import AuthSessionOut, LoginIn, PasswordChangeIn
from app.services.auth_service import AuthService, IssuedSession

router = APIRouter(prefix="/auth", tags=["Sign-in"])


def _set_cookie(response: Response, issued: IssuedSession, s: Settings) -> None:
    response.set_cookie(s.auth_cookie_name, issued.token, max_age=issued.max_age, httponly=True, secure=s.auth_cookie_secure, samesite="lax", path="/", domain=s.auth_cookie_domain)
    response.headers["Cache-Control"] = "no-store"


def _check_origin(request: Request, s: Settings) -> None:
    """Login-CSRF: a browser request from another site carries a foreign Origin."""
    origin = request.headers.get("origin") or _origin_of(request.headers.get("referer", ""))
    if origin and s.allowed_origins and origin.rstrip("/").lower() not in {o.rstrip("/").lower() for o in s.allowed_origins}:
        raise ForbiddenError("This request did not come from an allowed page.")


@router.post("/login", response_model=AuthSessionOut, summary="Sign in with username and password; sets the session cookie")
async def login(data: LoginIn, request: Request, response: Response, session: DbSession, settings: AppSettings):
    _check_origin(request, settings)
    ip = request.client.host if request.client else "unknown"
    issued = await AuthService(session, settings).login(data, ip=ip, user_agent=request.headers.get("user-agent"))
    _set_cookie(response, issued, settings)
    return issued.out


@router.get("/session", response_model=AuthSessionOut, summary="The current session with current permissions (401 = signed out)")
async def current_session(response: Response, session: DbSession, settings: AppSettings, token: Token):
    issued = await AuthService(session, settings).restore(token)
    _set_cookie(response, issued, settings)
    return issued.out


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the session everywhere")
async def logout(session: DbSession, settings: AppSettings, token: Token) -> Response:
    await AuthService(session, settings).logout(token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(settings.auth_cookie_name, path="/", domain=settings.auth_cookie_domain, secure=settings.auth_cookie_secure, httponly=True, samesite="lax")
    return response


@router.post("/password", response_model=AuthSessionOut, summary="Change your own password (addition: required after an HR-set password, G-Q5)")
async def change_password(data: PasswordChangeIn, response: Response, session: DbSession, settings: AppSettings, token: Token):
    issued = await AuthService(session, settings).change_password(token, data)
    _set_cookie(response, issued, settings)
    return issued.out
