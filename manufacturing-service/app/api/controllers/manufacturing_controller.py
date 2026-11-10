"""Production work orders and the company dashboard (frontend workOrders.http.ts and dashboard.http.ts). Read-only."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import DbSession, require
from app.core.config import get_settings
from app.core.permissions import M
from app.schemas.common import Page, PageParams, page_params
from app.schemas.manufacturing_schema import DashboardSummaryOut, WorkOrderListItemOut, WorkOrderOut, WorkOrderStageOut, WorkOrderSummaryOut
from app.services.manufacturing_service import ManufacturingService

production_router = APIRouter(prefix="/production", tags=["Production"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
VIEW = [Depends(require(M.MANUFACTURING_VIEW))]


@production_router.get("/work-order-stages", response_model=list[WorkOrderStageOut], dependencies=VIEW, summary="The shop-floor route (configuration)")
async def stages(session: DbSession):
    return await ManufacturingService(session, get_settings()).stages()


@production_router.get("/work-orders/summary", response_model=WorkOrderSummaryOut, dependencies=VIEW, summary="Pipeline figures")
async def summary(session: DbSession):
    return await ManufacturingService(session, get_settings()).summary()


@production_router.get("/work-orders", response_model=Page[WorkOrderListItemOut], dependencies=VIEW, summary="Work orders")
async def work_orders(session: DbSession, params: Annotated[PageParams, Depends(page_params)], stage: Annotated[str | None, Query(max_length=30)] = None,
                      view: Annotated[Literal["all", "delayed", "blocked", "due_soon"] | None, Query()] = None, work_centre: Annotated[str | None, Query(alias="workCentre", max_length=80)] = None):
    return await ManufacturingService(session, get_settings()).list(q=params.q, stage=stage, view=view, work_centre=work_centre, sort=params.sort, page=params.page, page_size=params.page_size)


@production_router.get("/work-orders/{work_order_id}", response_model=WorkOrderOut, dependencies=VIEW, summary="One work order (id or work order number)")
async def work_order(work_order_id: str, session: DbSession):
    return await ManufacturingService(session, get_settings()).get(work_order_id)


@dashboard_router.get("/summary", response_model=DashboardSummaryOut, dependencies=[Depends(require(M.DASHBOARD_VIEW))], summary="Company overview figures")
async def dashboard(session: DbSession):
    return await ManufacturingService(session, get_settings()).dashboard()
