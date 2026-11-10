"""Approval workflows (frontend admin.service.ts Workflow*, contract G5)."""

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel, ResponseModel, UtcDateTime

Process = Literal["leave", "attendance_correction", "overtime", "payroll", "performance_review"]
ApproverType = Literal["reporting_manager", "department_head", "role", "user"]


class StepCondition(CamelModel):
    field: str = Field(max_length=60)
    operator: Literal["gt", "gte", "lt", "lte"]
    value: float


class StepFallback(CamelModel):
    type: Literal["role", "user"]
    role_id: str | None = Field(default=None, max_length=100)
    user_id: str | None = Field(default=None, max_length=100)


class WorkflowStep(CamelModel):
    id: str = Field(max_length=60)
    name: str = Field(min_length=1, max_length=120)
    approver_type: ApproverType
    role_id: str | None = Field(default=None, max_length=100)
    user_id: str | None = Field(default=None, max_length=100)
    required: bool
    condition: StepCondition | None = None
    fallback: StepFallback | None = None
    escalate_after_hours: int | None = Field(default=None, ge=1, le=24 * 60)


class WorkflowIn(CamelModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=1000)
    process: Process
    effective_from: str | None = None
    effective_to: str | None = None
    steps: list[WorkflowStep] = Field(max_length=20)
    version: int | None = None


class WorkflowActionIn(CamelModel):
    version: int
    note: str = Field(default="", max_length=500)


class WorkflowHistoryOut(ResponseModel):
    version: int
    status: Literal["draft", "published", "archived"]
    at: UtcDateTime
    by: str
    note: str


class WorkflowOut(ResponseModel):
    id: str
    name: str
    description: str
    process: Process
    status: Literal["draft", "published", "archived"]
    version: int
    effective_from: str | None
    effective_to: str | None
    steps: list[WorkflowStep]
    history: list[WorkflowHistoryOut]
    updated_at: UtcDateTime
    updated_by: str


class ConditionFieldOut(ResponseModel):
    field: str
    label: str
    unit: str


class ProcessDefinitionOut(ResponseModel):
    process: Process
    label: str
    condition_fields: list[ConditionFieldOut]
