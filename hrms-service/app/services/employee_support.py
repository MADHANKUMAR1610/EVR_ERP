"""Shared pieces of the employee services: caller context, reference tables, dates, response building."""

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.config import get_settings
from app.core.context import Principal
from app.core.errors import ServiceUnavailableError
from app.core.permissions import P, has_permission
from app.models.department_model import Department
from app.models.designation_model import Designation
from app.models.employee_model import Employee, EmployeeContact, EmployeePayrollValue
from app.models.reference_data_model import (
    AttendancePolicyOption,
    EmployeeStatus,
    EmploymentType,
    OvertimePolicyOption,
    PayrollFieldDefinition,
    WorkLocation,
)
from app.models.shift_model import Shift
from app.schemas.employee_schema import (
    AddressModel,
    AuditInfoOut,
    DisplayOut,
    EmergencyContactModel,
    EmployeeListItemOut,
    EmployeeOut,
    EmploymentOut,
    NamedRefOut,
    PayrollOut,
    PersonalOut,
    ProbationModel,
    RestrictedOut,
    StatusRefOut,
    WorkModel,
)
from app.services.employee_scope_service import EmployeeScope, EmployeeScopeService

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def company_today() -> date:
    return datetime.now(ZoneInfo(get_settings().company_time_zone)).date()


def parse_date(value: str | None) -> date | None:
    """ISO date or None. Raises ValueError for anything else."""
    if value is None or value.strip() == "":
        return None
    v = value.strip()
    if not ISO_DATE.match(v):
        raise ValueError(v)
    return date.fromisoformat(v)


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def full_name(first: str, middle: str | None, last: str | None) -> str:
    return " ".join(p for p in (first, middle, last) if p)


@dataclass(frozen=True)
class Caller:
    principal: Principal
    scope: EmployeeScope
    can_contact: bool
    can_sensitive: bool

    def has(self, code: str) -> bool:
        return has_permission(self.principal.permissions, code)


async def caller_context(session: AsyncSession, principal: Principal) -> Caller:
    scope = await EmployeeScopeService(session).resolve(principal)
    return Caller(
        principal=principal,
        scope=scope,
        can_contact=has_permission(principal.permissions, P.EMPLOYEES_VIEW_CONTACT),
        can_sensitive=has_permission(principal.permissions, P.EMPLOYEES_VIEW_SENSITIVE),
    )


class References:
    """The small configuration tables, loaded once per request for validation and display names."""

    def __init__(self) -> None:
        self.departments: dict[uuid.UUID, Department] = {}
        self.designations: dict[uuid.UUID, Designation] = {}
        self.employment_types: dict[uuid.UUID, EmploymentType] = {}
        self.locations: dict[uuid.UUID, WorkLocation] = {}
        self.shifts: dict[uuid.UUID, Shift] = {}
        self.attendance_policies: dict[uuid.UUID, AttendancePolicyOption] = {}
        self.overtime_policies: dict[uuid.UUID, OvertimePolicyOption] = {}
        self.statuses: dict[str, EmployeeStatus] = {}
        self.payroll_fields: dict[str, PayrollFieldDefinition] = {}

    @classmethod
    async def load(cls, session: AsyncSession) -> "References":
        r = cls()

        async def table(model):
            return {row.id: row for row in (await session.scalars(select(model))).all()}

        r.departments = await table(Department)
        r.designations = await table(Designation)
        r.employment_types = await table(EmploymentType)
        r.locations = await table(WorkLocation)
        r.shifts = await table(Shift)
        r.attendance_policies = await table(AttendancePolicyOption)
        r.overtime_policies = await table(OvertimePolicyOption)
        r.statuses = {s.code: s for s in (await session.scalars(select(EmployeeStatus))).all()}
        fields = (await session.scalars(select(PayrollFieldDefinition).order_by(PayrollFieldDefinition.sort_order, PayrollFieldDefinition.label))).all()
        r.payroll_fields = {f.key: f for f in fields}
        return r

    def status_ref(self, code: str) -> StatusRefOut:
        s = self.statuses.get(code)
        return StatusRefOut(code=code, label=s.label if s else code, tone=s.tone if s else "neutral")

    def status_label(self, code: str | None) -> str | None:
        if code is None:
            return None
        s = self.statuses.get(code)
        return s.label if s else code

    @staticmethod
    def name(table: dict, key: uuid.UUID | None) -> str | None:
        item = table.get(key) if key else None
        return item.name if item else None

    def named(self, table: dict, key: uuid.UUID) -> NamedRefOut:
        return NamedRefOut(id=str(key), name=self.name(table, key) or "")


