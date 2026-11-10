"""Time & attendance (frontend attendance.service.ts, contract E1 / H1 / H2). Field names match exactly."""

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel, ResponseModel, UtcDateTime
from app.schemas.employee_schema import NamedRefOut

Status = Literal["present", "late", "half_day", "absent", "on_leave", "weekly_off", "holiday", "missing_punch", "not_started"]
Exception_ = Literal["late_arrival", "early_exit", "missing_in", "missing_out", "absent", "pending_correction"]
Source = Literal["fingerprint", "mobile_app"]
PunchSource = Literal["fingerprint", "mobile_app", "correction"]
Warning_ = Literal["duplicate_event", "delayed_sync", "missing_punch", "rejected_event"]
RequestStatus = Literal["pending", "approved", "rejected", "cancelled"]


class EmployeeRefOut(ResponseModel):
    id: str
    employee_code: str
    full_name: str
    department: NamedRefOut


class ShiftRefOut(ResponseModel):
    id: str
    code: str
    name: str
    start: str
    end: str
    overnight: bool


class DailyRecordOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    date: str
    shift: ShiftRefOut | None
    status: Status
    first_in: UtcDateTime | None
    last_out: UtcDateTime | None
    worked_minutes: int | None
    late_minutes: int
    early_exit_minutes: int
    overtime_minutes: int
    exceptions: list[Exception_]
    corrected: bool
    leave_type_name: str | None = None
    holiday_name: str | None = None
    in_source: PunchSource | None = None
    out_source: PunchSource | None = None
    warnings: list[Warning_] = Field(default_factory=list)


class PunchOut(ResponseModel):
    at: UtcDateTime
    direction: Literal["in", "out"]
    source: PunchSource
    device_name: str | None = None
    event_id: str | None = None


class MobileValidationOut(ResponseModel):
    status: Literal["accepted", "rejected", "pending_review"]
    message: str | None
    checks: list[dict]
    checked_at: UtcDateTime | None


class AttendanceEventOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    attendance_date: str
    at: UtcDateTime
    direction: Literal["in", "out"]
    source: Source
    device_id: str | None
    device_name: str | None
    app_reference: str | None
    location: str | None
    received_at: UtcDateTime | None
    sync_status: Literal["synced", "pending", "delayed", "failed"]
    processing_status: Literal["accepted", "duplicate", "rejected", "pending"]
    exception: str | None
    original_event_id: str | None
    original_reference: str | None
    warnings: list[Warning_]
    mobile_validation: MobileValidationOut | None


class AttendanceEventDetailOut(AttendanceEventOut):
    record: DailyRecordOut | None


class WorkflowEventOut(ResponseModel):
    id: str
    action: Literal["submitted", "approved", "rejected", "cancelled", "updated", "commented"]
    at: UtcDateTime
    by: str
    comment: str | None = None


class PunchPairOut(ResponseModel):
    in_: UtcDateTime | None = Field(alias="in", serialization_alias="in")
    out: UtcDateTime | None


class CorrectionOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    date: str
    original: PunchPairOut
    requested: PunchPairOut
    reason: str
    status: RequestStatus
    submitted_at: UtcDateTime
    submitted_by: str
    reviewed_by: str | None = None
    reviewed_at: UtcDateTime | None = None
    review_comment: str | None = None
    history: list[WorkflowEventOut]
    version: int


class DailyDetailOut(DailyRecordOut):
    punches: list[PunchOut]
    corrections: list[CorrectionOut]
    events: list[AttendanceEventOut] = Field(default_factory=list)


class CalendarDayOut(ResponseModel):
    date: str
    status: Status
    shift: ShiftRefOut | None
    first_in: UtcDateTime | None
    last_out: UtcDateTime | None
    worked_minutes: int | None
    late_minutes: int
    overtime_minutes: int
    exceptions: list[Exception_]
    corrected: bool
    pending_correction: bool
    leave_type_name: str | None
    holiday_name: str | None
    sources: list[PunchSource]
    warnings: list[Warning_]


class CalendarSummaryOut(ResponseModel):
    present_days: int
    absent_days: int
    late_arrivals: int
    half_days: int
    approved_leave_days: float
    weekly_offs: int
    holidays: int
    missing_punch_days: int
    pending_corrections: int
    worked_minutes: int | None


class CalendarEmployeeOut(EmployeeRefOut):
    designation: str | None
    joining_date: str | None


