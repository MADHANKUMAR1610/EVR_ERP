"""Service-to-service endpoints (not under /api/v1: the proxy never exposes them) and the public JWKS."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import AppSettings, DbSession, require, require_service
from app.services.audit_query import audit_slice
from app.core.tokens import TokenService
from app.schemas.identity_schema import InternalRoleOut, InternalUserOut, ServiceTokenIn, ServiceTokenOut, SessionStateOut
from app.services.auth_service import AuthService
from app.services.internal_service import InternalService

router = APIRouter(prefix="/internal", tags=["Internal"])
keys_router = APIRouter(tags=["Internal"])


@keys_router.get("/.well-known/jwks.json", summary="Public signing keys (services verify session tokens with these)")
async def jwks(settings: AppSettings):
    return TokenService(settings).jwks()


@router.post("/service-tokens", response_model=ServiceTokenOut, summary="Client-credentials: a short-lived service token")
async def service_token(data: ServiceTokenIn, session: DbSession, settings: AppSettings):
    return await InternalService(session, settings).service_token(data)


@router.get("/sessions/{sid}", response_model=SessionStateOut, dependencies=[Depends(require_service("identity:sessions.read"))], summary="Is a session still active (revocation check)")
async def session_state(sid: str, session: DbSession, settings: AppSettings):
    return SessionStateOut(active=await AuthService(session, settings).session_active(sid))


@router.get("/users", response_model=list[InternalUserOut], dependencies=[Depends(require_service("identity:users.read"))], summary="Users by id or search")
async def internal_users(session: DbSession, settings: AppSettings, ids: Annotated[str | None, Query()] = None, q: Annotated[str | None, Query(max_length=100)] = None,
                         limit: Annotated[int, Query(ge=1, le=200)] = 50, employee_ids: Annotated[str | None, Query(alias="employeeIds")] = None,
                         role_ids: Annotated[str | None, Query(alias="roleIds")] = None, active_only: Annotated[bool, Query(alias="activeOnly")] = False):
    split = lambda v: [i for i in (v or "").split(",") if i]  # noqa: E731
    return await InternalService(session, settings).users(ids=split(ids), q=(q or "").strip() or None, limit=limit, employee_ids=split(employee_ids), role_ids=split(role_ids), active_only=active_only)


@router.get("/roles", response_model=list[InternalRoleOut], dependencies=[Depends(require_service("identity:users.read"))], summary="Active roles")
async def internal_roles(session: DbSession, settings: AppSettings):
    return await InternalService(session, settings).roles()


# ---- For the Platform service, called with the caller's own session (each service applies its own permissions) ----


@router.get("/audit-events", dependencies=[Depends(require("admin:audit.view"))], summary="This service's audit events for the administration audit screen")
async def audit_events(session: DbSession, from_: Annotated[str | None, Query(alias="from")] = None, to: Annotated[str | None, Query()] = None,
                       actor_id: Annotated[str | None, Query(alias="actorId")] = None, module: Annotated[str | None, Query()] = None, action: Annotated[str | None, Query()] = None,
                       result: Annotated[str | None, Query()] = None, q: Annotated[str | None, Query(max_length=200)] = None, limit: Annotated[int, Query(ge=1, le=1000)] = 25):
    return await audit_slice(session, start=from_, end=to, actor_id=actor_id, module=module, action=action, result=result, q=q, limit=limit)


@router.get("/overview-counts", dependencies=[Depends(require("admin:view"))], summary="User and role counts for the administration overview")
async def overview_counts(session: DbSession, settings: AppSettings):
    return await InternalService(session, settings).overview_counts()
