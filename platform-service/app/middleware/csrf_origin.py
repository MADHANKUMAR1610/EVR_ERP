"""CSRF protection by Origin verification (OWASP), for cookie-authenticated unsafe requests.

The frontend authenticates with a SameSite=Lax cookie and sends no CSRF token. For POST, PUT, PATCH
and DELETE requests that carry the session cookie, the `Origin` header (or, if absent, `Referer`)
must match one of ALLOWED_ORIGINS. Requests authenticated only by a bearer header are not
CSRF-prone (browsers never add that header by themselves) and are not checked.
"""

import json
from http.cookies import SimpleCookie
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import error_body

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower() if parts.scheme and parts.netloc else ""


class CsrfOriginMiddleware:
    def __init__(self, app: ASGIApp, *, cookie_name: str, allowed_origins: list[str]):
        self.app = app
        self.cookie_name = cookie_name
        self.allowed = {o.rstrip("/").lower() for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in UNSAFE:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("cookie", ""))
        except Exception:  # noqa: BLE001 - a malformed cookie header is treated as "no cookie"
            cookie = SimpleCookie()
        if self.cookie_name not in cookie:
            await self.app(scope, receive, send)
            return
        origin = headers.get("origin") or _origin_of(headers.get("referer", ""))
        if origin and origin.rstrip("/").lower() in self.allowed:
            await self.app(scope, receive, send)
            return
        body = json.dumps(error_body("CSRF_REJECTED", "This request did not come from an allowed page. Reload the application and try again.")).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
