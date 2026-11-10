"""HR → Employee documents (frontend documents.http.ts, contract B5): list, upload, download, checklist."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response, status
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.config import get_settings
from app.core.errors import BadRequestError, LengthRequiredError, PayloadTooLargeError
from app.core.permissions import P
from app.schemas.employee_document_schema import DocumentChecklistOut, EmployeeDocumentOut
from app.services.employee_document_service import EmployeeDocumentService, UploadInput
from app.services.employee_support import caller_context
from app.utils.ids import path_id

router = APIRouter(prefix="/hr/employees", tags=["Employee documents"])

# Room for the multipart boundaries and the small text fields around the file.
FORM_OVERHEAD = 64 * 1024

UPLOAD_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file", "documentTypeId"],
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "documentTypeId": {"type": "string"},
                        "remarks": {"type": "string", "maxLength": 200},
                        "documentDate": {"type": "string", "format": "date"},
                        "expiryDate": {"type": "string", "format": "date"},
                    },
                }
            }
        },
    }
}


async def _service(session, principal) -> EmployeeDocumentService:
    return EmployeeDocumentService(session, await caller_context(session, principal))


@router.get("/{employee_id}/documents", response_model=list[EmployeeDocumentOut], dependencies=[Depends(require(P.DOCUMENTS_VIEW))], summary="An employee's documents, newest first")
async def list_documents(employee_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).list(path_id(employee_id))


@router.post(
    "/{employee_id}/documents", response_model=EmployeeDocumentOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(P.DOCUMENTS_UPLOAD))],
    summary="Upload one document (multipart/form-data)", openapi_extra=UPLOAD_SCHEMA,
)
async def upload_document(employee_id: str, request: Request, session: DbSession, principal: CurrentPrincipal):
    limit = get_settings().max_upload_bytes
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise LengthRequiredError()
    if int(length) > limit + FORM_OVERHEAD:
        # Refused before the body is read, so an oversized upload never reaches the disk.
        raise PayloadTooLargeError(details=[{"field": "file", "message": "The file is larger than allowed for this document type."}])
    try:
        form = await request.form(max_files=1, max_fields=10)
    except StarletteHTTPException:
        raise BadRequestError("Send the upload as multipart/form-data with one file.") from None
    try:
        upload = form.get("file")
        content = name = None
        if isinstance(upload, UploadFile):
            content = await upload.read(limit + 1)
            name = upload.filename

        def text(key: str) -> str | None:
            value = form.get(key)
            return value if isinstance(value, str) else None

        data = UploadInput(file_name=name, content=content, document_type_id=text("documentTypeId"), remarks=text("remarks"), document_date=text("documentDate"), expiry_date=text("expiryDate"))
    finally:
        await form.close()
    return await (await _service(session, principal)).upload(path_id(employee_id), data)


@router.get(
    "/{employee_id}/documents/{document_id}/content", dependencies=[Depends(require(P.DOCUMENTS_VIEW))], summary="Download or preview a document",
    responses={200: {"content": {"application/pdf": {}, "image/jpeg": {}, "image/png": {}}, "description": "The file"}},
)
async def download_document(employee_id: str, document_id: str, session: DbSession, principal: CurrentPrincipal) -> Response:
    file = await (await _service(session, principal)).download(path_id(employee_id), path_id(document_id))
    ascii_name = file.file_name.encode("ascii", "replace").decode().replace('"', "'").replace("?", "_")
    return Response(
        content=file.content,
        media_type=file.content_type,
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file.file_name)}",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store, private",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get("/{employee_id}/document-checklist", response_model=DocumentChecklistOut, dependencies=[Depends(require(P.DOCUMENTS_VIEW))], summary="One employee's document completion")
async def checklist(employee_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).checklist(path_id(employee_id))
