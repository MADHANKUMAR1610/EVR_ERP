"""Queries for the HR reference lists (employment types, statuses, locations, documents, payroll fields)."""

import uuid
from typing import TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reference_data_model import (
    AttendancePolicyOption,
    DocumentCategory,
    DocumentType,
    EmployeeStatus,
    EmploymentType,
    OvertimePolicyOption,
    PayrollFieldDefinition,
    WorkLocation,
)

CodedModel = TypeVar("CodedModel", EmploymentType, WorkLocation, AttendancePolicyOption, OvertimePolicyOption, DocumentCategory, DocumentType)


class ReferenceDataRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # Simple coded lists ---------------------------------------------------------------------------
    async def list_coded(self, model: type[CodedModel], *, active_only: bool = False) -> list[CodedModel]:
        stmt = select(model)
        if active_only:
            stmt = stmt.where(model.active.is_(True))
        return list((await self.session.scalars(stmt.order_by(model.name))).all())

    async def get_coded(self, model: type[CodedModel], item_id: uuid.UUID) -> CodedModel | None:
        return await self.session.get(model, item_id)

    async def get_coded_by_code(self, model: type[CodedModel], code: str) -> CodedModel | None:
        return await self.session.scalar(select(model).where(model.code == code))

    async def coded_code_taken(self, model: type[CodedModel], code: str, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(func.count()).select_from(model).where(model.code == code)
        if exclude_id:
            stmt = stmt.where(model.id != exclude_id)
        return bool(await self.session.scalar(stmt))

    # Employee statuses ---------------------------------------------------------------------------------
    async def list_statuses(self) -> list[EmployeeStatus]:
        return list((await self.session.scalars(select(EmployeeStatus).order_by(EmployeeStatus.sort_order, EmployeeStatus.code))).all())

    async def get_status(self, status_id: uuid.UUID) -> EmployeeStatus | None:
        return await self.session.get(EmployeeStatus, status_id)

    async def get_status_by_code(self, code: str) -> EmployeeStatus | None:
        return await self.session.scalar(select(EmployeeStatus).where(EmployeeStatus.code == code))

    async def existing_status_codes(self, codes: list[str]) -> set[str]:
        if not codes:
            return set()
        return set((await self.session.scalars(select(EmployeeStatus.code).where(EmployeeStatus.code.in_(codes)))).all())

    # Document types --------------------------------------------------------------------------------------
    async def list_document_types(self) -> list[DocumentType]:
        return list((await self.session.scalars(select(DocumentType).order_by(DocumentType.name))).all())

    # Payroll fields ----------------------------------------------------------------------------------------
    async def list_payroll_fields(self, *, active_only: bool = True) -> list[PayrollFieldDefinition]:
        stmt = select(PayrollFieldDefinition)
        if active_only:
            stmt = stmt.where(PayrollFieldDefinition.active.is_(True))
        return list((await self.session.scalars(stmt.order_by(PayrollFieldDefinition.sort_order, PayrollFieldDefinition.label))).all())

    async def get_payroll_field(self, field_id: uuid.UUID) -> PayrollFieldDefinition | None:
        return await self.session.get(PayrollFieldDefinition, field_id)

    async def payroll_key_taken(self, key: str, exclude_id: uuid.UUID | None = None) -> bool:
        stmt = select(func.count()).select_from(PayrollFieldDefinition).where(PayrollFieldDefinition.key == key)
        if exclude_id:
            stmt = stmt.where(PayrollFieldDefinition.id != exclude_id)
        return bool(await self.session.scalar(stmt))

    def add(self, obj: object) -> None:
        self.session.add(obj)
