"""Employees: directory, record, create, update, status changes, picker lookup and history (contract B4).

Access is checked in three layers:
- permission: the controller guards each endpoint;
- organizational scope (Q12): records outside the caller's scope are 404, and writes may not move
  a record out of it;
- field scope: contact details need hr.employees:view-contact; payroll values need
  hr.employees:view-sensitive, and sensitive ones are encrypted at rest and always masked.

Validation rules and messages are the frontend form's (src/features/hr/employees/schemas.ts).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic.alias_generators import to_camel
from sqlalchemy import false
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.errors import NotFoundError
from app.core.permissions import P
from app.database.base import utcnow
from app.models.employee_model import Employee, EmployeeContact, EmployeeHistory, EmployeePayrollValue, EmployeeReportingLine
from app.repositories.base_repository import paginate, parse_sort
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.common import Page, PageParams
from app.schemas.employee_schema import EmployeeLookupItemOut, EmployeeOut, EmployeeUpsertIn, HistoryEntryOut, NamedRefOut, StatusChangeIn
from app.services.audit_service import AuditService
from app.services.employee_scope_service import EmployeeScopeService
from app.services.employee_support import Caller, References, company_today, employee_out, full_name, list_item_out, parse_date
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

PHONE = re.compile(r"^\+?[0-9][0-9\s-]{5,19}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
CONTACT_KEYS = ("mobile", "email", "address", "emergency_contact")

# Section names used in history (values are never recorded, contract B4).
PERSONAL, CONTACT, EMPLOYMENT, WORK, PAYROLL = "Personal details", "Contact details", "Employment details", "Work references", "Payroll details"

Deny = Callable[[str], Awaitable[None]]  # records an audited denial and raises 403


def _digits(v: str) -> int:
    return len(re.sub(r"\D", "", v))


def _valid_phone(v: str) -> bool:
    return bool(PHONE.match(v)) and 7 <= _digits(v) <= 15


def _clean(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip()
    return v or None


@dataclass
class Planned:
    """Validated values ready to apply."""

    employee: dict[str, Any]
    contact: dict[str, Any] | None  # None = leave contact unchanged
    payroll_set: dict[str, str] = field(default_factory=dict)
    payroll_clear: set[str] = field(default_factory=set)


class EmployeeService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.repo = EmployeeRepository(session)
        self.scopes = EmployeeScopeService(session)
        self.audit = AuditService(session)
        self.scope_clause = EmployeeScopeService.clause(caller.scope)

    # ---- Reads ----------------------------------------------------------------------------------------

    async def directory(self, params: PageParams, *, department_id: str | None, designation_id: str | None, employment_type_id: str | None, status: str | None) -> Page:
        stmt = self.repo.directory(
            self.scope_clause,
            q=params.q,
            department_id=body_id(department_id),
            designation_id=body_id(designation_id),
            employment_type_id=body_id(employment_type_id),
            status=status or None,
        )
        # Unknown filter IDs match nothing rather than everything.
        for raw in (department_id, designation_id, employment_type_id):
            if raw and body_id(raw) is None:
                stmt = stmt.where(false())
        order = parse_sort(params.sort, EmployeeRepository.SORTS, "employeeCode:asc")
        result = await paginate(self.session, stmt.order_by(*order, Employee.id), params.page, params.page_size)
        refs = await References.load(self.session)
        managers = await self.repo.get_many(e.reporting_manager_id for e in result.items)
        contacts = await self.repo.contacts(e.id for e in result.items) if self.caller.can_contact else {}
        items = [list_item_out(e, refs, self.caller, manager=managers.get(e.reporting_manager_id), contact=contacts.get(e.id)) for e in result.items]
        return Page.build(result, items)

    async def _visible(self, employee_id: uuid.UUID) -> Employee:
        employee = await self.repo.get_visible(employee_id, self.scope_clause)
        if employee is None:
            raise NotFoundError()  # out of scope looks the same as missing (A4)
        return employee

    async def get(self, employee_id: uuid.UUID) -> EmployeeOut:
        return await self._out(await self._visible(employee_id))

    async def _out(self, e: Employee, refs: References | None = None) -> EmployeeOut:
        refs = refs or await References.load(self.session)
        manager = await self.repo.get(e.reporting_manager_id) if e.reporting_manager_id else None
        contact = await self.repo.contact(e.id) if self.caller.can_contact else None
        payroll = await self.repo.payroll_values(e.id) if self.caller.can_sensitive else None
        return employee_out(e, refs, self.caller, manager=manager, contact=contact, payroll=payroll)

    async def lookup(self, q: str | None, limit: int, exclude_id: str | None) -> list[EmployeeLookupItemOut]:
        """Picker search (B4): empty q returns the first `limit`; always within scope; only 4 fields."""
        stmt = self.repo.lookup(self.scope_clause, q=(q or "").strip() or None, exclude_id=body_id(exclude_id), limit=limit)
        rows = (await self.session.execute(stmt)).all()
        return [EmployeeLookupItemOut(id=str(r[0]), employee_code=r[1], full_name=r[2], department=r[3]) for r in rows]

    async def history(self, employee_id: uuid.UUID, page: int, page_size: int) -> Page:
        await self._visible(employee_id)
        result = await paginate(self.session, self.repo.history(employee_id), page, page_size)
        refs = await References.load(self.session)
        items = [
            HistoryEntryOut(
                id=str(h.id), at=h.created_at, actor=NamedRefOut(id=str(h.created_by), name=h.created_by_name), action=h.action, summary=h.summary,
                comment=h.comment, effective_date=h.effective_date.isoformat() if h.effective_date else None, changes=h.changes,
                from_status=refs.status_label(h.from_status), to_status=refs.status_label(h.to_status),
            )
            for h in result.items
        ]
        return Page.build(result, items)

    # ---- Create / update --------------------------------------------------------------------------------

    async def create(self, data: EmployeeUpsertIn, deny: Deny) -> EmployeeOut:
        await self._check_restricted_sections(data, deny)
        refs = await References.load(self.session)
        plan = await self._validate(data, None, refs)
        employee = await self.insert_planned(plan, refs)
        await self.session.commit()
        return await self._out(employee, refs)

    async def insert_planned(self, plan: Planned, refs: References, *, imported_by_job: str | None = None) -> Employee:
        """Adds a validated employee with its contact, payroll values, reporting line, history entry and
        audit entry, and flushes. The caller commits. Shared by create and the import job, so an
        imported employee is recorded exactly like one added through the form."""
        employee = Employee(id=uuid.uuid4(), **plan.employee)
        self.repo.add(employee)
        if plan.contact and any(v is not None for v in plan.contact.values()):
            self.repo.add(EmployeeContact(employee_id=employee.id, **plan.contact))
        await self._write_payroll(employee.id, {}, plan, refs)
        if employee.reporting_manager_id:
            self.repo.add(EmployeeReportingLine(employee_id=employee.id, manager_id=employee.reporting_manager_id, effective_from=employee.joining_date))
        if employee.shift_id:
            # Module 5: the shift is also recorded in the dated assignment history, from the joining date.
            from app.services.attendance.shift_assignment_service import record_assignment

            await self.session.flush()  # the employee row first: the assignment refers to it
            await record_assignment(self.session, employee, employee.shift_id, employee.joining_date, reason=None, backdated=False)
        if imported_by_job:
            self._history(employee.id, "imported", "Employee record imported", comment=f"Import job {imported_by_job}")
        else:
            self._history(employee.id, "created", "Employee record created")
        await self.session.flush()
        self.audit.record(
            module="Employees", action="employee.imported" if imported_by_job else "employee.created", summary=f"Employee {employee.employee_code} {'imported' if imported_by_job else 'created'}",
            entity_type="employee", entity_id=employee.id, entity_label=employee.full_name,
            changes=[{"field": "importJob", "before": None, "after": imported_by_job}] if imported_by_job else None,
        )
        return employee

    async def update(self, employee_id: uuid.UUID, data: EmployeeUpsertIn, deny: Deny) -> EmployeeOut:
        employee = await self._visible(employee_id)
        ensure_version(employee, data.version)
        await self._check_restricted_sections(data, deny)
        status_changes = data.employment.status_code != employee.status_code
        if status_changes and not self.caller.has(P.EMPLOYEES_CHANGE_STATUS):
            await deny(P.EMPLOYEES_CHANGE_STATUS)  # decision Q1: PATCH changes status only with both permissions
        refs = await References.load(self.session)
        plan = await self._validate(data, employee, refs)

        before_status = employee.status_code
        sections = self._changed_sections(employee, plan.employee)
        contact = await self.repo.contact(employee.id)
        if plan.contact is not None and self._contact_changed(contact, plan.contact):
            sections.append(CONTACT)
            if contact is None:
                self.repo.add(EmployeeContact(employee_id=employee.id, **plan.contact))
            else:
                for k, v in plan.contact.items():
                    setattr(contact, k, v)
        stored = await self.repo.payroll_values(employee.id)
        if await self._write_payroll(employee.id, stored, plan, refs):
            sections.append(PAYROLL)
        manager_changed = plan.employee["reporting_manager_id"] != employee.reporting_manager_id
        new_shift = plan.employee["shift_id"] if plan.employee["shift_id"] != employee.shift_id else None
        for k, v in plan.employee.items():
            setattr(employee, k, v)
        if new_shift:
            # Module 5: a shift changed on the form applies from today (never back-dated from the form).
            from app.services.attendance.shift_assignment_service import record_assignment

            await record_assignment(self.session, employee, new_shift, company_today(), reason=None, backdated=False)
        if not sections and not status_changes:
            return await self._out(employee, refs)

        employee.updated_at = utcnow()  # contact/payroll-only edits still move the version
        if manager_changed:
            self.repo.add(EmployeeReportingLine(employee_id=employee.id, manager_id=employee.reporting_manager_id, effective_from=company_today()))
        if sections:
            self._history(employee.id, "updated", "Employee record updated", changes=sorted(set(sections)))
        if status_changes:
            self._history(employee.id, "status_changed", "Employment status changed", from_status=before_status, to_status=employee.status_code)
        await self.session.flush()
        self.audit.record(
            module="Employees", action="employee.updated", summary=f"Employee {employee.employee_code} updated", entity_type="employee", entity_id=employee.id, entity_label=employee.full_name,
            changes=[{"field": s, "before": None, "after": None} for s in sorted(set(sections))] + ([{"field": "status", "before": before_status, "after": employee.status_code}] if status_changes else []),
        )
        await self.session.commit()
        return await self._out(employee, refs)

    async def _check_restricted_sections(self, data: EmployeeUpsertIn, deny: Deny) -> None:
        if data.payroll is not None and not self.caller.can_sensitive:
            await deny(P.EMPLOYEES_VIEW_SENSITIVE)
        if not self.caller.can_contact and any(k in data.personal.model_fields_set for k in CONTACT_KEYS):
            await deny(P.EMPLOYEES_VIEW_CONTACT)

    def _history(self, employee_id: uuid.UUID, action: str, summary: str, **kw: Any) -> None:
        self.repo.add(EmployeeHistory(employee_id=employee_id, action=action, summary=summary, **kw))

    @staticmethod
    def _changed_sections(e: Employee, values: dict[str, Any]) -> list[str]:
        groups = {
            PERSONAL: ("employee_code", "first_name", "middle_name", "last_name", "date_of_birth"),
            EMPLOYMENT: ("joining_date", "department_id", "designation_id", "employment_type_id", "reporting_manager_id", "work_location_id", "probation_applicable", "probation_end_date", "confirmation_date"),
            WORK: ("attendance_id", "shift_id", "attendance_policy_id", "overtime_policy_id"),
        }
        return [name for name, keys in groups.items() if any(getattr(e, k) != values[k] for k in keys)]

    @staticmethod
    def _contact_changed(current: EmployeeContact | None, values: dict[str, Any]) -> bool:
        if current is None:
            return any(v is not None for v in values.values())
        return any(getattr(current, k) != v for k, v in values.items())

    async def _write_payroll(self, employee_id: uuid.UUID, stored: dict[str, EmployeePayrollValue], plan: Planned, refs: References) -> bool:
        changed = False
        for key, value in plan.payroll_set.items():
            sensitive = refs.payroll_fields[key].sensitive
            row = stored.get(key)
            if row is not None:
                current = crypto.decrypt(row.value) if row.encrypted else row.value
                if current == value and row.encrypted == sensitive:
                    continue
                row.value, row.encrypted = (crypto.encrypt(value) if sensitive else value), sensitive
            else:
                self.repo.add(EmployeePayrollValue(employee_id=employee_id, field_key=key, value=crypto.encrypt(value) if sensitive else value, encrypted=sensitive))
            changed = True
        for key in plan.payroll_clear:
            if key in stored:
                await self.repo.delete(stored[key])
                changed = True
        return changed

    # ---- Validation ----------------------------------------------------------------------------------------

    async def _validate(self, data: EmployeeUpsertIn, current: Employee | None, refs: References) -> Planned:
        err = FieldErrors()
        today = company_today()
        current_id = current.id if current else None

        # Employee ID
        code = data.employee_code.strip()
        if not code:
            err.add("employeeCode", "Employee ID is required.")
        elif len(code) > 30:
            err.add("employeeCode", "Employee ID must be at most 30 characters.")
        elif re.search(r"\s", code):
            err.add("employeeCode", "Employee ID cannot contain spaces.")
        elif await self.repo.code_taken(code, current_id):
            err.add("employeeCode", "Another employee uses this employee ID.")

        # Personal
        p = data.personal
        first = p.first_name.strip()
        if not first:
            err.add("personal.firstName", "First name is required.")
        elif len(first) > 50:
            err.add("personal.firstName", "First name must be at most 50 characters.")
        middle, last = _clean(p.middle_name), _clean(p.last_name)
        for path, label, v in (("personal.middleName", "Middle name", middle), ("personal.lastName", "Last name", last)):
            if v and len(v) > 50:
                err.add(path, f"{label} must be at most 50 characters.")

        dob = joining = None
        try:
            dob = parse_date(p.date_of_birth)
        except ValueError:
            err.add("personal.dateOfBirth", "Enter a valid date.")
        e = data.employment
        try:
            joining = parse_date(e.joining_date)
            if joining is None:
                err.add("employment.joiningDate", "Joining date is required.")
        except ValueError:
            err.add("employment.joiningDate", "Enter a valid date.")
        if dob and dob > today:
            err.add("personal.dateOfBirth", "Date of birth cannot be in the future.")
        elif dob and joining and dob >= joining:
            err.add("personal.dateOfBirth", "Date of birth must be before the joining date.")

        contact = await self._validate_contact(data, current_id, err)

        # Employment references
        department_id = self._ref(err, "employment.departmentId", e.department_id, refs.departments, current.department_id if current else None, "Select a department.", "department")
        designation_id = self._ref(err, "employment.designationId", e.designation_id, refs.designations, current.designation_id if current else None, "Select a designation.", "designation")
        type_id = self._ref(err, "employment.employmentTypeId", e.employment_type_id, refs.employment_types, current.employment_type_id if current else None, "Select an employment type.", "employment type")
        location_id = self._ref(err, "employment.workLocationId", e.work_location_id, refs.locations, current.work_location_id if current else None, None, "work location")
        self._validate_status(err, e.status_code, current, refs)
        manager_id = await self._validate_manager(err, "employment.reportingManagerId", e.reporting_manager_id, current_id)

        probation = e.probation
        applicable = bool(probation and probation.applicable)
        end = confirmation = None
        try:
            end = parse_date(probation.end_date if probation else None)
        except ValueError:
            err.add("employment.probation.endDate", "Enter a valid date.")
        try:
            confirmation = parse_date(probation.confirmation_date if probation else None)
        except ValueError:
            err.add("employment.probation.confirmationDate", "Enter a valid date.")
        if applicable and end is None and not err.has("employment.probation.endDate"):
            err.add("employment.probation.endDate", "Enter the probation end date.")
        if applicable and end and joining and end <= joining:
            err.add("employment.probation.endDate", "Probation must end after the joining date.")
        if confirmation and joining and confirmation < joining:
            err.add("employment.probation.confirmationDate", "Confirmation date cannot be before the joining date.")

        # Work references
        w = data.work
        attendance_id = _clean(w.attendance_id)
        if attendance_id and len(attendance_id) > 30:
            err.add("work.attendanceId", "Attendance ID must be at most 30 characters.")
        elif attendance_id and await self.repo.attendance_id_taken(attendance_id, current_id):
            err.add("work.attendanceId", "Another employee uses this attendance ID.")
        shift_id = self._ref(err, "work.shiftId", w.shift_id, refs.shifts, current.shift_id if current else None, None, "shift")
        ap_id = self._ref(err, "work.attendancePolicyId", w.attendance_policy_id, refs.attendance_policies, current.attendance_policy_id if current else None, None, "attendance policy")
        op_id = self._ref(err, "work.overtimePolicyId", w.overtime_policy_id, refs.overtime_policies, current.overtime_policy_id if current else None, None, "overtime policy")

        payroll_set, payroll_clear = await self._validate_payroll(err, data.payroll, current_id, refs)

        # Organizational scope: a write may not place the record outside the caller's reach.
        if department_id and not err.has("employment.departmentId") and not err.has("employment.reportingManagerId"):
            if not await self.scopes.covers(self.caller.scope, employee_id=current_id, department_id=department_id, manager_id=manager_id):
                err.add("employment.departmentId", "You can only add or move employees within your organizational scope.")

        transition_only = len(err.details) == 1 and err.has("employment.statusCode") and err.details[0].get("_transition")
        for d in err.details:
            d.pop("_transition", None)
        err.raise_if_any(code="INVALID_TRANSITION" if transition_only else None)

        values = {
            "employee_code": code, "first_name": first, "middle_name": middle, "last_name": last, "full_name": full_name(first, middle, last), "date_of_birth": dob,
            "joining_date": joining, "department_id": department_id, "designation_id": designation_id, "employment_type_id": type_id, "status_code": e.status_code,
            "reporting_manager_id": manager_id, "work_location_id": location_id, "probation_applicable": applicable, "probation_end_date": end, "confirmation_date": confirmation,
            "attendance_id": attendance_id, "shift_id": shift_id, "attendance_policy_id": ap_id, "overtime_policy_id": op_id,
        }
        return Planned(employee=values, contact=contact, payroll_set=payroll_set, payroll_clear=payroll_clear)

    @staticmethod
    def _ref(err: FieldErrors, path: str, raw: str | None, table: dict, current: uuid.UUID | None, required_message: str | None, label: str) -> uuid.UUID | None:
        if raw is None or str(raw).strip() == "":
            if required_message:
                err.add(path, required_message)
            return None
        item_id = body_id(raw)
        item = table.get(item_id) if item_id else None
        if item is None:
            err.add(path, f"Select an existing {label}.")
            return None
        if not item.active and item_id != current:
            err.add(path, f"This {label} is no longer active.")
            return None
        return item_id

    def _validate_status(self, err: FieldErrors, code: str, current: Employee | None, refs: References) -> None:
        path = "employment.statusCode"
        status = refs.statuses.get(code)
        if not code:
            err.add(path, "Select an employment status.")
        elif status is None:
            err.add(path, "Select an existing employment status.")
        elif current is None:
            if not status.active or not status.allowed_on_create:
                err.add(path, "This status cannot be used for a new employee.")
        elif code != current.status_code:
            allowed = {t.to_code for t in refs.statuses[current.status_code].transitions} if current.status_code in refs.statuses else set()
            if code not in allowed or not status.active:
                err.details.append({"field": path, "message": f"An employee cannot move from {refs.status_label(current.status_code)} to {status.label}.", "_transition": True})
            elif status.reason_required:
                err.add(path, f"Moving to {status.label} needs a reason. Use Change status instead.")

    async def _validate_manager(self, err: FieldErrors, path: str, raw: str | None, employee_id: uuid.UUID | None) -> uuid.UUID | None:
        if raw is None or str(raw).strip() == "":
            return None
        manager_id = body_id(raw)
        if manager_id is None or await self.repo.get(manager_id) is None:
            err.add(path, "Select an existing employee.")
            return None
        if employee_id and manager_id == employee_id:
            err.add(path, "An employee cannot report to themself.")
            return None
        if employee_id and await self.scopes.is_report(employee_id, manager_id):
            err.add(path, "The manager cannot be one of this employee's reports.")
            return None
        return manager_id

    async def _validate_contact(self, data: EmployeeUpsertIn, current_id: uuid.UUID | None, err: FieldErrors) -> dict[str, Any] | None:
        p = data.personal
        sent = p.model_fields_set
        if not any(k in sent for k in CONTACT_KEYS):
            return None  # unchanged (or none on create)
        existing = await self.repo.contact(current_id) if current_id else None

        def keep(attr: str) -> Any:
            return getattr(existing, attr) if existing else None

        values: dict[str, Any] = {}
        if "mobile" in sent:
            mobile = _clean(p.mobile)
            if mobile and not _valid_phone(mobile):
                err.add("personal.mobile", "Enter a valid contact number (7–15 digits).")
            values["mobile"] = mobile
        else:
            values["mobile"] = keep("mobile")
        if "email" in sent:
            email = _clean(p.email)
            if email and (len(email) > 254 or not EMAIL.match(email)):
                err.add("personal.email", "Enter a valid email address.")
            elif email and await self.repo.email_taken(email, current_id):
                err.add("personal.email", "Another employee uses this email address.")
            values["email"] = email
        else:
            values["email"] = keep("email")

        address_fields = {"line1": ("address_line1", 120, "Address line 1"), "line2": ("address_line2", 120, "Address line 2"), "city": ("address_city", 60, "City"),
                          "state": ("address_state", 60, "State"), "postal_code": ("address_postal_code", 12, "Postal code"), "country": ("address_country", 60, "Country")}
        if "address" in sent:
            a = p.address
            for key, (column, limit, label) in address_fields.items():
                v = _clean(getattr(a, key)) if a else None
                if v and len(v) > limit:
                    err.add(f"personal.address.{to_camel(key)}", f"{label} must be at most {limit} characters.")
                values[column] = v
        else:
            for column, _, _ in address_fields.values():
                values[column] = keep(column)

        if "emergency_contact" in sent:
            ec = p.emergency_contact
            name, relationship, phone = (_clean(ec.name), _clean(ec.relationship), _clean(ec.phone)) if ec else (None, None, None)
            if name and len(name) > 100:
                err.add("personal.emergencyContact.name", "Contact name must be at most 100 characters.")
            if relationship and len(relationship) > 40:
                err.add("personal.emergencyContact.relationship", "Relationship must be at most 40 characters.")
            if phone and not _valid_phone(phone):
                err.add("personal.emergencyContact.phone", "Enter a valid phone number (7–15 digits).")
            if name or relationship or phone:
                if not name:
                    err.add("personal.emergencyContact.name", "Enter the contact name, or clear the emergency contact.")
                if not phone:
                    err.add("personal.emergencyContact.phone", "Enter the contact phone number, or clear the emergency contact.")
            values.update(emergency_name=name, emergency_relationship=relationship, emergency_phone=phone)
        else:
            for column in ("emergency_name", "emergency_relationship", "emergency_phone"):
                values[column] = keep(column)
        return values

    async def _validate_payroll(self, err: FieldErrors, payload: dict[str, str] | None, current_id: uuid.UUID | None, refs: References) -> tuple[dict[str, str], set[str]]:
        if payload is None:
            return {}, set()
        to_set: dict[str, str] = {}
        to_clear: set[str] = set()
        for key, raw in payload.items():
            path = f"payroll.{key}"
            definition = refs.payroll_fields.get(key)
            if definition is None or not definition.active:
                err.add(path, "This payroll field is not in use.")
                continue
            value = (raw or "").strip()
            label = definition.label
            if not value:
                if not definition.sensitive:
                    to_clear.add(key)  # "" clears a non-sensitive value; a blank sensitive value keeps it
                continue
            if definition.max_length and len(value) > definition.max_length:
                err.add(path, f"{label} must be at most {definition.max_length} characters.")
            elif definition.pattern and not re.search(definition.pattern, value):
                err.add(path, definition.pattern_message or f"{label} has an invalid format.")
            if definition.type == "select" and definition.options and not any(o.get("value") == value for o in definition.options):
                err.add(path, f"Select a valid {label.lower()}.")
            if definition.type == "date":
                try:
                    if parse_date(value) is None:
                        raise ValueError(value)
                except ValueError:
                    err.add(path, "Enter a valid date.")
            if definition.type == "number":
                try:
                    float(value)
                except ValueError:
                    err.add(path, "Enter a number.")
            to_set[key] = value
        stored = set((await self.repo.payroll_values(current_id)).keys()) if current_id else set()
        for key, definition in refs.payroll_fields.items():
            if definition.active and definition.required:
                will_have = key in to_set or (key in stored and key not in to_clear)
                if not will_have:
                    err.add(f"payroll.{key}", f"{definition.label} is required.")
        return to_set, to_clear

    # ---- Status changes (B4 status-changes) -----------------------------------------------------------------

    async def change_status(self, employee_id: uuid.UUID, data: StatusChangeIn) -> EmployeeOut:
        employee = await self._visible(employee_id)
        ensure_version(employee, data.version)
        refs = await References.load(self.session)
        err = FieldErrors()
        target = refs.statuses.get(data.to_status)
        current = refs.statuses.get(employee.status_code)
        transition_error = False
        if not data.to_status:
            err.add("toStatus", "Select the new status.")
        elif data.to_status == employee.status_code:
            err.add("toStatus", "The employee already has this status.")
        elif target is None or current is None or data.to_status not in {t.to_code for t in current.transitions}:
            err.add("toStatus", "This change is not allowed from the current status.")
            transition_error = True
        elif not target.active:
            err.add("toStatus", "This status is no longer in use.")
        effective: date | None = None
        try:
            effective = parse_date(data.effective_date)
        except ValueError:
            pass
        if effective is None:
            err.add("effectiveDate", "Enter the effective date.")
        elif effective < employee.joining_date:
            err.add("effectiveDate", "The effective date cannot be before the joining date.")
        reason = _clean(data.reason)
        if reason and len(reason) > 500:
            err.add("reason", "Keep the reason under 500 characters.")
        elif not reason and target is not None and target.reason_required:
            err.add("reason", "Enter a reason for this change.")
        err.raise_if_any(code="INVALID_TRANSITION" if transition_error and len(err.details) == 1 else None)

        before = employee.status_code
        employee.status_code = data.to_status
        self._history(employee.id, "status_changed", "Employment status changed", from_status=before, to_status=data.to_status, effective_date=effective, comment=reason)
        await self.session.flush()
        self.audit.record(
            module="Employees", action="employee.status_changed", summary=f"Employee {employee.employee_code}: {before} → {data.to_status}", entity_type="employee",
            entity_id=employee.id, entity_label=employee.full_name, changes=[{"field": "status", "before": before, "after": data.to_status}],
        )
        await self.session.commit()
        return await self._out(employee, refs)
