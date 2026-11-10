"""Leave management (frontend leave.service.ts and approvals.service.ts, contracts E2, E3, H3).

Field names match the frontend exactly. Setup schemas (HR setup of types, policies, holidays,
allocations, adjustments) are additions without a frontend screen.
"""

from typing import Literal

from pydantic import Field

from app.schemas.attendance_schema import EmployeeRefOut, RequestStatus, WorkflowEventOut
from app.schemas.common import CamelModel, Page, ResponseModel, UtcDateTime
from app.schemas.employee_schema import NamedRefOut

Portion = Literal["full", "first_half", "second_half"]
DeadlineUnit = Literal["hours", "days", "working_days"]
FirstApprover = Literal["reporting_manager", "department_head"]


class LeaveTypeRefOut(ResponseModel):
    id: str
    code: str
    name: str


class LeaveTypeOut(ResponseModel):
    id: str
    code: str
    name: str
    paid: bool
    allow_half_day: bool
    balance_tracked: bool
    attachment_after_days: int | None
    active: bool


class HolidayOut(ResponseModel):
    date: str
    name: str
    type: Literal["national", "festival", "company"]


class AccrualOut(ResponseModel):
    method: Literal["annual", "monthly", "none"]
    days: float


class CarryForwardOut(ResponseModel):
    allowed: bool
    max_days: float | None


class LeavePolicyOut(ResponseModel):
    id: str
    leave_type: LeaveTypeRefOut
    accrual: AccrualOut
    carry_forward: CarryForwardOut
    effective_from: str
    effective_to: str | None = None
    applies_to: str
    allow_half_day: bool
    attachment_after_days: int | None


# --- Requests -------------------------------------------------------------------------------------------


class LeaveAttachmentOut(ResponseModel):
    id: str
    file_name: str
    size_bytes: int


class ApproverStateOut(ResponseModel):
    type: Literal["reporting_manager", "department_head", "role", "user"]
    name: str


class RoutingEventOut(ResponseModel):
    at: UtcDateTime
    action: Literal["assigned", "reminder_sent", "escalated"]
    detail: str


class WorkflowRefOut(ResponseModel):
    id: str
    name: str


class LeaveApprovalStateOut(ResponseModel):
    workflow: WorkflowRefOut | None
    stage: Literal["first_level", "escalated", "completed", "withdrawn"]
    current_approver: ApproverStateOut | None
    escalation_due_at: UtcDateTime | None
    escalation: Literal["not_configured", "on_track", "due_soon", "overdue", "escalated", "not_applicable"]
    escalated_at: UtcDateTime | None
    events: list[RoutingEventOut]


class LeaveRequestOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    leave_type: LeaveTypeRefOut
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    portion: Portion
    days: float
    reason: str
    status: RequestStatus
    attachments: list[LeaveAttachmentOut]
    submitted_at: UtcDateTime
    submitted_by: str
    reviewed_by: str | None = None
    reviewed_at: UtcDateTime | None = None
    review_comment: str | None = None
    history: list[WorkflowEventOut]
    version: int
    approval: LeaveApprovalStateOut | None = None


class ExcludedDateOut(ResponseModel):
    date: str
    reason: str


class OverlapOut(ResponseModel):
    id: str
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    status: RequestStatus
    leave_type_name: str


class LeaveEstimateOut(ResponseModel):
    days: float
    excluded_dates: list[ExcludedDateOut]
    available_before: float | None
    overlapping: list[OverlapOut]
    warnings: list[str]


class CancellationIn(CamelModel):
    version: int
    comment: str | None = Field(default=None, max_length=1000)


class CommentIn(CamelModel):
    comment: str = Field(max_length=2000)
    version: int


# --- Balances -------------------------------------------------------------------------------------------------


class LeaveBalanceOut(ResponseModel):
    leave_type: LeaveTypeRefOut
    allocated: float | None
    carried_forward: float
    used: float
    pending: float
    available: float | None


class EmployeeBalancesOut(ResponseModel):
    employee: EmployeeRefOut
    balances: list[LeaveBalanceOut]


# --- Summary ------------------------------------------------------------------------------------------------------


class OnLeaveTodayOut(ResponseModel):
    employee: EmployeeRefOut
    leave_type_name: str
    to: str
    portion: Portion


class UpcomingLeaveOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    leave_type_name: str
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    days: float


class LowBalanceOut(ResponseModel):
    employee: EmployeeRefOut
    leave_type_name: str
    available: float


class LeaveSummaryOut(ResponseModel):
    on_leave_today: list[OnLeaveTodayOut]
    pending_requests: int
    upcoming: list[UpcomingLeaveOut]
    upcoming_window_days: int
    awaiting_my_action: int
    low_balances: list[LowBalanceOut]
    low_balance_threshold: float
    as_of: UtcDateTime


# --- Leave approval workflows (H3) ----------------------------------------------------------------------------------


class ApproverRefModel(CamelModel):
    type: Literal["role", "user"]
    id: str = Field(max_length=100)
    name: str = Field(max_length=200)


class EscalationModel(CamelModel):
    enabled: bool
    after: int | None = None
    unit: DeadlineUnit = "hours"
    reminder_hours_before: int | None = None
    recipient: ApproverRefModel | None = None


class NotificationsModel(CamelModel):
    on_submit: bool
    before_deadline: bool
    on_escalation: bool
    on_decision: bool


class LeaveWorkflowIn(CamelModel):
    name: str = Field(max_length=200)
    status: Literal["draft", "active", "inactive"]
    scope: Literal["company", "departments"]
    department_ids: list[str] = Field(default_factory=list, max_length=500)
    first_approver: FirstApprover
    fallback_approver: ApproverRefModel | None = None
    escalation: EscalationModel
    notifications: NotificationsModel
    effective_from: str = Field(max_length=10)
    effective_to: str | None = Field(default=None, max_length=10)
    version: int | None = None


