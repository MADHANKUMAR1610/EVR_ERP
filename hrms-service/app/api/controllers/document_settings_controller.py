"""/hr/setup/document-settings: the document expiry window (HR configuration, pending HR confirmation)."""

from fastapi import APIRouter, Depends

from app.api.dependencies import DbSession, require
from app.core.permissions import P
from app.schemas.employee_document_schema import DocumentSettingsIn, DocumentSettingsOut
from app.services.document_settings_service import DocumentSettingsService

router = APIRouter(prefix="/hr/setup/document-settings", tags=["HR setup"])


@router.get("", response_model=DocumentSettingsOut, dependencies=[Depends(require(P.SETTINGS_VIEW, P.SETTINGS_MANAGE))])
async def get_settings_(session: DbSession):
    return await DocumentSettingsService(session).get()


@router.put("", response_model=DocumentSettingsOut, dependencies=[Depends(require(P.SETTINGS_MANAGE))])
async def update_settings(data: DocumentSettingsIn, session: DbSession):
    return await DocumentSettingsService(session).update(data)
