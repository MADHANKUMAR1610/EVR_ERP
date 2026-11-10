"""Request ID, access logging and last-resort error handling (pure ASGI, outermost layer).

- Reuses a safe incoming `X-Request-Id` (e.g. from Nginx) or generates one, and returns it on every
  response, including errors.
- Logs one line per request: method, path, status, duration, user ID. Never bodies or headers.
- Converts any exception that escaped the app into the standard 500 envelope, so the client never
  sees a stack trace and still gets the request ID.
"""

import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import principal_var, request_id_var
from app.core.errors import error_body

logger = logging.getLogger("hrms.access")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        rid_token = request_id_var.set(request_id)
        principal_token = principal_var.set(None)
        started = time.perf_counter()
        status = {"code": 500}
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                status["code"] = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            logger.exception("unhandled error")
            if not response_started:
                body = json.dumps(error_body("INTERNAL", "Something went wrong on our side. Quote the reference if you contact support.")).encode()
                await send_with_id({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                await send_with_id({"type": "http.response.body", "body": body})
        finally:
            principal = principal_var.get()
            logger.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status["code"],
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    **({"user_id": principal.user_id} if principal else {}),
                },
            )
            principal_var.reset(principal_token)
            request_id_var.reset(rid_token)
