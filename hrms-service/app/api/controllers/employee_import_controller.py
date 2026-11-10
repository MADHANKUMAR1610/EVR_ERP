"""HR → Employee import (frontend employeeImport.http.ts, contract B6). Everything needs hr.employees:import.

Contract endpoints: fields, validate, start (202), job status. Additions for API clients (the frontend
does not need them): template download, server-side reading of a .xlsx/.csv file, failure report CSV.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.config import get_settings
from app.core.errors import BadRequestError, LengthRequiredError, PayloadTooLargeError
from app.core.permissions import P
from app.schemas.import_schema import ImportFieldOut, ImportJobOut, ImportRowsIn, ImportStartIn, ImportValidationOut, ParsedFileOut
from app.services.audit_service import AuditService
from app.services.employee_import_service import EmployeeImportService
from app.services.employee_support import caller_context
from app.services.import_file_service import parse_file, template
from app.utils.ids import path_id

router = APIRouter(prefix="/hr/employee-imports", tags=["Employee import"], dependencies=[Depends(require(P.EMPLOYEES_IMPORT))])

FILE_SCHEMA = {
    "requestBody": {
        "required": True,
        "content": {"multipart/form-data": {"schema": {"type": "object", "required": ["file"], "properties": {"file": {"type": "string", "format": "binary", "description": ".xlsx (first worksheet) or .csv"}}}}},
    }
}


async def _service(session, principal) -> EmployeeImportService:
    return EmployeeImportService(session, await caller_context(session, principal))


@router.get("/fields", response_model=list[ImportFieldOut], response_model_exclude_none=True, summary="Import columns (the template is generated from these)")
async def fields(session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).fields()


@router.post("/validate", response_model=ImportValidationOut, summary="Check every row without saving anything (preview)")
async def validate(data: ImportRowsIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).validate(data.rows)


@router.post("", response_model=ImportJobOut, status_code=status.HTTP_202_ACCEPTED, summary="Start an import job (rows are re-checked when imported)")
async def start(data: ImportStartIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).start(data.rows, data.skip_duplicates)


@router.get("/template", summary="Download the import template (.xlsx or .csv)", responses={200: {"content": {"text/csv": {}, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
async def download_template(session: DbSession, principal: CurrentPrincipal, format: Annotated[Literal["xlsx", "csv"], Query()] = "xlsx") -> Response:
    content, media_type, name = template(await (await _service(session, principal)).fields(), format)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.post("/file-rows", response_model=ParsedFileOut, summary="Read a .xlsx/.csv file into import rows (nothing is stored)", openapi_extra=FILE_SCHEMA)
async def file_rows(request: Request, session: DbSession, principal: CurrentPrincipal):
    limit = get_settings().import_max_file_bytes
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise LengthRequiredError()
    if int(length) > limit + 64 * 1024:
        raise PayloadTooLargeError(details=[{"field": "file", "message": f"The file is larger than {limit / (1024 * 1024):g} MB."}])
    try:
        form = await request.form(max_files=1, max_fields=2)
    except StarletteHTTPException:
        raise BadRequestError("Send the file as multipart/form-data.") from None
    try:
        upload = form.get("file")
        content = await upload.read(limit + 1) if isinstance(upload, UploadFile) else None
        name = upload.filename if isinstance(upload, UploadFile) else None
    finally:
        await form.close()
    service = await _service(session, principal)
    parsed = parse_file(name, content, await service.fields())
    AuditService(session).record(module="Employees", action="employee_import.file_read", summary=f"Import file read: {len(parsed.rows)} row(s)")
    await session.commit()
    return parsed


@router.get("/{job_id}", response_model=ImportJobOut, summary="Import job status (job owner only)")
async def job(job_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).job(path_id(job_id))


@router.get("/{job_id}/failures.csv", summary="Failed and skipped rows as CSV (job owner only)", responses={200: {"content": {"text/csv": {}}}})
async def failure_report(job_id: str, session: DbSession, principal: CurrentPrincipal) -> Response:
    content, name = await (await _service(session, principal)).failure_report(path_id(job_id))
    return Response(content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})
