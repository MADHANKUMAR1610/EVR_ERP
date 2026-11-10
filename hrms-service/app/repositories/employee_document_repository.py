import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_document_model import DocumentSettings, EmployeeDocument


class EmployeeDocumentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def for_employee(self, employee_id: uuid.UUID) -> list[EmployeeDocument]:
        stmt = select(EmployeeDocument).where(EmployeeDocument.employee_id == employee_id).order_by(EmployeeDocument.created_at.desc(), EmployeeDocument.id.desc())
        return list((await self.session.scalars(stmt)).all())

    async def get(self, employee_id: uuid.UUID, document_id: uuid.UUID) -> EmployeeDocument | None:
        return await self.session.scalar(select(EmployeeDocument).where(EmployeeDocument.id == document_id, EmployeeDocument.employee_id == employee_id))

    async def latest_per_type(self, employee_ids: Iterable[uuid.UUID]) -> dict[tuple[uuid.UUID, uuid.UUID], EmployeeDocument]:
        """The newest copy of each document type for each employee (the copy that decides its state)."""
        ids = list(set(employee_ids))
        if not ids:
            return {}
        stmt = (
            select(EmployeeDocument)
            .where(EmployeeDocument.employee_id.in_(ids))
            .distinct(EmployeeDocument.employee_id, EmployeeDocument.document_type_id)
            .order_by(EmployeeDocument.employee_id, EmployeeDocument.document_type_id, EmployeeDocument.created_at.desc(), EmployeeDocument.id.desc())
        )
        return {(d.employee_id, d.document_type_id): d for d in (await self.session.scalars(stmt)).all()}

    async def settings(self) -> DocumentSettings:
        row = await self.session.scalar(select(DocumentSettings))
        if row is None:  # created by migration 0005; absence means a damaged database
            raise RuntimeError("document_settings row is missing")
        return row

    def add(self, obj: object) -> None:
        self.session.add(obj)