class CalendarOut(ResponseModel):
    employee: CalendarEmployeeOut
    month: str
    days: list[CalendarDayOut]
    summary: CalendarSummaryOut
    as_of: UtcDateTime


class DepartmentAttendanceOut(ResponseModel):
    department: NamedRefOut
    expected: int
    present: int
    late: int
    absent: int
    on_leave: int
    missing_punches: int


class SummaryOut(ResponseModel):
    date: str
    active_employees: int
    present: int
    absent: int
    late: int
    on_leave: int
    missing_punches: int
    weekly_off_or_holiday: int
    not_started: int
    pending_corrections: int
    by_department: list[DepartmentAttendanceOut]
    exceptions: list[DailyRecordOut]
    recent_corrections: list[CorrectionOut]
    as_of: UtcDateTime


class MonthlyRowOut(ResponseModel):
    employee: EmployeeRefOut
    month: str
    present: int
    absent: int
    leave: float
    weekly_off: int
    holiday: int
    late: int
    missing_punches: int
    worked_minutes: int
    overtime_minutes: int


class MonthlyDayOut(ResponseModel):
    date: str
    status: Status
    first_in: UtcDateTime | None
    last_out: UtcDateTime | None
    worked_minutes: int | None
    exceptions: list[Exception_]
    corrected: bool
    leave_type_name: str | None
    holiday_name: str | None


class MonthlyDetailOut(MonthlyRowOut):
    days: list[MonthlyDayOut]


class DeviceSyncRunOut(ResponseModel):
    id: str
    started_at: UtcDateTime
    finished_at: UtcDateTime | None
    result: Literal["success", "partial", "failed"]
    events_received: int
    message: str | None


class DeviceOut(ResponseModel):
    id: str
    name: str
    location: str
    serial_number: str | None = None
    connection: Literal["online", "offline", "error", "not_connected"]
    last_sync_at: UtcDateTime | None
    last_sync_result: Literal["success", "partial", "failed"] | None = None
    records_last_sync: int | None = None
    error_message: str | None = None


class DeviceListOut(ResponseModel):
    items: list[DeviceOut]
    integration_configured: bool
    as_of: UtcDateTime


# --- Inputs ---------------------------------------------------------------------------------------------


class CorrectionIn(CamelModel):
    employee_id: str
    date: str = Field(max_length=10)
    requested_in: str | None = Field(default=None, max_length=40)
    requested_out: str | None = Field(default=None, max_length=40)
    reason: str = Field(max_length=2000)


class DecisionIn(CamelModel):
    decision: Literal["approve", "reject"]
    comment: str | None = Field(default=None, max_length=1000)
    version: int


class ShiftAssignmentIn(CamelModel):
    employee_ids: list[str] = Field(min_length=1, max_length=2000)
    effective_from: str = Field(max_length=10)
    # Not sent by the current frontend; required for back-dated assignments (owner decision 2).
    reason: str | None = Field(default=None, max_length=500)


class ShiftAssignmentOut(ResponseModel):
    assigned: int
    effective_from: str
    # Additions (the frontend ignores them): attendance days whose calculation changes.
    affected_attendance_days: int = 0
    backdated: bool = False


class IngestEventIn(CamelModel):
    attendance_id: str = Field(min_length=1, max_length=30)
    at: str = Field(max_length=40)
    direction: Literal["in", "out"]
    reference: str | None = Field(default=None, max_length=100)
    source: Literal["fingerprint", "mobile_app"] = "fingerprint"


class IngestIn(CamelModel):
    events: list[IngestEventIn] = Field(min_length=1, max_length=1000)


class IngestOut(ResponseModel):
    sync_run_id: str
    received: int
    accepted: int
    duplicates: int
    rejected: int
    already_received: int
    result: Literal["success", "partial", "failed"]


class DeviceSetupIn(CamelModel):
    name: str = Field(min_length=2, max_length=120)
    serial_number: str = Field(min_length=1, max_length=100)
    work_location_id: str | None = None
    active: bool = True
    version: int | None = None


class DeviceSetupOut(ResponseModel):
    id: str
    name: str
    serial_number: str
    location: NamedRefOut | None
    active: bool
    key_issued: bool
    version: int


class DeviceKeyOut(ResponseModel):
    device_id: str
    api_key: str  # shown once; only its hash is stored


class LockIn(CamelModel):
    from_date: str
    to_date: str
    reason: str = Field(min_length=3, max_length=300)


class LockOut(ResponseModel):
    id: str
    from_date: str
    to_date: str
    reason: str
    created_at: UtcDateTime
    created_by: str
