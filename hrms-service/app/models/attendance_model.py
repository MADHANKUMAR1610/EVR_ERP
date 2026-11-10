"""Time & attendance (Module 5): HR settings, approval workflows, shift assignments, devices, events,
calculated days, corrections, period locks and the generic background job queue."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


# --- HR policies (contract G6) --------------------------------------------------------------------


class PolicySetting(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """Values of one policy area from `effective_from` on. The newest row on or before a date applies."""

    __tablename__ = "policy_setting"

    area: Mapped[str] = mapped_column(String(20), nullable=False)
    values: Mapped[dict] = mapped_column(JSONB, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (UniqueConstraint("area", "effective_from"),)


# --- Approval workflows (contract G5) ---------------------------------------------------------------

WORKFLOW_PROCESSES = ("leave", "attendance_correction", "overtime", "payroll", "performance_review")
WORKFLOW_STATUSES = ("draft", "published", "archived")


class Workflow(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """The editable workflow. `published` holds the version in force (steps frozen at publication)."""

    __tablename__ = "workflow"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    process: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    steps: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    # {version, effectiveFrom, effectiveTo, steps} of the published version, or null.
    published: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))

    __table_args__ = (
        CheckConstraint(_in("process", WORKFLOW_PROCESSES), name="process"),
        CheckConstraint(_in("status", WORKFLOW_STATUSES), name="status"),
        CheckConstraint("effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from", name="dates"),
    )


class WorkflowHistory(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Publication and archive history (append-only)."""

    __tablename__ = "workflow_history"

    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow.id", ondelete="RESTRICT"), nullable=False, index=True)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


# --- Shift assignments ------------------------------------------------------------------------------


class ShiftAssignment(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """The employee works `shift_id` from `effective_from` until the next assignment."""

    __tablename__ = "shift_assignment"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    shift_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shift.id", ondelete="RESTRICT"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)

    __table_args__ = (UniqueConstraint("employee_id", "effective_from"), Index("ix_shift_assignment_shift", "shift_id"))


class ShiftAssignmentChange(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Append-only record of every assignment: old and new shift, effective date, reason, affected days."""

    __tablename__ = "shift_assignment_change"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False, index=True)
    old_shift_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("shift.id", ondelete="RESTRICT"))
    new_shift_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shift.id", ondelete="RESTRICT"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    backdated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500))
    affected_from: Mapped[date | None] = mapped_column(Date)
    affected_to: Mapped[date | None] = mapped_column(Date)
    affected_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (CheckConstraint("NOT backdated OR reason IS NOT NULL", name="backdated_needs_reason"),)


# --- Devices and events -----------------------------------------------------------------------------

CONNECTIONS = ("online", "offline", "error", "not_connected")
SYNC_RESULTS = ("success", "partial", "failed")


class AttendanceDevice(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "attendance_device"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    work_location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_location.id", ondelete="RESTRICT"))
    serial_number: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    # SHA-256 of the device API key; the key itself is shown once when issued and never stored.
    key_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_result: Mapped[str | None] = mapped_column(String(10))
    records_last_sync: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (CheckConstraint(f"last_sync_result IS NULL OR {_in('last_sync_result', SYNC_RESULTS)}", name="last_sync_result"),)


class DeviceSyncRun(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "device_sync_run"

    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("attendance_device.id", ondelete="RESTRICT"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(String(10), nullable=False)
    events_received: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (CheckConstraint(_in("result", SYNC_RESULTS), name="result"), Index("ix_device_sync_run_device_started", "device_id", "started_at"))


EVENT_SOURCES = ("fingerprint", "mobile_app")
SYNC_STATUSES = ("synced", "pending", "delayed", "failed")
PROCESSING_STATUSES = ("accepted", "duplicate", "rejected", "pending")


class AttendanceEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """A raw punch as received (append-only). Only `accepted` events count towards attendance."""

    __tablename__ = "attendance_event"

    employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"))
    reported_attendance_id: Mapped[str] = mapped_column(String(30), nullable=False)
    attendance_date: Mapped[date | None] = mapped_column(Date)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("attendance_device.id", ondelete="RESTRICT"))
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("device_sync_run.id", ondelete="RESTRICT"))
    app_reference: Mapped[str | None] = mapped_column(String(100))
    original_reference: Mapped[str | None] = mapped_column(String(100))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sync_status: Mapped[str] = mapped_column(String(10), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(10), nullable=False)
    exception: Mapped[str | None] = mapped_column(String(200))
    original_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("attendance_event.id", ondelete="RESTRICT"))
    warnings: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    mobile_validation: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        CheckConstraint("direction IN ('in', 'out')", name="direction"),
        CheckConstraint(_in("source", EVENT_SOURCES), name="source"),
        CheckConstraint(_in("sync_status", SYNC_STATUSES), name="sync_status"),
        CheckConstraint(_in("processing_status", PROCESSING_STATUSES), name="processing_status"),
        Index("uq_attendance_event_device_reference", "device_id", "original_reference", unique=True, postgresql_where=text("device_id IS NOT NULL AND original_reference IS NOT NULL")),
        Index("ix_attendance_event_employee_date", "employee_id", "attendance_date"),
        Index("ix_attendance_event_date", "attendance_date"),
    )


# --- Calculated days, corrections, locks --------------------------------------------------------------

DAY_STATUSES = ("present", "late", "half_day", "absent", "on_leave", "weekly_off", "holiday", "missing_punch", "not_started")


class AttendanceDay(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Stored result of the calculation for a finished day (written by the worker; never edited by hand)."""

    __tablename__ = "attendance_day"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(15), nullable=False)
    shift_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("shift.id", ondelete="RESTRICT"))
    first_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worked_minutes: Mapped[int | None] = mapped_column(Integer)
    late_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    early_exit_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overtime_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    beyond_shift_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exceptions: Mapped[list[str]] = mapped_column(ARRAY(String(20)), nullable=False, default=list)
    warnings: Mapped[list[str]] = mapped_column(ARRAY(String(30)), nullable=False, default=list)
    corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("employee_id", "date"), CheckConstraint(_in("status", DAY_STATUSES), name="status"), Index("ix_attendance_day_date", "date"))


