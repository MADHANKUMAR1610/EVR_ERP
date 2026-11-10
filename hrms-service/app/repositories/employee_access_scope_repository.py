import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_access_scope_model import EmployeeAccessScope


class EmployeeAccessScopeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[EmployeeAccessScope]:
        return list((await self.session.scalars(select(EmployeeAccessScope).order_by(EmployeeAccessScope.role_code, EmployeeAccessScope.scope_type))).all())

    async def active_for_roles(self, roles: frozenset[str]) -> list[EmployeeAccessScope]:
        if not roles:
            return []
        stmt = select(EmployeeAccessScope).where(EmployeeAccessScope.role_code.in_(sorted(roles)), EmployeeAccessScope.active.is_(True))
        return list((await self.session.scalars(stmt)).all())

    async def get(self, scope_id: uuid.UUID) -> EmployeeAccessScope | None:
        return await self.session.get(EmployeeAccessScope, scope_id)

    async def exists(self, role_code: str, scope_type: str, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(EmployeeAccessScope.id).where(EmployeeAccessScope.role_code == role_code, EmployeeAccessScope.scope_type == scope_type)
        if exclude_id:
            stmt = stmt.where(EmployeeAccessScope.id != exclude_id)
        return await self.session.scalar(stmt) is not None

    def add(self, scope: EmployeeAccessScope) -> None:
        self.session.add(scope)
