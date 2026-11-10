"""Import columns and row checking (contract B6).

Columns are the contract's proposed template (R5, pending HR approval). Which ones are required is
not decided here: a column is required exactly when the employee form requires the field (Module 2),
so import and the form can never disagree. Each row is converted to the same request the form sends
and checked by the same validator (EmployeeService._validate): formats, references, statuses allowed
on create, uniqueness against existing employees and organizational scope. On top of that, rows are
checked against earlier rows of the same file for the unique fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailedError
from app.models.employee_model import Employee
from app.schemas.employee_schema import EmployeeUpsertIn
from app.schemas.import_schema import ImportFieldOut, ImportMessageOut, ImportRowIn
from app.services.employee_service import EmployeeService, Planned
from app.services.employee_support import Caller, References


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    required: bool
    type: str
    reference_type: str | None = None
    max_length: int | None = None
    aliases: tuple[str, ...] = ()
    unique: bool = False
    contact: bool = False  # needs hr.employees:view-contact


COLUMNS: tuple[Column, ...] = (
    Column("employeeCode", "Employee ID", True, "text", max_length=30, aliases=("employee code", "emp id", "employee no"), unique=True),
    Column("personal.firstName", "First name", True, "text", max_length=50, aliases=("given name",)),
    Column("personal.middleName", "Middle name", False, "text", max_length=50),
    Column("personal.lastName", "Last name", False, "text", max_length=50, aliases=("surname", "family name")),
    Column("personal.dateOfBirth", "Date of birth", False, "date", aliases=("dob", "birth date")),
    Column("personal.mobile", "Mobile", False, "phone", aliases=("phone", "mobile number", "contact number"), contact=True),
    Column("personal.email", "Email", False, "email", aliases=("email address", "e-mail"), unique=True, contact=True),
    Column("employment.joiningDate", "Joining date", True, "date", aliases=("date of joining", "doj", "join date")),
    Column("employment.department", "Department", True, "reference", "department", aliases=("dept",)),
    Column("employment.designation", "Designation", True, "reference", "designation", aliases=("job title", "title")),
    Column("employment.employmentType", "Employment type", True, "reference", "employmentType", aliases=("type",)),
    Column("employment.status", "Employment status", True, "reference", "employeeStatus", aliases=("status",)),
    Column("employment.workLocation", "Work location", False, "reference", "workLocation", aliases=("location",)),
    Column("employment.reportingManagerCode", "Reporting manager employee ID", False, "text", max_length=30, aliases=("manager", "manager id", "reporting manager")),
    Column("work.attendanceId", "Attendance ID", False, "text", max_length=30, aliases=("biometric id", "device id"), unique=True),
)
BY_KEY = {c.key: c for c in COLUMNS}

# Validator field paths (EmployeeUpsertIn) -> import column keys.
PATHS = {
    "employment.departmentId": "employment.department",
    "employment.designationId": "employment.designation",
    "employment.employmentTypeId": "employment.employmentType",
    "employment.statusCode": "employment.status",
    "employment.workLocationId": "employment.workLocation",
    "employment.reportingManagerId": "employment.reportingManagerCode",
}
# Validator messages that mean "conflicts with an existing employee on a unique field".
UNIQUE_CONFLICTS = {
    "Another employee uses this employee ID.",
    "Another employee uses this email address.",
    "Another employee uses this attendance ID.",
}
REFERENCE_LABELS = {"department": "department", "designation": "designation", "employmentType": "employment type", "employeeStatus": "employment status", "workLocation": "work location"}


def normalize_date(value: str) -> str | None:
    """Accepted formats (contract B6, proposed): YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY. ISO or None."""
    v = value.strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    if m:
        y, mo, d = m.groups()
    else:
        m = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", v)
        if not m:
            return None
        d, mo, y = m.groups()
    try:
        return date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return None


def visible_columns(caller: Caller) -> list[Column]:
    """Contact columns are offered only to callers who may see contact details (field-level rule)."""
    return [c for c in COLUMNS if caller.can_contact or not c.contact]


def field_definitions(caller: Caller, refs: References) -> list[ImportFieldOut]:
    """GET /fields. Examples come from the company's own configuration, never from invented values."""
    first = {
        "department": next((d.name for d in sorted(refs.departments.values(), key=lambda x: x.name) if d.active), None),
        "designation": next((d.name for d in sorted(refs.designations.values(), key=lambda x: x.name) if d.active), None),
        "employmentType": next((d.name for d in sorted(refs.employment_types.values(), key=lambda x: x.name) if d.active), None),
        "employeeStatus": next((s.label for s in sorted(refs.statuses.values(), key=lambda x: x.sort_order) if s.active and s.allowed_on_create), None),
        "workLocation": next((d.name for d in sorted(refs.locations.values(), key=lambda x: x.name) if d.active), None),
    }
    examples = {"employeeCode": "EMP-0001", "personal.firstName": "First", "personal.lastName": "Last", "personal.dateOfBirth": "1990-01-31", "personal.mobile": "+91 98765 43210",
                "personal.email": "name@example.com", "employment.joiningDate": "2026-01-15", "work.attendanceId": "0001"}
    out = []
    for c in visible_columns(caller):
        example = first.get(c.reference_type) if c.reference_type else examples.get(c.key)
        out.append(ImportFieldOut(key=c.key, label=c.label, required=c.required, type=c.type, reference_type=c.reference_type, max_length=c.max_length,
                                  aliases=list(c.aliases), example=example, unique=c.unique))
    return out


