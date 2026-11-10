"""HR → Workspace (frontend workspace.http.ts, contract B7). Read-only; tasks are derived from the employee data."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.permissions import P
from app.schemas.workspace_schema import TaskPageOut, UpcomingEventOut, WorkforceSummaryOut, WorkspaceActivityOut
from app.services.employee_support import caller_context
from app.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/hr", tags=["HR workspace"])


async def _service(session, principal) -> WorkspaceService:
    return WorkspaceService(session, await caller_context(session, principal))


@router.get("/workspace/summary", response_model=WorkforceSummaryOut, dependencies=[Depends(require(P.DASHBOARD_VIEW))], summary="Workforce summary (unavailable figures carry a reason)")
async def summary(session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).summary()


@router.get("/tasks", response_model=TaskPageOut, dependencies=[Depends(require(P.DASHBOARD_VIEW, P.EMPLOYEES_EDIT, P.DOCUMENTS_UPLOAD, P.EMPLOYEES_CHANGE_STATUS))],
            summary="The caller's derived task queue, with unfiltered counts")
async def tasks(
    session: DbSession, principal: CurrentPrincipal, page: Annotated[int, Query(ge=1)] = 1, page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100, description="1-100: the dashboard asks for short lists")] = 25,
    type_: Annotated[Literal["employee_record_incomplete", "probation_review_due", "onboarding_documents"] | None, Query(alias="type")] = None,
    priority: Annotated[Literal["high", "medium", "low"] | None, Query()] = None, due: Annotated[Literal["overdue", "next7", "next30"] | None, Query()] = None,
):
    return await (await _service(session, principal)).tasks(type_=type_, priority=priority, due=due, page=page, page_size=page_size)


@router.get("/activity", response_model=list[WorkspaceActivityOut], dependencies=[Depends(require(P.EMPLOYEES_VIEW))], summary="Recent employee history (field names only, no values)")
async def activity(session: DbSession, principal: CurrentPrincipal, limit: Annotated[int, Query(ge=1, le=50)] = 6):
    return await (await _service(session, principal)).activity(limit)


@router.get("/upcoming-events", response_model=list[UpcomingEventOut], dependencies=[Depends(require(P.EMPLOYEES_VIEW))], summary="Joinings and work anniversaries (no birthdays)")
async def upcoming_events(session: DbSession, principal: CurrentPrincipal, days: Annotated[int, Query(ge=1, le=90)] = 30):
    return await (await _service(session, principal)).upcoming(days)
