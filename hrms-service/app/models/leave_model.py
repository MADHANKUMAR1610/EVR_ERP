"""Leave management (Module 6): types, policies, holidays, the balance ledger, leave requests with their
history and routing, leave approval workflows (contract H3), permission and overtime requests (Part B),
and the notification outbox."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


# --- Configuration --------------------------------------------------------------------------------------


class LeaveType(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "leave_type"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    paid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    allow_half_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    balance_tracked: Mapped[bool] = mapped_column(Boolean, nullable=False)
    attachment_after_days: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (CheckConstraint("code ~ '^[A-Za-z0-9_-]{1,20}$'", name="code_format"), CheckConstraint("attachment_after_days IS NULL OR attachment_after_days >= 0", name="attachment_days"))


ACCRUAL_METHODS = ("annual", "monthly", "none")


class LeavePolicy(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """Entitlement rules of a leave type, entered by HR, effective-dated. Applicability: employment types
    and/or departments (empty = everyone)."""

    __tablename__ = "leave_policy"

    leave_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_type.id", ondelete="RESTRICT"), nullable=False, index=True)
    accrual_method: Mapped[str] = mapped_column(String(10), nullable=False)
    accrual_days: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    carry_forward_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    carry_forward_max_days: Mapped[float | None] = mapped_column(Numeric(6, 2))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    employment_type_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    department_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    allow_half_day: Mapped[bool | None] = mapped_column(Boolean)
    attachment_after_days: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(_in("accrual_method", ACCRUAL_METHODS), name="accrual_method"),
        CheckConstraint("accrual_days >= 0", name="accrual_days"),
        CheckConstraint("accrual_method <> 'none' OR accrual_days = 0", name="none_has_no_days"),
        CheckConstraint("carry_forward_max_days IS NULL OR carry_forward_max_days >= 0", name="carry_forward_max"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="dates"),
    )


HOLIDAY_TYPES = ("national", "festival", "company")


class Holiday(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A company-wide holiday (no location) or a location-specific one (owner decision 4)."""

    __tablename__ = "holiday"

    date: Mapped[date] = mapped_column(Date, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    work_location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_location.id", ondelete="RESTRICT"))

    __table_args__ = (
        CheckConstraint(_in("type", HOLIDAY_TYPES), name="type"),
        Index("uq_holiday_company_date", "date", unique=True, postgresql_where=text("work_location_id IS NULL")),
        Index("uq_holiday_location_date", "date", "work_location_id", unique=True, postgresql_where=text("work_location_id IS NOT NULL")),
    )


# --- Balance ledger -----------------------------------------------------------------------------------------

LEDGER_TYPES = ("allocation", "accrual", "carry_forward", "lapse", "usage", "usage_reversal", "adjustment")


class LeaveLedgerEntry(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """One balance transaction (append-only). Balances are sums of these; nothing is edited."""

    __tablename__ = "leave_ledger_entry"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    leave_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_type.id", ondelete="RESTRICT"), nullable=False)
    leave_year: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(15), nullable=False)
    days: Mapped[float] = mapped_column(Numeric(7, 2), nullable=False)
    leave_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_request.id", ondelete="RESTRICT"))
    leave_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_policy.id", ondelete="RESTRICT"))
    reason: Mapped[str | None] = mapped_column(String(500))
    # Makes accrual and carry-forward idempotent (e.g. "accrual:<policy>:2026-03").
    period_key: Mapped[str | None] = mapped_column(String(120))

    __table_args__ = (
        CheckConstraint(_in("entry_type", LEDGER_TYPES), name="entry_type"),
        CheckConstraint("entry_type NOT IN ('adjustment', 'allocation') OR reason IS NOT NULL OR period_key IS NOT NULL", name="manual_needs_reason"),
        Index("ix_leave_ledger_employee_year", "employee_id", "leave_type_id", "leave_year"),
        Index("uq_leave_ledger_period", "employee_id", "leave_type_id", "period_key", unique=True, postgresql_where=text("period_key IS NOT NULL")),
    )


# --- Leave approval workflows (contract H3) ---------------------------------------------------------------


class LeaveApprovalWorkflow(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "leave_approval_workflow"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    scope: Mapped[str] = mapped_column(String(12), nullable=False)
    department_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    first_approver: Mapped[str] = mapped_column(String(20), nullable=False)
    fallback_approver: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))  # {type, id, name}
    escalation: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {enabled, after, unit, reminderHoursBefore, recipient}
    notifications: Mapped[dict] = mapped_column(JSONB, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'inactive')", name="status"),
        CheckConstraint("scope IN ('company', 'departments')", name="scope"),
        CheckConstraint("first_approver IN ('reporting_manager', 'department_head')", name="first_approver"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="dates"),
    )


