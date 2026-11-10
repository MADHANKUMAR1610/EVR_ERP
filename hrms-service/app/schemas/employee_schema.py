"""Employees (frontend employees.service.ts and admin.service.ts ReportingLine). Field names match exactly.

Inputs carry only loose type and size limits; the service applies the frontend form's rules and
messages, so every problem is reported on the field path the form shows.
"""

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel, ResponseModel, UtcDateTime
from app.schemas.reference_data_schema import Tone


# --- Shared --------------------------------------------------------------------------------------


class NamedRefOut(ResponseModel):
    id: str
    name: str


class StatusRefOut(ResponseModel):
    code: str
    label: str
    tone: Tone


# --- Directory -----------------------------------------------------------------------------------


class EmployeeListItemOut(ResponseModel):
    id: str
    employee_code: str
    full_name: str
    photo_url: str | None = None
    department: NamedRefOut
    designation: NamedRefOut
    employment_type: NamedRefOut
    status: StatusRefOut
    joining_date: str
    reporting_manager: NamedRefOut | None
    email: str | None
    mobile: str | None


# --- Record --------------------------------------------------------------------------------------


class AddressModel(CamelModel):
    line1: str | None = Field(default=None, max_length=500)
    line2: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=500)
    state: str | None = Field(default=None, max_length=500)
    postal_code: str | None = Field(default=None, max_length=500)
    country: str | None = Field(default=None, max_length=500)


class EmergencyContactModel(CamelModel):
    name: str | None = Field(default=None, max_length=500)
    relationship: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=500)


class PersonalOut(ResponseModel):
    first_name: str
    middle_name: str | None
    last_name: str | None
    date_of_birth: str | None
    mobile: str | None
    email: str | None
    address: AddressModel | None
    emergency_contact: EmergencyContactModel | None


class ProbationModel(CamelModel):
    applicable: bool = False
    end_date: str | None = None
    confirmation_date: str | None = None


class EmploymentOut(ResponseModel):
    joining_date: str
    department_id: str
    designation_id: str
    employment_type_id: str
    status_code: str
    reporting_manager_id: str | None
    work_location_id: str | None
    probation: ProbationModel


class WorkModel(CamelModel):
    attendance_id: str | None = Field(default=None, max_length=500)
    shift_id: str | None = None
    attendance_policy_id: str | None = None
    overtime_policy_id: str | None = None


class PayrollOut(ResponseModel):
    values: dict[str, str | None]


class DisplayOut(ResponseModel):
    full_name: str
    department: str
    designation: str
    employment_type: str
    status: StatusRefOut
    reporting_manager: NamedRefOut | None
    work_location: str | None
    shift: str | None
    attendance_policy: str | None
    overtime_policy: str | None


class RestrictedOut(ResponseModel):
    contact: bool
    payroll: bool


class AuditInfoOut(ResponseModel):
    created_at: UtcDateTime
    created_by: str
    updated_at: UtcDateTime
    updated_by: str


class EmployeeOut(ResponseModel):
    id: str
    employee_code: str
    version: int
    personal: PersonalOut
    employment: EmploymentOut
    work: WorkModel
    payroll: PayrollOut | None
    display: DisplayOut
    restricted: RestrictedOut
    audit: AuditInfoOut


# --- Create / update -------------------------------------------------------------------------------


class PersonalIn(CamelModel):
    first_name: str = Field(max_length=500)
    middle_name: str | None = Field(default=None, max_length=500)
    last_name: str | None = Field(default=None, max_length=500)
    date_of_birth: str | None = None
    # Contact keys: omitted = unchanged (callers without view-contact never send them).
    mobile: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=500)
    address: AddressModel | None = None
    emergency_contact: EmergencyContactModel | None = None


class EmploymentIn(CamelModel):
    joining_date: str
    department_id: str
    designation_id: str
    employment_type_id: str
    status_code: str
    reporting_manager_id: str | None = None
    work_location_id: str | None = None
    probation: ProbationModel | None = None


class EmployeeUpsertIn(CamelModel):
    employee_code: str = Field(max_length=500)
    personal: PersonalIn
    employment: EmploymentIn
    work: WorkModel = Field(default_factory=WorkModel)
    payroll: dict[str, str] | None = None
    version: int | None = None


class StatusChangeIn(CamelModel):
    to_status: str = Field(max_length=100)
    effective_date: str = Field(max_length=20)
    reason: str | None = Field(default=None, max_length=5000)
    version: int


# --- Lookup and history ----------------------------------------------------------------------------


class EmployeeLookupItemOut(ResponseModel):
    id: str
    employee_code: str
    full_name: str
    department: str


class HistoryEntryOut(ResponseModel):
    id: str
    at: UtcDateTime
    actor: NamedRefOut
    action: Literal["created", "updated", "status_changed", "document_uploaded", "imported"]
    summary: str
    comment: str | None = None
    effective_date: str | None = None
    changes: list[str] | None = None
    from_status: str | None = None
    to_status: str | None = None


# --- Reporting lines (Administration → Organization) -----------------------------------------------


class EmployeeBriefOut(ResponseModel):
    id: str
    employee_code: str
    full_name: str


class ReportingLineOut(ResponseModel):
    employee: EmployeeBriefOut
    department: NamedRefOut
    designation: NamedRefOut
    manager: EmployeeBriefOut | None
    effective_from: str | None
    direct_reports: int


class ManagerChangeIn(CamelModel):
    manager_id: str | None = None
    effective_from: str = Field(max_length=20)
    reason: str = Field(max_length=5000)


# --- Organizational access scopes (/hr/setup/employee-access-scopes) ------------------------------

ScopeType = Literal["all", "departments", "headed_departments", "reporting_tree", "own_record"]


class AccessScopeIn(CamelModel):
    role_code: str = Field(min_length=1, max_length=100)
    scope_type: ScopeType
    department_ids: list[str] = Field(default_factory=list)
    active: bool = True
    version: int | None = None


class AccessScopeOut(ResponseModel):
    id: str
    role_code: str
    scope_type: ScopeType
    departments: list[NamedRefOut]
    active: bool
    version: int
