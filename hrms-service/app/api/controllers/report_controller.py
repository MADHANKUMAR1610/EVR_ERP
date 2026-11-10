"""HR → Reports (frontend reports.http.ts, contract Part F)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.permissions import P
from app.schemas.common import PageParams, page_params
from app.schemas.report_schema import ReportActivityOut, ReportDefinitionOut, ReportResultOut, ReportsDashboardOut
from app.services.employee_support import caller_context
from app.services.report_service import Params, ReportService

router = APIRouter(prefix="/hr/reports", tags=["Reports"])
ANY = [Depends(require(P.REPORTS_VIEW, P.REPORTS_PAYROLL_VIEW))]
Text = Annotated[str | None, Query(max_length=40)]


async def _service(session, principal) -> ReportService:
    return ReportService(session, await caller_context(session, principal))


def filters(
    q: Annotated[str | None, Query(max_length=200)] = None, department_id: Annotated[str | None, Query(alias="departmentId")] = None, date: Text = None,
    from_: Annotated[str | None, Query(alias="from", max_length=10)] = None, to: Annotated[str | None, Query(max_length=10)] = None, month: Annotated[str | None, Query(max_length=7)] = None,
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None, period_id: Annotated[str | None, Query(alias="periodId")] = None,
    leave_type_id: Annotated[str | None, Query(alias="leaveTypeId")] = None, status: Annotated[str | None, Query(max_length=20)] = None,
) -> Params:
    return Params(q=(q or "").strip() or None, department_id=department_id, date=date, from_=from_, to=to, month=month, year=year, period_id=period_id, leave_type_id=leave_type_id, status=status)


Filters = Annotated[Params, Depends(filters)]


@router.get("", response_model=list[ReportDefinitionOut], dependencies=ANY, summary="Reports the caller may run")
async def catalog(session: DbSession, principal: CurrentPrincipal):
    return (await _service(session, principal)).catalog()


@router.get("/dashboard", response_model=ReportsDashboardOut, dependencies=[Depends(require(P.REPORTS_VIEW))], summary="Headline metrics and trends (each gated by its module permission)")
async def dashboard(session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).dashboard()


@router.get("/activity", response_model=list[ReportActivityOut], dependencies=[Depends(require(P.REPORTS_VIEW))], summary="Recent report runs and exports")
async def activity(session: DbSession, principal: CurrentPrincipal, limit: Annotated[int, Query(ge=1, le=100)] = 10):
    return await (await _service(session, principal)).activity(limit)


@router.get("/{report_id}/export", dependencies=ANY, summary="All matching rows as CSV or XLSX",
            responses={200: {"content": {"text/csv": {}, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
async def export(report_id: str, session: DbSession, principal: CurrentPrincipal, p: Filters, format: Annotated[Literal["csv", "xlsx"], Query()] = "csv",
                 sort: Annotated[str | None, Query(max_length=60)] = None) -> Response:
    content, media_type, name = await (await _service(session, principal)).export(report_id, p, sort=sort, fmt=format)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store, private"})


@router.get("/{report_id}", response_model=ReportResultOut, dependencies=ANY, summary="Run a report: filtered, sorted, paginated; totals over all matching rows")
async def run(report_id: str, session: DbSession, principal: CurrentPrincipal, p: Filters, page: Annotated[PageParams, Depends(page_params)]):
    return await (await _service(session, principal)).run(report_id, p, sort=page.sort, page=page.page, page_size=page.page_size)
