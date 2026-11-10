"""Designations (job titles): list, create and update (Administration → Organization)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.designation_model import Designation, DesignationDepartment
from app.models.employee_model import Employee
from app.repositories.employee_repository import EmployeeRepository
from app.repositories.department_repository import DepartmentRepository
from app.repositories.designation_repository import DesignationRepository
from app.schemas.department_schema import DepartmentRef
from app.schemas.designation_schema import DesignationInput, DesignationOut
from app.services.audit_service import AuditService, diff
from app.services.department_service import CODE_MESSAGE, ORG_CODE, normalise_org_code
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version


def _snapshot(d: Designation) -> dict:
    return {
        "code": d.code,
        "name": d.name,
        "description": d.description,
        "departmentIds": ",".join(sorted(str(link.department_id) for link in d.department_links)),
        "active": d.active,
    }


def _out(d: Designation, count: int) -> DesignationOut:
    departments = [DepartmentRef(id=str(link.department.id), name=link.department.name) for link in d.department_links]
    # employeeCount counts employees whose status is not marked "employment ended" (HR setting).
    return DesignationOut(id=str(d.id), code=d.code, name=d.name, description=d.description, departments=departments, active=d.active, employee_count=count, version=d.version)


class DesignationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = DesignationRepository(session)
        self.departments = DepartmentRepository(session)
        self.employees = EmployeeRepository(session)
        self.audit = AuditService(session)

    async def list(self) -> list[DesignationOut]:
        counts = await self.employees.active_counts(Employee.designation_id)
        return [_out(d, counts.get(d.id, 0)) for d in await self.repo.list_all()]

    async def _validate(self, data: DesignationInput, current: Designation | None) -> tuple[str, str, list[uuid.UUID]]:
        errors = FieldErrors()
        code = normalise_org_code(data.code)
        name = data.name.strip()
        if not ORG_CODE.match(code):
            errors.add("code", CODE_MESSAGE)
        elif await self.repo.code_taken(code, current.id if current else None):
            errors.add("code", "Another designation uses this code.")
        if len(name) < 2:
            errors.add("name", "Enter a name.")
        ids = [body_id(v) for v in data.department_ids]
        unique = list(dict.fromkeys(i for i in ids if i is not None))
        if None in ids or len(await self.departments.get_many(unique)) != len(unique):
            errors.add("departmentIds", "Select existing departments.")
        if current is not None and current.active and not data.active:
            active = await self.employees.active_count(Employee.designation_id, current.id)
            if active:
                # G4: a designation with active employees cannot be deactivated.
                errors.add("active", f"{active} active employee(s) have this designation. Change it before deactivating.")
        errors.raise_if_any()
        return code, name, unique

    def _set_departments(self, designation: Designation, department_ids: list[uuid.UUID]) -> None:
        wanted = set(department_ids)
        designation.department_links = [link for link in designation.department_links if link.department_id in wanted]
        have = {link.department_id for link in designation.department_links}
        for dep_id in department_ids:
            if dep_id not in have:
                designation.department_links.append(DesignationDepartment(department_id=dep_id))

    async def create(self, data: DesignationInput) -> DesignationOut:
        code, name, department_ids = await self._validate(data, None)
        designation = Designation(code=code, name=name, description=data.description.strip(), active=data.active, department_links=[])
        self._set_departments(designation, department_ids)
        self.repo.add(designation)
        await self.session.flush()
        self.audit.record(
            module="Organization", action="designation.created", summary=f"Designation {code} created", entity_type="designation", entity_id=designation.id, entity_label=name,
            changes=diff({}, _snapshot(designation)),
        )
        await self.session.commit()
        return await self._reloaded(designation.id)

    async def update(self, designation_id: uuid.UUID, data: DesignationInput) -> DesignationOut:
        designation = await self.repo.get(designation_id)
        if designation is None:
            raise NotFoundError()
        ensure_version(designation, data.version)
        code, name, department_ids = await self._validate(data, designation)
        before = _snapshot(designation)
        designation.code, designation.name, designation.description, designation.active = code, name, data.description.strip(), data.active
        self._set_departments(designation, department_ids)
        changes = diff(before, _snapshot(designation))
        if changes:
            # A change to the department links alone still re-stamps updated_at (the audit listener
            # counts collection changes), so the version moves and concurrent edits are detected.
            await self.session.flush()
            self.audit.record(
                module="Organization", action="designation.updated", summary=f"Designation {code} updated", entity_type="designation", entity_id=designation.id, entity_label=name, changes=changes
            )
            await self.session.commit()
        return await self._reloaded(designation.id)

    async def _reloaded(self, designation_id: uuid.UUID) -> DesignationOut:
        designation = await self.repo.get(designation_id)
        assert designation is not None
        await self.session.refresh(designation, ["department_links"])
        return _out(designation, await self.employees.active_count(Employee.designation_id, designation.id))
