"""HR workspace (frontend workspace.service.ts, contract B7). Field names match the frontend exactly."""

from typing import Literal

from pydantic import Field

from app.schemas.common import Page, ResponseModel, UtcDateTime
from app.schemas.employee_schema import HistoryEntryOut
from app.schemas.report_schema import MetricOut

TaskType = Literal["employee_record_incomplete", "probation_review_due", "onboarding_documents"]
Priority = Literal["high", "medium", "low"]


class WorkforceSummaryOut(ResponseModel):
    total_employees: MetricOut
    active_employees: MetricOut
    present_today: MetricOut
    pending_approvals: MetricOut
    as_of: UtcDateTime


class EmployeeSubjectOut(ResponseModel):
    id: str
    employee_code: str
    name: str


class HrTaskOut(ResponseModel):
    id: str
    type: TaskType
    title: str
    description: str
    priority: Priority
    status: Literal["pending"]
    due_date: str | None
    subject: EmployeeSubjectOut
    missing_items: list[str] | None = None


class TaskTypeCountsOut(ResponseModel):
    employee_record_incomplete: int = Field(serialization_alias="employee_record_incomplete")
    probation_review_due: int = Field(serialization_alias="probation_review_due")
    onboarding_documents: int = Field(serialization_alias="onboarding_documents")


class TaskCountsOut(ResponseModel):
    total: int
    overdue: int
    high_priority: int
    by_type: TaskTypeCountsOut


class TaskPageOut(Page[HrTaskOut]):
    counts: TaskCountsOut


class WorkspaceActivityOut(HistoryEntryOut):
    subject: EmployeeSubjectOut


class UpcomingEventOut(ResponseModel):
    id: str
    type: Literal["joining", "work_anniversary"]
    date: str
    subject: EmployeeSubjectOut
    years: int | None = None
