"""Administration → Organization → Reporting lines (frontend admin.http.ts, contract G4)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.permissions import A, P
from app.schemas.common import Page, PageParams, page_params
from app.schemas.employee_schema import ManagerChangeIn, ReportingLineOut
from app.services.employee_support import caller_context
from app.services.reporting_line_service import ReportingLineService
from app.utils.ids import path_id

router = APIRouter(prefix="/admin/reporting-lines", tags=["Organization"])

# G4: viewing needs both admin:organization.view (or manage) and hr.employees:view.
_view = [Depends(require(A.ORGANIZATION_VIEW, A.ORGANIZATION_MANAGE)), Depends(require(P.EMPLOYEES_VIEW))]


@router.get("", response_model=Page[ReportingLineOut], dependencies=_view, summary="Reporting lines (scoped)")
async def list_lines(
    session: DbSession,
    principal: CurrentPrincipal,
    params: Annotated[PageParams, Depends(page_params)],
    department_id: Annotated[str | None, Query(alias="departmentId")] = None,
    manager_id: Annotated[str | None, Query(alias="managerId")] = None,
):
    return await ReportingLineService(session, await caller_context(session, principal)).list(params, department_id=department_id, manager_id=manager_id)


@router.post("/{employee_id}", response_model=ReportingLineOut, dependencies=[Depends(require(A.ORGANIZATION_MANAGE))], summary="Change an employee's reporting manager")
async def change_manager(employee_id: str, data: ManagerChangeIn, session: DbSession, principal: CurrentPrincipal):
    return await ReportingLineService(session, await caller_context(session, principal)).change_manager(path_id(employee_id), data)
