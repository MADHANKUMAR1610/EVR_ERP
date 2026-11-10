"""The administration audit screen and overview (contract G10), across services.

Platform asks Identity and HRMS with the caller's own session (each applies its own permissions), adds its own
events, merges them newest first and pages the result. A service the caller may not read is left out.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.repositories.base_repository import PageResult
from app.schemas.common import PageMeta
from app.schemas.platform_schema import (
    ActorOut,
    AdminOverviewOut,
    AuditEventOut,
    AuditFacetsOut,
    AuditPageOut,
    RoleCountsOut,
    UserCountsOut,
    WorkflowCountsOut,
)
from app.services import peers
from app.services.audit_query import audit_slice
from app.services.integration_service import IntegrationService


class AdminViewService:
    def __init__(self, session: AsyncSession, settings: Settings, token: str | None):
        self.session = session
        self.s = settings
        self.token = token

    async def _slices(self, filters: dict, limit: int) -> list[dict]:
        params = {**filters, "limit": limit}
        slices = [await audit_slice(self.session, start=filters.get("from"), end=filters.get("to"), actor_id=filters.get("actorId"), module=filters.get("module"),
                                    action=filters.get("action"), result=filters.get("result"), q=filters.get("q"), limit=limit)]
        for base, path, name in ((self.s.identity_base_url, "/internal/audit-events", "Identity"), (self.s.hrms_base_url, "/api/v1/hr/internal/audit-events", "HRMS")):
            part = await peers.get_json(base, path, self.token, params, name=name)
            if part:
                slices.append(part)
        return slices

    async def audit(self, filters: dict, page: int, page_size: int) -> AuditPageOut:
        slices = await self._slices(filters, page * page_size)
        events = sorted((e for s in slices for e in s["items"]), key=lambda e: (e["at"], e["id"]), reverse=True)
        total = sum(s["total"] for s in slices)
        modules = sorted({m for s in slices for m in s["facets"]["modules"]})
        actions = sorted({a for s in slices for a in s["facets"]["actions"]})
        actors = {a["id"]: a["name"] for s in slices for a in s["facets"]["actors"]}
        items = [AuditEventOut.model_validate(e) for e in events[(page - 1) * page_size: page * page_size]]
        r = PageResult([], page, page_size, total)
        return AuditPageOut(items=items, meta=PageMeta(page=page, page_size=page_size, total_items=total, total_pages=r.total_pages),
                            facets=AuditFacetsOut(modules=modules, actions=actions, actors=sorted((ActorOut(id=i, name=n) for i, n in actors.items()), key=lambda a: a.name.lower())))

    async def overview(self) -> AdminOverviewOut:
        identity = await peers.get_json(self.s.identity_base_url, "/internal/overview-counts", self.token, name="Identity") or {}
        hrms = await peers.get_json(self.s.hrms_base_url, "/api/v1/hr/internal/admin-counts", self.token, name="HRMS") or {}
        users = identity.get("users") or {"total": 0, "active": 0, "invited": 0, "inactive": 0, "locked": 0}
        roles = identity.get("roles") or {"total": 0, "administrators": 0}
        workflows = hrms.get("workflows") or {"published": 0, "draft": 0, "processesWithoutWorkflow": []}
        recent = (await self.audit({}, 1, 10)).items
        return AdminOverviewOut(users=UserCountsOut(**users), roles=RoleCountsOut(**roles), departments=hrms.get("departments", 0), designations=hrms.get("designations", 0),
                                workflows=WorkflowCountsOut(published=workflows["published"], draft=workflows["draft"], processes_without_workflow=workflows["processesWithoutWorkflow"]),
                                integrations_needing_attention=await IntegrationService(self.session).needing_attention(), recent_audit=recent)
