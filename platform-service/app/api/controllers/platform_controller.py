"""Platform endpoints: company settings (G7), notifications (B2, G8), integrations (G9), audit and overview (G10)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.dependencies import CurrentPrincipal, DbSession, SessionToken, require, require_service
from app.core.config import get_settings
from app.core.permissions import A
from app.schemas.common import PageParams, page_params
from app.schemas.platform_schema import (
    AdminOverviewOut,
    AuditPageOut,
    CompanySettingsIn,
    CompanySettingsOut,
    DeliveryOut,
    IntegrationIn,
    IntegrationOut,
    IntegrationTestOut,
    InternalNotificationIn,
    NotificationFeedOut,
    NotificationPageOut,
    NotificationPreferencesIn,
    NotificationPreferencesOut,
)
from app.services.admin_view_service import AdminViewService
from app.services.integration_service import IntegrationService
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.utils.ids import path_id

admin_router = APIRouter(prefix="/admin", tags=["Administration"])
notifications_router = APIRouter(prefix="/notifications", tags=["Notifications"])
internal_router = APIRouter(prefix="/internal", tags=["Internal"])
Params = Annotated[PageParams, Depends(page_params)]
Category = Literal["approval", "attendance", "leave", "overtime", "payroll", "employee", "documents", "performance", "system"]


# ---- Company settings ----------------------------------------------------------------------------------------------


@admin_router.get("/settings/company", response_model=CompanySettingsOut, dependencies=[Depends(require(A.SETTINGS_VIEW))], summary="Company settings (empty until saved)")
async def company_settings(session: DbSession):
    return await SettingsService(session).get()


@admin_router.put("/settings/company", response_model=CompanySettingsOut, dependencies=[Depends(require(A.SETTINGS_MANAGE))], summary="Save company settings (version 0 for the first save)")
async def save_company_settings(data: CompanySettingsIn, session: DbSession):
    return await SettingsService(session).save(data)


# ---- Integrations ------------------------------------------------------------------------------------------------------


@admin_router.get("/integrations", response_model=list[IntegrationOut], dependencies=[Depends(require(A.INTEGRATIONS_VIEW))], summary="Integrations (secrets never returned)")
async def integrations(session: DbSession):
    return await IntegrationService(session).list()


@admin_router.put("/integrations/{integration_id}", response_model=IntegrationOut, dependencies=[Depends(require(A.INTEGRATIONS_MANAGE))], summary="Save settings; omitted secrets are kept")
async def save_integration(integration_id: str, data: IntegrationIn, session: DbSession):
    return await IntegrationService(session).save(integration_id, data)


@admin_router.post("/integrations/{integration_id}/test", response_model=IntegrationTestOut, dependencies=[Depends(require(A.INTEGRATIONS_MANAGE))], summary="Test the connection")
async def test_integration(integration_id: str, session: DbSession):
    return await IntegrationService(session).test(integration_id)


# ---- Audit and overview -------------------------------------------------------------------------------------------------


@admin_router.get("/audit-events", response_model=AuditPageOut, dependencies=[Depends(require(A.AUDIT_VIEW))], summary="Audit events of every service, newest first")
async def audit_events(session: DbSession, token: SessionToken, params: Params, from_: Annotated[str | None, Query(alias="from")] = None, to: Annotated[str | None, Query()] = None,
                       actor_id: Annotated[str | None, Query(alias="actorId")] = None, module: Annotated[str | None, Query(max_length=50)] = None,
                       action: Annotated[str | None, Query(max_length=80)] = None, result: Annotated[Literal["success", "failure", "denied"] | None, Query()] = None):
    filters = {"from": from_, "to": to, "actorId": actor_id, "module": module, "action": action, "result": result, "q": params.q}
    return await AdminViewService(session, get_settings(), token).audit(filters, params.page, params.page_size)


@admin_router.get("/overview", response_model=AdminOverviewOut, dependencies=[Depends(require(A.VIEW))], summary="Administration overview")
async def overview(session: DbSession, token: SessionToken):
    return await AdminViewService(session, get_settings(), token).overview()


# ---- Notifications (only the caller's own) ---------------------------------------------------------------------------------


@notifications_router.get("", response_model=NotificationFeedOut, summary="Latest notifications for the bell menu")
async def feed(session: DbSession, principal: CurrentPrincipal, limit: Annotated[int, Query(ge=1, le=50)] = 20):
    return await NotificationService(session, get_settings(), principal).feed(limit)


@notifications_router.get("/history", response_model=NotificationPageOut, summary="Notification history")
async def history(session: DbSession, principal: CurrentPrincipal, params: Params, category: Annotated[Category | None, Query()] = None,
                  status_: Annotated[Literal["read", "unread"] | None, Query(alias="status")] = None):
    return await NotificationService(session, get_settings(), principal).history(category=category, status=status_, page=params.page, page_size=params.page_size)


@notifications_router.get("/preferences", response_model=NotificationPreferencesOut, summary="Your delivery preferences")
async def preferences(session: DbSession, principal: CurrentPrincipal):
    return await NotificationService(session, get_settings(), principal).preferences()


@notifications_router.put("/preferences", response_model=NotificationPreferencesOut, summary="Save your delivery preferences")
async def save_preferences(data: NotificationPreferencesIn, session: DbSession, principal: CurrentPrincipal):
    return await NotificationService(session, get_settings(), principal).save_preferences(data)


@notifications_router.post("/read-all", status_code=status.HTTP_204_NO_CONTENT, summary="Mark all read")
async def read_all(session: DbSession, principal: CurrentPrincipal) -> Response:
    await NotificationService(session, get_settings(), principal).mark_all_read()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@notifications_router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT, summary="Mark one read (404 if not yours)")
async def read_one(notification_id: str, session: DbSession, principal: CurrentPrincipal) -> Response:
    await NotificationService(session, get_settings(), principal).mark_read(path_id(notification_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- Internal: delivery for other services ------------------------------------------------------------------------------------


@internal_router.post("/notifications", response_model=DeliveryOut, summary="Deliver a notification (service token with platform:notifications.write)")
async def deliver(data: InternalNotificationIn, session: DbSession, service: Annotated[object, Depends(require_service("platform:notifications.write"))]):
    return await NotificationService(session, get_settings()).deliver(data, source=service.user_id)  # type: ignore[attr-defined]
