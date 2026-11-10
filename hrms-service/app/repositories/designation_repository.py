import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.designation_model import Designation


class DesignationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[Designation]:
        return list((await self.session.scalars(select(Designation).order_by(Designation.name))).all())

    async def get(self, designation_id: uuid.UUID) -> Designation | None:
        return await self.session.get(Designation, designation_id)

    async def code_taken(self, code: str, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(func.count()).select_from(Designation).where(Designation.code == code)
        if exclude_id:
            stmt = stmt.where(Designation.id != exclude_id)
        return bool(await self.session.scalar(stmt))

    def add(self, designation: Designation) -> None:
        self.session.add(designation)
