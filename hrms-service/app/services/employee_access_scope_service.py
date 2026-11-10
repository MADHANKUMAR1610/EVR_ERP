"""/hr/setup/employee-access-scopes: HR or management assigns organizational scopes to Identity roles (Q12).

No assignments are created by default; every assignment is a management decision and is audited.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.models.employee_access_scope_model import EmployeeAccessScope
from app.repositories.department_repository import DepartmentRepository
from app.repositories.employee_access_scope_repository import EmployeeAccessScopeRepository
from app.schemas.employee_schema import AccessScopeIn, AccessScopeOut, NamedRefOut
from app.services.audit_service import AuditService, diff
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version


def _snapshot(s: EmployeeAccessScope) -> dict:
    return {"roleCode": s.role_code, "scopeType": s.scope_type, "departmentIds": ",".join(sorted(str(d) for d in s.department_ids)), "active": s.active}


class EmployeeAccessScopeService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = EmployeeAccessScopeRepository(session)
        self.departments = DepartmentRepository(session)
        self.audit = AuditService(session)

    async def _out(self, items: list[EmployeeAccessScope]) -> list[AccessScopeOut]:
        names = {d.id: d.name for d in await self.departments.get_many(list({i for s in items for i in s.department_ids}))}
        return [
            AccessScopeOut(id=str(s.id), role_code=s.role_code, scope_type=s.scope_type, departments=[NamedRefOut(id=str(d), name=names.get(d, "")) for d in s.department_ids], active=s.active, version=s.version)
            for s in items
        ]

    async def list(self) -> list[AccessScopeOut]:
        return await self._out(await self.repo.list_all())

    async def _validate(self, data: AccessScopeIn, current_id: uuid.UUID | None) -> list[uuid.UUID]:
        err = FieldErrors()
        role = data.role_code.strip()
        if not role:
            err.add("roleCode", "Enter the role code from the Identity service.")
        elif await self.repo.exists(role, data.scope_type, current_id):
            err.add("scopeType", "This role already has this scope type.")
        ids = [body_id(v) for v in data.department_ids]
        unique = list(dict.fromkeys(i for i in ids if i))
        if data.scope_type == "departments":
            if not data.department_ids:
                err.add("departmentIds", "Select at least one department.")
            elif None in ids or len(await self.departments.get_many(unique)) != len(unique):
                err.add("departmentIds", "Select existing departments.")
        elif data.department_ids:
            err.add("departmentIds", "Departments are only listed for the 'departments' scope type.")
        err.raise_if_any()
        return unique

    async def create(self, data: AccessScopeIn) -> AccessScopeOut:
        department_ids = await self._validate(data, None)
        scope = EmployeeAccessScope(role_code=data.role_code.strip(), scope_type=data.scope_type, department_ids=department_ids, active=data.active)
        self.repo.add(scope)
        await self.session.flush()
        self.audit.record(module="HR Setup", action="employee_access_scope.created", summary=f"Scope {scope.scope_type} given to role {scope.role_code}", entity_type="employee_access_scope", entity_id=scope.id, entity_label=scope.role_code, changes=diff({}, _snapshot(scope)))
        await self.session.commit()
        return (await self._out([scope]))[0]

    async def update(self, scope_id: uuid.UUID, data: AccessScopeIn) -> AccessScopeOut:
        scope = await self.repo.get(scope_id)
        if scope is None:
            raise NotFoundError()
        ensure_version(scope, data.version)
        department_ids = await self._validate(data, scope.id)
        before = _snapshot(scope)
        scope.role_code, scope.scope_type, scope.department_ids, scope.active = data.role_code.strip(), data.scope_type, department_ids, data.active
        changes = diff(before, _snapshot(scope))
        if changes:
            await self.session.flush()
            self.audit.record(module="HR Setup", action="employee_access_scope.updated", summary=f"Scope of role {scope.role_code} updated", entity_type="employee_access_scope", entity_id=scope.id, entity_label=scope.role_code, changes=changes)
            await self.session.commit()
        return (await self._out([scope]))[0]