def payroll_out(values: dict[str, EmployeePayrollValue], refs: References) -> PayrollOut:
    """Active payroll fields; sensitive values decrypted only to be masked (B4)."""
    out: dict[str, str | None] = {}
    for key, definition in refs.payroll_fields.items():
        if not definition.active:
            continue
        row = values.get(key)
        if row is None:
            out[key] = None
            continue
        try:
            plain = crypto.decrypt(row.value) if row.encrypted else row.value
        except crypto.EncryptionUnavailableError:
            raise ServiceUnavailableError("Payroll details are unavailable right now.") from None
        out[key] = crypto.mask(plain) if definition.sensitive else plain
    return PayrollOut(values=out)


def contact_parts(c: EmployeeContact | None) -> tuple[AddressModel | None, EmergencyContactModel | None]:
    if c is None:
        return None, None
    address = AddressModel(line1=c.address_line1, line2=c.address_line2, city=c.address_city, state=c.address_state, postal_code=c.address_postal_code, country=c.address_country)
    emergency = EmergencyContactModel(name=c.emergency_name, relationship=c.emergency_relationship, phone=c.emergency_phone)
    has_address = any(v for v in address.model_dump().values())
    has_emergency = any(v for v in emergency.model_dump().values())
    return (address if has_address else None), (emergency if has_emergency else None)


def employee_out(e: Employee, refs: References, caller: Caller, *, manager: Employee | None, contact: EmployeeContact | None, payroll: dict[str, EmployeePayrollValue] | None) -> EmployeeOut:
    address, emergency = contact_parts(contact) if caller.can_contact else (None, None)
    personal = PersonalOut(
        first_name=e.first_name,
        middle_name=e.middle_name,
        last_name=e.last_name,
        date_of_birth=iso(e.date_of_birth),
        mobile=contact.mobile if caller.can_contact and contact else None,
        email=contact.email if caller.can_contact and contact else None,
        address=address,
        emergency_contact=emergency,
    )
    employment = EmploymentOut(
        joining_date=e.joining_date.isoformat(),
        department_id=str(e.department_id),
        designation_id=str(e.designation_id),
        employment_type_id=str(e.employment_type_id),
        status_code=e.status_code,
        reporting_manager_id=str(e.reporting_manager_id) if e.reporting_manager_id else None,
        work_location_id=str(e.work_location_id) if e.work_location_id else None,
        probation=ProbationModel(applicable=e.probation_applicable, end_date=iso(e.probation_end_date), confirmation_date=iso(e.confirmation_date)),
    )
    work = WorkModel(
        attendance_id=e.attendance_id,
        shift_id=str(e.shift_id) if e.shift_id else None,
        attendance_policy_id=str(e.attendance_policy_id) if e.attendance_policy_id else None,
        overtime_policy_id=str(e.overtime_policy_id) if e.overtime_policy_id else None,
    )
    display = DisplayOut(
        full_name=e.full_name,
        department=refs.name(refs.departments, e.department_id) or "",
        designation=refs.name(refs.designations, e.designation_id) or "",
        employment_type=refs.name(refs.employment_types, e.employment_type_id) or "",
        status=refs.status_ref(e.status_code),
        reporting_manager=NamedRefOut(id=str(manager.id), name=manager.full_name) if manager else None,
        work_location=refs.name(refs.locations, e.work_location_id),
        shift=refs.name(refs.shifts, e.shift_id),
        attendance_policy=refs.name(refs.attendance_policies, e.attendance_policy_id),
        overtime_policy=refs.name(refs.overtime_policies, e.overtime_policy_id),
    )
    return EmployeeOut(
        id=str(e.id),
        employee_code=e.employee_code,
        version=e.version,
        personal=personal,
        employment=employment,
        work=work,
        payroll=payroll_out(payroll or {}, refs) if caller.can_sensitive else None,
        display=display,
        restricted=RestrictedOut(contact=not caller.can_contact, payroll=not caller.can_sensitive),
        audit=AuditInfoOut(created_at=e.created_at, created_by=e.created_by_name, updated_at=e.updated_at, updated_by=e.updated_by_name),
    )


def list_item_out(e: Employee, refs: References, caller: Caller, *, manager: Employee | None, contact: EmployeeContact | None) -> EmployeeListItemOut:
    return EmployeeListItemOut(
        id=str(e.id),
        employee_code=e.employee_code,
        full_name=e.full_name,
        photo_url=None,  # photos are out of scope until decided (contract D16)
        department=refs.named(refs.departments, e.department_id),
        designation=refs.named(refs.designations, e.designation_id),
        employment_type=refs.named(refs.employment_types, e.employment_type_id),
        status=refs.status_ref(e.status_code),
        joining_date=e.joining_date.isoformat(),
        reporting_manager=NamedRefOut(id=str(manager.id), name=manager.full_name) if manager else None,
        email=contact.email if caller.can_contact and contact else None,
        mobile=contact.mobile if caller.can_contact and contact else None,
    )
