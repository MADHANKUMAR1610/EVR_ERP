"""/hr/setup/document-settings: company document settings (expiry window). HR configuration, audited."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.employee_document_repository import EmployeeDocumentRepository
from app.schemas.employee_document_schema import DocumentSettingsIn, DocumentSettingsOut
from app.services.audit_service import AuditService, diff
from app.utils.validation import ensure_version


class DocumentSettingsService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = EmployeeDocumentRepository(session)

    @staticmethod
    def _out(s) -> DocumentSettingsOut:
        return DocumentSettingsOut(expiry_window_days=s.expiry_window_days, version=s.version, updated_at=s.updated_at, updated_by=s.updated_by_name)

    async def get(self) -> DocumentSettingsOut:
        return self._out(await self.repo.settings())

    async def update(self, data: DocumentSettingsIn) -> DocumentSettingsOut:
        settings = await self.repo.settings()
        ensure_version(settings, data.version)
        before = {"expiryWindowDays": settings.expiry_window_days}
        settings.expiry_window_days = data.expiry_window_days
        changes = diff(before, {"expiryWindowDays": settings.expiry_window_days})
        if changes:
            await self.session.flush()
            AuditService(self.session).record(module="HR Setup", action="document_settings.updated", summary="Document settings updated", entity_type="document_settings", entity_id=settings.id, changes=changes)
            await self.session.commit()
        return self._out(settings)