REQUEST_STATUSES = ("pending", "approved", "rejected", "cancelled")


class AttendanceCorrection(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A correction request and its workflow state (steps copied from the workflow version in force)."""

    __tablename__ = "attendance_correction"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    original_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
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

    __table_args__ = (
        CheckConstraint(_in("status", REQUEST_STATUSES), name="status"),
        CheckConstraint("requested_in IS NOT NULL OR requested_out IS NOT NULL", name="something_requested"),
        CheckConstraint("requested_in IS NULL OR requested_out IS NULL OR requested_out > requested_in", name="out_after_in"),
        Index("uq_attendance_correction_pending", "employee_id", "date", unique=True, postgresql_where=text("status = 'pending'")),
        Index("ix_attendance_correction_status", "status", "created_at"),
    )


CORRECTION_ACTIONS = ("submitted", "approved", "rejected", "cancelled", "updated", "commented", "escalated")


class AttendanceCorrectionEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Approval history of a correction (append-only)."""

    __tablename__ = "attendance_correction_event"

    correction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("attendance_correction.id", ondelete="RESTRICT"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    step_name: Mapped[str | None] = mapped_column(String(120))
    comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint(_in("action", CORRECTION_ACTIONS), name="action"),)


class AttendanceLockPeriod(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Dates whose attendance may no longer change (a finalized payroll period)."""

    __tablename__ = "attendance_lock_period"

    from_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)

    __table_args__ = (CheckConstraint("to_date >= from_date", name="dates"),)


# --- Generic background jobs (worker) -----------------------------------------------------------------------

BACKGROUND_JOB_STATUSES = ("queued", "running", "succeeded", "failed")


class BackgroundJob(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """Queue for worker tasks other than employee imports (attendance recalculation, day close, escalation)."""

    __tablename__ = "background_job"

    type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Prevents the same scheduled job from being queued twice (e.g. "close-day:2026-11-02").
    dedupe_key: Mapped[str | None] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONB)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (CheckConstraint(_in("status", BACKGROUND_JOB_STATUSES), name="status"), Index("ix_background_job_status_created", "status", "created_at"))


