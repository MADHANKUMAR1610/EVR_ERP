"""Manufacturing (frontend workOrders.service.ts and dashboard.service.ts). Field names match the frontend exactly."""

from typing import Literal

from app.schemas.common import ResponseModel, UtcDateTime


class WorkOrderStageOut(ResponseModel):
    code: str
    label: str
    sequence: int


class SalesOrderRefOut(ResponseModel):
    id: str
    order_no: str
    customer_name: str


class UnitOut(ResponseModel):
    index: int
    of: int


class ProductOut(ResponseModel):
    rating_kva: float
    voltage_ratio: str
    vector_group: str
    cooling: str


class ScheduleOut(ResponseModel):
    status: Literal["on_track", "at_risk", "delayed"]
    variance_days: int


class BlockerOut(ResponseModel):
    type: Literal["material", "quality", "engineering", "capacity"]
    description: str
    since: str


class PersonOut(ResponseModel):
    id: str
    name: str
    role: str


class NextActionOut(ResponseModel):
    label: str
    owner: PersonOut
    due_date: str | None


class WorkOrderListItemOut(ResponseModel):
    id: str
    work_order_no: str
    sales_order: SalesOrderRefOut
    unit: UnitOut
    product: ProductOut
    status: Literal["not_started", "in_progress", "on_hold", "completed"]
    stage: WorkOrderStageOut
    stage_count: int
    priority: Literal["high", "normal"]
    work_centre: str
    planned_start: str
    planned_finish: str
    customer_due_date: str
    schedule: ScheduleOut
    blocker: BlockerOut | None
    next_action: NextActionOut


class StageRecordOut(ResponseModel):
    code: str
    label: str
    state: Literal["done", "current", "pending"]
    started_at: str | None
    completed_at: str | None


class MaterialLineOut(ResponseModel):
    item: str
    required: str
    status: Literal["issued", "available", "short", "on_order"]
    expected_date: str | None


class WorkOrderEventOut(ResponseModel):
    id: str
    at: UtcDateTime
    by: str
    summary: str


class WorkOrderOut(WorkOrderListItemOut):
    stages: list[StageRecordOut]
    materials: list[MaterialLineOut]
    history: list[WorkOrderEventOut]
    design_ref: str


class StageCountOut(ResponseModel):
    code: str
    label: str
    count: int


class WorkOrderSummaryOut(ResponseModel):
    by_stage: list[StageCountOut]
    open: int
    delayed: int
    at_risk: int
    blocked: int
    blocked_by_material: int
    due_soon: int
    due_window_days: int
    as_of: UtcDateTime


class DashboardKpisOut(ResponseModel):
    open_orders: int
    units_in_production: int
    tests_pending: int
    dispatches_this_week: int


class MonthlyOutputOut(ResponseModel):
    month: str
    units_completed: int
    mva_completed: float


class RecentOrderOut(ResponseModel):
    id: str
    order_no: str
    customer_name: str
    rating_kva: float
    quantity: int
    status: Literal["draft", "confirmed", "in_design", "in_production", "testing", "ready_to_dispatch", "dispatched", "on_hold"]
    due_date: str


class DashboardSummaryOut(ResponseModel):
    kpis: DashboardKpisOut
    monthly_output: list[MonthlyOutputOut]
    recent_orders: list[RecentOrderOut]