class LeaveWorkflowHistory(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Append-only history of a leave workflow (created, updated, activated, deactivated)."""

    __tablename__ = "leave_workflow_history"

    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_approval_workflow.id", ondelete="RESTRICT"), nullable=False, index=True)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


# --- Leave requests ------------------------------------------------------------------------------------------------

REQUEST_STATUSES = ("pending", "approved", "rejected", "cancelled")
PORTIONS = ("full", "first_half", "second_half")


class LeaveRequest(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A leave application. Routing is fixed at submission (owner decision 1: never re-routed)."""

    __tablename__ = "leave_request"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    leave_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_type.id", ondelete="RESTRICT"), nullable=False)
    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    portion: Mapped[str] = mapped_column(String(12), nullable=False)
    days: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False)
    # {leave_year: days} charged per leave year (a request may cross a leave-year boundary).
    days_by_year: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # The dates charged (weekly offs and holidays excluded unless countOffsWithinLeave was on); the
    # attendance calculation shows exactly these as on_leave / half_day.
    charged_dates: Mapped[list[date]] = mapped_column(ARRAY(Date), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    # Routing snapshot (H3), fixed at submission.
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_approval_workflow.id", ondelete="RESTRICT"))
    workflow_snapshot: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    approver_kind: Mapped[str | None] = mapped_column(String(20))  # reporting_manager | department_head | role | user
    approver_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"))
    approver_ref: Mapped[str | None] = mapped_column(String(100))  # role code or user id
    approver_name: Mapped[str | None] = mapped_column(String(200))
    # Escalation recipient (role or user), copied from the workflow at submission.
    recipient_kind: Mapped[str | None] = mapped_column(String(10))
    recipient_ref: Mapped[str | None] = mapped_column(String(100))
    recipient_name: Mapped[str | None] = mapped_column(String(200))
    escalation_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stage: Mapped[str] = mapped_column(String(12), nullable=False, default="first_level")
    reviewed_by_name: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint(_in("status", REQUEST_STATUSES), name="status"),
        CheckConstraint(_in("portion", PORTIONS), name="portion"),
        CheckConstraint("to_date >= from_date", name="dates"),
        CheckConstraint("portion = 'full' OR from_date = to_date", name="half_day_single"),
        CheckConstraint("days > 0", name="days_positive"),
        CheckConstraint("stage IN ('first_level', 'escalated', 'completed', 'withdrawn')", name="stage"),
        Index("ix_leave_request_employee_dates", "employee_id", "from_date", "to_date"),
        Index("ix_leave_request_status_created", "status", "created_at"),
    )


class LeaveRequestAttachment(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Metadata of an attachment; the file is in encrypted private storage (as Module 3 documents)."""

    __tablename__ = "leave_request_attachment"

    leave_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_request.id", ondelete="RESTRICT"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)


REQUEST_KINDS = ("leave", "permission", "overtime")
EVENT_ACTIONS = ("submitted", "approved", "rejected", "cancelled", "updated", "commented")


class RequestEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """History of leave, permission and overtime requests (WorkflowEvent, append-only)."""

    __tablename__ = "request_event"

    request_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint(_in("request_kind", REQUEST_KINDS), name="request_kind"), CheckConstraint(_in("action", EVENT_ACTIONS), name="action"), Index("ix_request_event_request", "request_kind", "request_id", "created_at"))


class LeaveRoutingEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Routing events of a leave request: assigned, reminder_sent, escalated (append-only)."""

    __tablename__ = "leave_routing_event"

    leave_request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leave_request.id", ondelete="RESTRICT"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(15), nullable=False)
    detail: Mapped[str] = mapped_column(String(500), nullable=False)

    __table_args__ = (CheckConstraint("action IN ('assigned', 'reminder_sent', 'escalated')", name="action"),)


# --- Part B: permission (short absence) and overtime requests ----------------------------------------------------


class PermissionRequest(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "permission_request"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    from_time: Mapped[str] = mapped_column(String(5), nullable=False)
    to_time: Mapped[str] = mapped_column(String(5), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    reviewed_by_name: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint(_in("status", REQUEST_STATUSES), name="status"), CheckConstraint("to_time > from_time AND minutes > 0", name="times"), Index("ix_permission_request_employee_date", "employee_id", "date"))


class OvertimeRequest(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """Overtime claim (time only; any pay is calculated by payroll). Approval may use a G5 workflow."""

    __tablename__ = "overtime_request"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow.id", ondelete="RESTRICT"))
    workflow_version: Mapped[int | None] = mapped_column(Integer)
    steps: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    current_step: Mapped[int | None] = mapped_column(Integer)
    step_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint(_in("status", REQUEST_STATUSES), name="status"), CheckConstraint("minutes BETWEEN 1 AND 960", name="minutes"), Index("ix_overtime_request_employee_date", "employee_id", "date"))


# --- Notifications (to the Platform service) ------------------------------------------------------------------------


class NotificationOutbox(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Written in the same transaction as the change it reports; delivered by the worker with retries."""

    __tablename__ = "notification_outbox"

    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    link: Mapped[str | None] = mapped_column(String(300))
    employee_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    user_ids: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False, default=list)
    role_codes: Mapped[list[str]] = mapped_column(ARRAY(String(100)), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (CheckConstraint("status IN ('pending', 'delivered', 'failed')", name="status"), Index("ix_notification_outbox_status", "status", "next_attempt_at"))


