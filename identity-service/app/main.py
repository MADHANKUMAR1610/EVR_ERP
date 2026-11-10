"""Identity service application factory: sign-in, sessions, users, roles, permissions.

Start in production with:  uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 2 --proxy-headers
The database schema is managed by Alembic; nothing is created at startup.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.database.audit_listener  # noqa: F401 - registers the audit-column listener
from app.api.router import api_router, root_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.database.session import dispose_engine
from app.middleware.csrf_origin import CsrfOriginMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.schemas.common import ErrorEnvelope

logger = logging.getLogger("identity")
ERROR_RESPONSES = {code: {"model": ErrorEnvelope} for code in (400, 401, 403, 404, 409, 422, 429, 500)}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info("startup", extra={"environment": settings.environment, "service": settings.service_name})
        yield
        await dispose_engine()

    app = FastAPI(title="EVR Power ERP — Identity service", version="0.1.0", description="Sign-in, sessions, users, roles and the permission catalogue.",
                  lifespan=lifespan, docs_url="/docs" if settings.docs_enabled else None, redoc_url=None,
                  openapi_url="/openapi.json" if settings.docs_enabled else None, responses=ERROR_RESPONSES)
    app.state.settings = settings
    register_exception_handlers(app)
    app.add_middleware(CsrfOriginMiddleware, cookie_name=settings.auth_cookie_name, allowed_origins=settings.allowed_origins)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(root_router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
