"""Liveness and readiness probes for Docker and the reverse proxy. No authentication, no data."""

from fastapi import APIRouter
from sqlalchemy import text

from app.api.dependencies import DbSession
from app.core.errors import ServiceUnavailableError

router = APIRouter(tags=["Health"])


@router.get("/health", summary="Liveness: the process is running")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", summary="Readiness: the database is reachable")
async def ready(session: DbSession) -> dict[str, str]:
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        raise ServiceUnavailableError("The database is not reachable.") from None
    return {"status": "ready"}
