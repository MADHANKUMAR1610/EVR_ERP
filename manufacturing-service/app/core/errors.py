"""Application errors and the single error envelope used for every non-2xx response.

    { "error": { "code": "VALIDATION_FAILED", "message": "...", "details": [{ "field": "...", "message": "..." }] } }

Messages are safe to show to end users: no stack traces, SQL or internal details.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException


logger = logging.getLogger("manufacturing.errors")


class AppError(Exception):
    """Base class for errors the service reports to the client on purpose."""

    status_code = 400
    code = "BAD_REQUEST"
    default_message = "The request could not be processed."

    def __init__(self, message: str | None = None, *, details: list[dict[str, str]] | None = None, code: str | None = None):
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.details = details or []
        if code:
            self.code = code


class BadRequestError(AppError):
    status_code, code, default_message = 400, "BAD_REQUEST", "The request is not valid."


class UnauthenticatedError(AppError):
    status_code, code, default_message = 401, "UNAUTHENTICATED", "Your session has ended. Sign in again."


class ForbiddenError(AppError):
    status_code, code, default_message = 403, "FORBIDDEN", "You do not have permission to perform this action."


class NotFoundError(AppError):
    status_code, code, default_message = 404, "NOT_FOUND", "The requested record was not found."


class ConflictError(AppError):
    """409. Use a specific code: STALE_VERSION, DUPLICATE, INVALID_TRANSITION, PERIOD_LOCKED or CONFLICT."""

    status_code, code, default_message = 409, "CONFLICT", "The request conflicts with the current state of the record."


class StaleVersionError(ConflictError):
    code, default_message = "STALE_VERSION", "This record was changed by someone else. Reload it and try again."


class InvalidTransitionError(ConflictError):
    code, default_message = "INVALID_TRANSITION", "This action is not allowed in the record's current state."


class PeriodLockedError(ConflictError):
    code, default_message = "PERIOD_LOCKED", "This payroll period is finalized and can no longer be changed."


class LengthRequiredError(AppError):
    status_code, code, default_message = 411, "LENGTH_REQUIRED", "Uploads must declare their size (Content-Length)."


class PayloadTooLargeError(AppError):
    status_code, code, default_message = 413, "PAYLOAD_TOO_LARGE", "The file is too large."


class ValidationFailedError(AppError):
    status_code, code, default_message = 422, "VALIDATION_FAILED", "Some fields need attention."


class RateLimitedError(AppError):
    status_code, code, default_message = 429, "RATE_LIMITED", "Too many requests. Try again shortly."


class ServiceUnavailableError(AppError):
    status_code, code, default_message = 503, "SERVICE_UNAVAILABLE", "A required service is unavailable. Try again shortly."


def field_error(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(details=[{"field": field, "message": message}])


def error_body(code: str, message: str, details: list[dict[str, str]] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or []}}


def _response(status: int, code: str, message: str, details: list[dict[str, str]] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=error_body(code, message, details))


def _camel(part: str) -> str:
    head, *rest = part.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def _field_path(loc: tuple[Any, ...]) -> str:
    """('body', 'personal', 'email') -> 'personal.email'; ('query', 'pageSize') -> 'pageSize'."""
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(_camel(p) for p in parts)


_PYDANTIC_MESSAGES = {
    "missing": "This field is required.",
    "string_too_short": "This value is too short.",
    "string_too_long": "This value is too long.",
    "uuid_parsing": "Enter a valid identifier.",
    "date_from_datetime_parsing": "Enter a valid date (YYYY-MM-DD).",
    "date_parsing": "Enter a valid date (YYYY-MM-DD).",
    "datetime_parsing": "Enter a valid date and time.",
    "int_parsing": "Enter a whole number.",
    "bool_parsing": "Enter true or false.",
    "literal_error": "Choose one of the allowed values.",
    "enum": "Choose one of the allowed values.",
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("service error", extra={"code": exc.code})
        return _response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for err in exc.errors():
            message = _PYDANTIC_MESSAGES.get(err.get("type", ""), None)
            if message is None:
                raw = str(err.get("msg", "Invalid value."))
                message = raw.removeprefix("Value error, ")
            details.append({"field": _field_path(tuple(err.get("loc", ()))), "message": message})
        return _response(422, "VALIDATION_FAILED", "Some fields need attention.", details)

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, __: StaleDataError) -> JSONResponse:
        return _response(409, StaleVersionError.code, StaleVersionError.default_message)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        # Safety net behind the services' own checks. Never echo the database message.
        pgcode = getattr(getattr(exc, "orig", None), "sqlstate", None) or getattr(getattr(exc, "orig", None), "pgcode", None)
        logger.warning("integrity error", extra={"sqlstate": pgcode})
        if pgcode == "23505":
            return _response(409, "DUPLICATE", "A record with these details already exists.")
        return _response(409, "CONFLICT", "The change conflicts with related records.")

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: ("NOT_FOUND", "The requested resource was not found."), 405: ("METHOD_NOT_ALLOWED", "This method is not allowed here.")}
        code, message = codes.get(exc.status_code, ("HTTP_ERROR", "The request could not be processed."))
        return _response(exc.status_code, code, message)

    # Any other exception is turned into the 500 envelope by RequestContextMiddleware, which also
    # adds the request ID (an Exception handler here would run outside that middleware).
