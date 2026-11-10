"""Reports (frontend reports.service.ts, contract Part F). Field names match the frontend exactly."""

from typing import Literal

from app.schemas.common import PageMeta, ResponseModel, UtcDateTime
from app.schemas.employee_schema import NamedRefOut

ReportCategory = Literal["hr", "attendance", "leave", "payroll"]
ReportFilter = Literal["date", "dateRange", "month", "year", "period", "department", "search", "leaveType", "requestStatus"]
ExportFormat = Literal["csv", "xlsx"]
ColumnType = Literal["text", "code", "number", "percent", "money", "date", "datetime", "time", "minutes", "status"]
Cell = str | int | float | None


class ReportDefinitionOut(ResponseModel):
    id: str
    category: ReportCategory
    title: str
    description: str
    filters: list[ReportFilter]
    formats: list[ExportFormat]
    default_sort: str | None = None


class ReportColumnOut(ResponseModel):
    key: str
    label: str
    type: ColumnType
    sortable: bool
    priority: Literal["primary", "secondary", "detail"] | None = None


class ReportRefOut(ResponseModel):
    id: str
    title: str


class ReportResultOut(ResponseModel):
    report: ReportRefOut
    columns: list[ReportColumnOut]
    rows: list[dict[str, Cell]]
    totals: dict[str, Cell] | None
    meta: PageMeta
    currency: str | None
    notes: list[str]
    generated_at: UtcDateTime


class ReportActivityOut(ResponseModel):
    id: str
    report_id: str
    report_title: str
    action: Literal["exported", "generated"]
    format: ExportFormat | None = None
    by: str
    at: UtcDateTime


class MetricOut(ResponseModel):
    value: int | float | None
    unavailable_reason: str | None = None


class MonthMetricOut(MetricOut):
    month: str


class YearMetricOut(MetricOut):
    year: int


class PayrollCostMetricOut(MetricOut):
    period_label: str | None
    currency: str


class AttendanceTrendOut(ResponseModel):
    month: str
    rate: float | None


class HeadcountOut(ResponseModel):
    department: NamedRefOut
    count: int


class PayrollCostTrendOut(ResponseModel):
    month: str
    label: str
    cost: float | None


class ReportsDashboardOut(ResponseModel):
    total_employees: MetricOut
    attendance_rate: MonthMetricOut
    leave_utilisation: YearMetricOut
    payroll_cost: PayrollCostMetricOut
    payroll_exceptions: MetricOut
    pending_payroll_approvals: MetricOut
    attendance_trend: list[AttendanceTrendOut]
    headcount_by_department: list[HeadcountOut]
    payroll_cost_trend: list[PayrollCostTrendOut]
    as_of: UtcDateTime
