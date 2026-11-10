import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.department_model import Department


class DepartmentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[Department]:
        return list((await self.session.scalars(select(Department).order_by(Department.name))).all())

    async def get(self, department_id: uuid.UUID) -> Department | None:
        return await self.session.get(Department, department_id)

    async def get_many(self, ids: list[uuid.UUID]) -> list[Department]:
        if not ids:
            return []
        return list((await self.session.scalars(select(Department).where(Department.id.in_(ids)))).all())

    async def code_taken(self, code: str, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(func.count()).select_from(Department).where(Department.code == code)
        if exclude_id:
            stmt = stmt.where(Department.id != exclude_id)
        return bool(await self.session.scalar(stmt))

    async def parent_of(self, department_id: uuid.UUID) -> uuid.UUID | None:
        return await self.session.scalar(select(Department.parent_id).where(Department.id == department_id))

    def add(self, department: Department) -> None:
        self.session.add(department)
