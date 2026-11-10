import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shift_model import Shift


class ShiftRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_all(self) -> list[Shift]:
        return list((await self.session.scalars(select(Shift).order_by(Shift.start_time, Shift.code))).all())

    async def list_active(self) -> list[Shift]:
        return list((await self.session.scalars(select(Shift).where(Shift.active.is_(True)).order_by(Shift.start_time, Shift.code))).all())

    async def get(self, shift_id: uuid.UUID) -> Shift | None:
        return await self.session.get(Shift, shift_id)

    async def code_taken(self, code: str, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(func.count()).select_from(Shift).where(func.lower(Shift.code) == code.lower())
        if exclude_id:
            stmt = stmt.where(Shift.id != exclude_id)
        return bool(await self.session.scalar(stmt))

    def add(self, shift: Shift) -> None:
        self.session.add(shift)