class LeaveWorkflowHistoryOut(ResponseModel):
    version: int
    at: UtcDateTime
    by: str
    action: Literal["created", "updated", "activated", "deactivated"]
    note: str | None


class ApproverRefOut(ResponseModel):
    type: Literal["role", "user"]
    id: str
    name: str


class EscalationOut(ResponseModel):
    enabled: bool
    after: int | None
    unit: DeadlineUnit
    reminder_hours_before: int | None
    recipient: ApproverRefOut | None


class NotificationsOut(ResponseModel):
    on_submit: bool
    before_deadline: bool
    on_escalation: bool
    on_decision: bool


class LeaveWorkflowOut(ResponseModel):
    id: str
    name: str
    status: Literal["draft", "active", "inactive"]
    scope: Literal["company", "departments"]
    departments: list[NamedRefOut]
    first_approver: FirstApprover
    fallback_approver: ApproverRefOut | None
    escalation: EscalationOut
    notifications: NotificationsOut
    effective_from: str
    effective_to: str | None
    history: list[LeaveWorkflowHistoryOut]
    version: int
    updated_at: UtcDateTime
    updated_by: str


class LeaveWorkflowOptionsOut(ResponseModel):
    roles: list[NamedRefOut]
    users: list[NamedRefOut]
    working_days: list[int]


# --- Part B: permission and overtime requests -------------------------------------------------------------------------


class PermissionRequestOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    date: str
    from_: str = Field(alias="from", serialization_alias="from")
    to: str
    minutes: int
    reason: str
    status: RequestStatus
    submitted_at: UtcDateTime
    submitted_by: str
    reviewed_by: str | None = None
    review_comment: str | None = None
    history: list[WorkflowEventOut]
    version: int


class PermissionIn(CamelModel):
    employee_id: str | None = None
    date: str = Field(max_length=10)
    from_: str = Field(alias="from", max_length=5)
    to: str = Field(max_length=5)
    reason: str = Field(max_length=2000)


class OvertimeRequestOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    date: str
    minutes: int
    recorded_minutes: int | None
    reason: str
    status: RequestStatus
    submitted_at: UtcDateTime
    submitted_by: str
    reviewed_by: str | None = None
    review_comment: str | None = None
    history: list[WorkflowEventOut]
    version: int


class OvertimeIn(CamelModel):
    employee_id: str | None = None
    date: str = Field(max_length=10)
    minutes: int
    reason: str = Field(max_length=2000)


# --- Approval inbox (E3) ---------------------------------------------------------------------------------------------

ApprovalType = Literal["leave", "permission", "overtime", "attendance_correction"]


class ApprovalItemOut(ResponseModel):
    id: str
    type: ApprovalType
    request_id: str
    employee: EmployeeRefOut
    summary: str
    date: str
    submitted_at: UtcDateTime
    version: int


class ApprovalCountsOut(ResponseModel):
    """Keyed by ApprovalType values (`Record<ApprovalType, number>`), so not camelCased."""

    leave: int
    permission: int
    overtime: int
    attendance_correction: int = Field(alias="attendance_correction", serialization_alias="attendance_correction")


class ApprovalInboxOut(Page[ApprovalItemOut]):
    counts: ApprovalCountsOut


# --- HR setup (additions; no frontend screen) ---------------------------------------------------------------------------


class LeaveTypeIn(CamelModel):
    code: str = Field(max_length=20)
    name: str = Field(max_length=200)
    paid: bool
    allow_half_day: bool = False
    balance_tracked: bool
    attachment_after_days: int | None = None
    active: bool = True
    version: int | None = None


class LeavePolicyIn(CamelModel):
    leave_type_id: str
    accrual_method: Literal["annual", "monthly", "none"]
    accrual_days: float = 0
    carry_forward_allowed: bool = False
    carry_forward_max_days: float | None = None
    effective_from: str = Field(max_length=10)
    effective_to: str | None = Field(default=None, max_length=10)
    employment_type_ids: list[str] = Field(default_factory=list, max_length=100)
    department_ids: list[str] = Field(default_factory=list, max_length=500)
    allow_half_day: bool | None = None
    attachment_after_days: int | None = None
    version: int | None = None


class LeavePolicySetupOut(LeavePolicyOut):
    employment_type_ids: list[str]
    department_ids: list[str]
    version: int


class HolidayIn(CamelModel):
    date: str = Field(max_length=10)
    name: str = Field(max_length=200)
    type: Literal["national", "festival", "company"]
    work_location_id: str | None = None
    version: int | None = None


class HolidaySetupOut(HolidayOut):
    id: str
    location: NamedRefOut | None
    version: int


class LedgerEntryIn(CamelModel):
    employee_id: str
    leave_type_id: str
    year: int
    days: float
    reason: str = Field(max_length=1000)


class LedgerEntryOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    leave_type: LeaveTypeRefOut
    year: int
    entry_type: Literal["allocation", "accrual", "carry_forward", "lapse", "usage", "usage_reversal", "adjustment"]
    days: float
    leave_request_id: str | None
    reason: str | None
    created_at: UtcDateTime
    created_by: str


class NotificationOut(ResponseModel):
    id: str
    category: str
    title: str
    status: Literal["pending", "delivered", "failed"]
    attempts: int
    next_attempt_at: UtcDateTime | None
    delivered_at: UtcDateTime | None
    last_error: str | None
    created_at: UtcDateTime


class NotificationOutboxOut(ResponseModel):
    delivery_configured: bool
    pending: int
    failed: int
    delivered: int
    recent: list[NotificationOut]
