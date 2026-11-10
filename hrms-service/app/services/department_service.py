"""Departments: list, create and update (Administration → Organization)."""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.department_model import Department
from app.models.employee_model import Employee
from app.repositories.department_repository import DepartmentRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.department_schema import DepartmentInput, DepartmentOut, DepartmentRef, EmployeeNameRef
from app.services.audit_service import AuditService, diff
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

ORG_CODE = re.compile(r"^[A-Z0-9-]{1,10}$")
CODE_MESSAGE = "Use 1–10 capital letters, digits or hyphens."


def normalise_org_code(code: str) -> str:
    return code.strip().upper()


def _snapshot(d: Department) -> dict:
    return {"code": d.code, "name": d.name, "parentId": d.parent_id, "headEmployeeId": d.head_employee_id, "active": d.active}


class DepartmentService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DepartmentRepository(session)
        self.employees = EmployeeRepository(session)
        self.audit = AuditService(session)

    async def list(self) -> list[DepartmentOut]:
        departments = await self.repo.list_all()
        names = {d.id: d.name for d in departments}
        counts = await self.employees.active_counts(Employee.department_id)
        heads = await self.employees.get_many(d.head_employee_id for d in departments)
        return [self._out(d, names, counts, heads) for d in departments]

    def _out(self, d: Department, names: dict[uuid.UUID, str], counts: dict[uuid.UUID, int], heads: dict[uuid.UUID, Employee]) -> DepartmentOut:
        parent = DepartmentRef(id=str(d.parent_id), name=names.get(d.parent_id, "")) if d.parent_id else None
        head = heads.get(d.head_employee_id) if d.head_employee_id else None
        # employeeCount counts employees whose status is not marked "employment ended" (HR setting).
        return DepartmentOut(
            id=str(d.id), code=d.code, name=d.name, head=EmployeeNameRef(id=str(head.id), full_name=head.full_name) if head else None,
            parent=parent, active=d.active, employee_count=counts.get(d.id, 0), version=d.version,
        )

    async def _validate(self, data: DepartmentInput, current: Department | None) -> tuple[str, str, uuid.UUID | None, uuid.UUID | None]:
        errors = FieldErrors()
        code = normalise_org_code(data.code)
        name = data.name.strip()
        if not ORG_CODE.match(code):
            errors.add("code", CODE_MESSAGE)
        elif await self.repo.code_taken(code, current.id if current else None):
            errors.add("code", "Another department uses this code.")
        if len(name) < 2:
            errors.add("name", "Enter a name.")
        head_id = body_id(data.head_employee_id)
        if data.head_employee_id and (head_id is None or await self.employees.get(head_id) is None):
            errors.add("headEmployeeId", "Select an existing employee.")
        elif head_id and head_id != (current.head_employee_id if current else None) and not await self.employees.is_active(head_id):
            # G4: the head must be an active employee (status not marked "employment ended").
            errors.add("headEmployeeId", "The department head must be an active employee.")
        if current is not None and current.active and not data.active:
            active = await self.employees.active_count(Employee.department_id, current.id)
            if active:
                # G4: a department with active employees cannot be deactivated.
                errors.add("active", f"{active} active employee(s) are in this department. Move them before deactivating it.")

        parent_id = body_id(data.parent_id)
        if data.parent_id and parent_id is None:
            errors.add("parentId", "Select an existing department.")
        elif parent_id is not None:
            if await self.repo.get(parent_id) is None:
                errors.add("parentId", "Select an existing department.")
            elif current is not None and await self._creates_cycle(current.id, parent_id):
                errors.add("parentId", "A department cannot sit under itself or one of its sub-departments.")
        errors.raise_if_any()
        return code, name, parent_id, head_id

    async def _creates_cycle(self, department_id: uuid.UUID, parent_id: uuid.UUID) -> bool:
        seen: set[uuid.UUID] = set()
        node: uuid.UUID | None = parent_id
        while node is not None and node not in seen:
            if node == department_id:
                return True
            seen.add(node)
            node = await self.repo.parent_of(node)
        return False

    async def create(self, data: DepartmentInput) -> DepartmentOut:
        code, name, parent_id, head_id = await self._validate(data, None)
        department = Department(code=code, name=name, parent_id=parent_id, head_employee_id=head_id, active=data.active)
        self.repo.add(department)
        await self.session.flush()
        self.audit.record(
            module="Organization", action="department.created", summary=f"Department {code} created", entity_type="department", entity_id=department.id, entity_label=name,
            changes=diff({}, _snapshot(department)),
        )
        await self.session.commit()
        return await self._one(department)

    async def update(self, department_id: uuid.UUID, data: DepartmentInput) -> DepartmentOut:
        department = await self.repo.get(department_id)
        if department is None:
            raise NotFoundError()
        ensure_version(department, data.version)
        code, name, parent_id, head_id = await self._validate(data, department)
        before = _snapshot(department)
        department.code, department.name, department.parent_id, department.head_employee_id, department.active = code, name, parent_id, head_id, data.active
        changes = diff(before, _snapshot(department))
        if changes:
            await self.session.flush()
            self.audit.record(
                module="Organization", action="department.updated", summary=f"Department {code} updated", entity_type="department", entity_id=department.id, entity_label=name, changes=changes
            )
            await self.session.commit()
        return await self._one(department)

    async def _one(self, d: Department) -> DepartmentOut:
        names = {}
        if d.parent_id:
            parent = await self.repo.get(d.parent_id)
            names = {parent.id: parent.name} if parent else {}
        count = await self.employees.active_count(Employee.department_id, d.id)
        heads = await self.employees.get_many([d.head_employee_id])
        return self._out(d, names, {d.id: count}, heads)