@dataclass
class RowOutcome:
    row_number: int
    messages: list[ImportMessageOut] = field(default_factory=list)
    plan: Planned | None = None

    @property
    def errors(self) -> list[ImportMessageOut]:
        return [m for m in self.messages if m.severity == "error"]

    @property
    def duplicate_only(self) -> bool:
        """Every error is a unique-field conflict (with an existing employee or an earlier row)."""
        return bool(self.errors) and all(is_duplicate_message(m.message) for m in self.errors)

    @property
    def status(self) -> str:
        """Worst status wins: error > duplicate > warning > valid (contract B6)."""
        if self.errors:
            return "duplicate" if self.duplicate_only else "error"
        return "warning" if self.messages else "valid"


def is_duplicate_message(message: str) -> bool:
    return message in UNIQUE_CONFLICTS or (message.startswith("Same ") and " as row " in message)


class RowChecker:
    """Checks rows in file order. Keep one instance per file, so duplicates within the file are found."""

    def __init__(self, session: AsyncSession, caller: Caller, refs: References):
        self.session = session
        self.caller = caller
        self.refs = refs
        self.employees = EmployeeService(session, caller)
        self.seen: dict[str, dict[str, int]] = {c.key: {} for c in COLUMNS if c.unique}
        self.columns = {c.key: c for c in visible_columns(caller)}
        self._lookup = {
            "department": [(d.id, d.code, d.name) for d in refs.departments.values()],
            "designation": [(d.id, d.code, d.name) for d in refs.designations.values()],
            "employmentType": [(d.id, d.code, d.name) for d in refs.employment_types.values()],
            "workLocation": [(d.id, d.code, d.name) for d in refs.locations.values()],
            "employeeStatus": [(s.code, s.code, s.label) for s in refs.statuses.values()],
        }

    def remember(self, row: ImportRowIn) -> None:
        """Records a row's unique values without checking it (rows processed before a resume)."""
        for key, seen in self.seen.items():
            value = (row.values.get(key) or "").strip()
            if value:
                seen.setdefault(value.lower() if key != "work.attendanceId" else value, row.row_number)

    def _resolve(self, column: Column, value: str, out: RowOutcome) -> str | None:
        v = value.strip().lower()
        matches = {i for i, code, name in self._lookup[column.reference_type] if code.lower() == v or name.lower() == v}
        if not matches:
            out.messages.append(ImportMessageOut(field=column.key, message=f'{column.label} "{value}" does not match any {REFERENCE_LABELS[column.reference_type]}.', severity="error"))
            return None
        if len(matches) > 1:
            out.messages.append(ImportMessageOut(field=column.key, message=f'{column.label} "{value}" matches more than one {REFERENCE_LABELS[column.reference_type]}; use its code.', severity="error"))
            return None
        return str(next(iter(matches)))

    async def check(self, row: ImportRowIn) -> RowOutcome:
        out = RowOutcome(row.row_number)
        values = {k: v.strip() for k, v in row.values.items() if v is not None and v.strip() != ""}
        for key in values:
            if key not in BY_KEY:
                out.messages.append(ImportMessageOut(field=key, message=f'"{key}" is not an import column.', severity="error"))
            elif key not in self.columns:
                out.messages.append(ImportMessageOut(field=key, message="You do not have permission to import contact details.", severity="error"))
        for key, column in self.columns.items():
            value = values.get(key)
            if value and column.max_length and len(value) > column.max_length:
                out.messages.append(ImportMessageOut(field=key, message=f"{column.label} must be at most {column.max_length} characters.", severity="error"))

        # Within-file duplicates on unique columns (case-insensitive, like the database).
        for key, seen in self.seen.items():
            value = values.get(key)
            if not value or key not in self.columns:
                continue
            norm = value.lower() if key != "work.attendanceId" else value
            if norm in seen:
                out.messages.append(ImportMessageOut(field=key, message=f"Same {BY_KEY[key].label.lower()} as row {seen[norm]}.", severity="error"))
            else:
                seen[norm] = row.row_number

        dates: dict[str, str | None] = {}
        for key in ("personal.dateOfBirth", "employment.joiningDate"):
            if values.get(key):
                iso = normalize_date(values[key])
                if iso is None:
                    out.messages.append(ImportMessageOut(field=key, message=f'{BY_KEY[key].label} "{values[key]}" is not a valid date (use YYYY-MM-DD or DD/MM/YYYY).', severity="error"))
                dates[key] = iso or ""
        refs: dict[str, str | None] = {}
        for key in ("employment.department", "employment.designation", "employment.employmentType", "employment.status", "employment.workLocation"):
            if values.get(key):
                refs[key] = self._resolve(BY_KEY[key], values[key], out)

        manager_id = None
        manager_code = values.get("employment.reportingManagerCode")
        if manager_code:
            manager_id = await self.session.scalar(select(Employee.id).where(func.lower(Employee.employee_code) == manager_code.lower()))
            if manager_id is None:
                out.messages.append(ImportMessageOut(field="employment.reportingManagerCode", message=f'No existing employee has the Employee ID "{manager_code}".', severity="error"))
        else:
            out.messages.append(ImportMessageOut(field="employment.reportingManagerCode", message="No reporting manager given.", severity="warning"))

        personal = {"firstName": values.get("personal.firstName", ""), "middleName": values.get("personal.middleName"), "lastName": values.get("personal.lastName"),
                    "dateOfBirth": dates.get("personal.dateOfBirth")}
        if self.caller.can_contact and ("personal.mobile" in values or "personal.email" in values):
            personal |= {"mobile": values.get("personal.mobile"), "email": values.get("personal.email")}
        status_value = refs.get("employment.status")
        request = EmployeeUpsertIn(
            employee_code=values.get("employeeCode", ""),
            personal=personal,
            employment={
                "joiningDate": dates.get("employment.joiningDate") or "", "departmentId": refs.get("employment.department") or "",
                "designationId": refs.get("employment.designation") or "", "employmentTypeId": refs.get("employment.employmentType") or "",
                "statusCode": status_value or "", "reportingManagerId": str(manager_id) if manager_id else None, "workLocationId": refs.get("employment.workLocation"),
            },
            work={"attendanceId": values.get("work.attendanceId")},
        )
        try:
            plan = await self.employees._validate(request, None, self.refs)
        except ValidationFailedError as exc:
            already = {m.field for m in out.messages if m.severity == "error"}
            for d in exc.details:
                key = PATHS.get(d["field"], d["field"])
                if key in already:
                    continue  # the import's own, more specific message is already there
                column = BY_KEY.get(key)
                message = d["message"]
                if column and message.startswith(("Select a", "Enter ", "Employee ID is required", "First name is required", "Joining date is required")) and not values.get(key):
                    message = f"{column.label} is required."
                out.messages.append(ImportMessageOut(field=key, message=message, severity="error"))
            return out
        if out.errors:
            return out
        out.plan = plan
        return out
