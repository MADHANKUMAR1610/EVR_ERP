"""Queries for employee records. Callers pass the organizational-scope clause; nothing here decides access."""

import uuid
from collections.abc import Iterable

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department_model import Department
from app.models.designation_model import Designation
from app.models.employee_model import Employee, EmployeeContact, EmployeeHistory, EmployeePayrollValue, EmployeeReportingLine
from app.models.reference_data_model import EmployeeStatus

# Employees whose status is configured as "employment ended" (HR setting) do not count as active.
ACTIVE = Employee.status_code.in_(select(EmployeeStatus.code).where(EmployeeStatus.employment_ended.is_(False)))


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def text_match(q: str) -> ColumnElement[bool]:
    pattern = f"%{_escape_like(q.lower())}%"
    return or_(func.lower(Employee.employee_code).like(pattern, escape="\\"), func.lower(Employee.full_name).like(pattern, escape="\\"))


class EmployeeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # --- Reads ---------------------------------------------------------------------------------------

    def directory(self, scope: ColumnElement[bool], *, q: str | None, department_id: uuid.UUID | None, designation_id: uuid.UUID | None,
                  employment_type_id: uuid.UUID | None, status: str | None) -> Select:
        stmt = (
            select(Employee)
            .join(Department, Department.id == Employee.department_id)
            .join(Designation, Designation.id == Employee.designation_id)
            .join(EmployeeStatus, EmployeeStatus.code == Employee.status_code)
            .where(scope)
        )
        if q:
            stmt = stmt.where(text_match(q))
        if department_id:
            stmt = stmt.where(Employee.department_id == department_id)
        if designation_id:
            stmt = stmt.where(Employee.designation_id == designation_id)
        if employment_type_id:
            stmt = stmt.where(Employee.employment_type_id == employment_type_id)
        if status:
            stmt = stmt.where(Employee.status_code == status)
        return stmt

    SORTS = {
        "employeeCode": func.lower(Employee.employee_code),
        "fullName": func.lower(Employee.full_name),
        "department": func.lower(Department.name),
        "designation": func.lower(Designation.name),
        "joiningDate": Employee.joining_date,
        "status": func.lower(EmployeeStatus.label),
    }

    async def get(self, employee_id: uuid.UUID) -> Employee | None:
        return await self.session.get(Employee, employee_id)

    async def get_visible(self, employee_id: uuid.UUID, scope: ColumnElement[bool]) -> Employee | None:
        return await self.session.scalar(select(Employee).where(Employee.id == employee_id, scope))

    async def get_many(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Employee]:
        ids = {i for i in ids if i}
        if not ids:
            return {}
        return {e.id: e for e in (await self.session.scalars(select(Employee).where(Employee.id.in_(ids)))).all()}

    async def contacts(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, EmployeeContact]:
        ids = set(ids)
        if not ids:
            return {}
        return {c.employee_id: c for c in (await self.session.scalars(select(EmployeeContact).where(EmployeeContact.employee_id.in_(ids)))).all()}

    async def contact(self, employee_id: uuid.UUID) -> EmployeeContact | None:
        return await self.session.scalar(select(EmployeeContact).where(EmployeeContact.employee_id == employee_id))

    async def payroll_values(self, employee_id: uuid.UUID) -> dict[str, EmployeePayrollValue]:
        rows = (await self.session.scalars(select(EmployeePayrollValue).where(EmployeePayrollValue.employee_id == employee_id))).all()
        return {r.field_key: r for r in rows}

    async def payroll_values_for_field(self, field_key: str) -> list[EmployeePayrollValue]:
        return list((await self.session.scalars(select(EmployeePayrollValue).where(EmployeePayrollValue.field_key == field_key))).all())

    async def all_encrypted_payroll_values(self) -> list[EmployeePayrollValue]:
        return list((await self.session.scalars(select(EmployeePayrollValue).where(EmployeePayrollValue.encrypted.is_(True)))).all())

    def lookup(self, scope: ColumnElement[bool], *, q: str | None, exclude_id: uuid.UUID | None, limit: int) -> Select:
        stmt = select(Employee.id, Employee.employee_code, Employee.full_name, Department.name).join(Department, Department.id == Employee.department_id).where(scope, ACTIVE)
        if q:
            stmt = stmt.where(text_match(q))
        if exclude_id:
            stmt = stmt.where(Employee.id != exclude_id)
        return stmt.order_by(func.lower(Employee.full_name), Employee.employee_code).limit(limit)

    def history(self, employee_id: uuid.UUID) -> Select:
        return select(EmployeeHistory).where(EmployeeHistory.employee_id == employee_id).order_by(EmployeeHistory.created_at.desc(), EmployeeHistory.id.desc())

    # --- Uniqueness ----------------------------------------------------------------------------------

    async def code_taken(self, code: str, exclude_id: uuid.UUID | None) -> bool:
        stmt = select(Employee.id).where(func.lower(Employee.employee_code) == code.lower())
        if exclude_id:
            stmt = stmt.where(Employee.id != exclude_id)
        return await self.session.scalar(stmt.limit(1)) is not None

    async def attendance_id_taken(self, attendance_id: str, exclude_id: uuid.UUID | None) -> bool:
        stmt = select(Employee.id).where(Employee.attendance_id == attendance_id)
        if exclude_id:
            stmt = stmt.where(Employee.id != exclude_id)
        return await self.session.scalar(stmt.limit(1)) is not None

    async def email_taken(self, email: str, exclude_id: uuid.UUID | None) -> bool:
        stmt = select(EmployeeContact.id).where(func.lower(EmployeeContact.email) == email.lower())
        if exclude_id:
            stmt = stmt.where(EmployeeContact.employee_id != exclude_id)
        return await self.session.scalar(stmt.limit(1)) is not None

    # --- Counts (active employees only) ----------------------------------------------------------------

    async def active_counts(self, column: ColumnElement) -> dict[uuid.UUID, int]:
        rows = await self.session.execute(select(column, func.count()).where(ACTIVE, column.is_not(None)).group_by(column))
        return {k: v for k, v in rows.all()}

    async def active_count(self, column: ColumnElement, value: uuid.UUID) -> int:
        return int(await self.session.scalar(select(func.count()).select_from(Employee).where(ACTIVE, column == value)) or 0)

    async def is_active(self, employee_id: uuid.UUID) -> bool:
        return await self.session.scalar(select(Employee.id).where(Employee.id == employee_id, ACTIVE)) is not None

    async def direct_report_counts(self, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
        ids = set(ids)
        if not ids:
            return {}
        rows = await self.session.execute(select(Employee.reporting_manager_id, func.count()).where(Employee.reporting_manager_id.in_(ids)).group_by(Employee.reporting_manager_id))
        return {k: v for k, v in rows.all()}

    # --- Reporting lines ---------------------------------------------------------------------------------

    def reporting_lines(self, scope: ColumnElement[bool], *, q: str | None, department_id: uuid.UUID | None, manager_id: uuid.UUID | None) -> Select:
        stmt = select(Employee).where(scope)
        if q:
            stmt = stmt.where(text_match(q))
        if department_id:
            stmt = stmt.where(Employee.department_id == department_id)
        if manager_id:
            stmt = stmt.where(Employee.reporting_manager_id == manager_id)
        return stmt.order_by(func.lower(Employee.full_name), Employee.employee_code)

    async def current_line_dates(self, employees: Iterable[Employee]) -> dict[uuid.UUID, object]:
        """Effective date of each employee's latest reporting-line entry (for the current manager)."""
        ids = {e.id for e in employees}
        if not ids:
            return {}
        latest = (
            select(EmployeeReportingLine.employee_id, func.max(EmployeeReportingLine.effective_from))
            .where(EmployeeReportingLine.employee_id.in_(ids))
            .group_by(EmployeeReportingLine.employee_id)
        )
        return {k: v for k, v in (await self.session.execute(latest)).all()}

    def add(self, obj: object) -> None:
        self.session.add(obj)

    async def delete(self, obj: object) -> None:
        await self.session.delete(obj)
