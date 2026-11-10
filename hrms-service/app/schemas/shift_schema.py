"""Shifts (frontend `attendance.service.ts`: Shift, ShiftInput)."""

from pydantic import Field

from app.schemas.common import CamelModel, ResponseModel, UtcDateTime
from app.schemas.department_schema import DepartmentRef

HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class ShiftOut(ResponseModel):
    id: str
    code: str
    name: str
    start: str
    end: str
    overnight: bool
    break_minutes: int
    grace_minutes: int
    working_days: list[int]
    departments: list[DepartmentRef]
    active: bool
    assigned_employees: int
    version: int
    updated_at: UtcDateTime
    updated_by: str


class ShiftInput(CamelModel):
    """Limits match the frontend shift form (features/hr/attendance/schemas.ts); the service re-checks the
    cross-field rules and returns the same messages."""

    code: str = Field(max_length=20)
    name: str = Field(max_length=80)
    start: str
    end: str
    overnight: bool
    break_minutes: int
    grace_minutes: int
    working_days: list[int]
    department_ids: list[str] = Field(default_factory=list)
    active: bool = True
    version: int | None = None
