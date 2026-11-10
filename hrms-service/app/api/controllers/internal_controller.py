"""Views for the Platform service's administration screens (hrms-service docs/AUTH_INTEGRATION.md section 4).

Platform calls these with the caller's own session, so HRMS applies the caller's permissions: the audit screen
needs admin:audit.view, the overview needs admin:view. Values in audit changes were masked when written.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.dependencies import DbSession, require
from app.core.permissions import A
from app.models.attendance_model import WORKFLOW_PROCESSES, Workflow
from app.models.department_model import Department
from app.models.designation_model import Designation
from app.services.audit_query import audit_slice

router = APIRouter(prefix="/hr/internal", tags=["Internal"])


@router.get("/audit-events", dependencies=[Depends(require(A.AUDIT_VIEW))], summary="HRMS audit events for the administration audit screen")
async def audit_events(session: DbSession, from_: Annotated[str | None, Query(alias="from")] = None, to: Annotated[str | None, Query()] = None,
                       actor_id: Annotated[str | None, Query(alias="actorId")] = None, module: Annotated[str | None, Query()] = None, action: Annotated[str | None, Query()] = None,
                       result: Annotated[str | None, Query()] = None, q: Annotated[str | None, Query(max_length=200)] = None, limit: Annotated[int, Query(ge=1, le=1000)] = 25):
    return await audit_slice(session, start=from_, end=to, actor_id=actor_id, module=module, action=action, result=result, q=q, limit=limit)


@router.get("/admin-counts", dependencies=[Depends(require(A.VIEW))], summary="Departments, designations and approval workflows for the administration overview")
async def admin_counts(session: DbSession):
    by_status = dict((await session.execute(select(Workflow.status, func.count()).group_by(Workflow.status))).all())
    published = set((await session.scalars(select(Workflow.process).where(Workflow.status == "published").distinct())).all())
    return {
        "departments": await session.scalar(select(func.count()).select_from(Department)) or 0,
        "designations": await session.scalar(select(func.count()).select_from(Designation)) or 0,
        "workflows": {"published": by_status.get("published", 0), "draft": by_status.get("draft", 0), "processesWithoutWorkflow": [p for p in WORKFLOW_PROCESSES if p not in published]},
    }
