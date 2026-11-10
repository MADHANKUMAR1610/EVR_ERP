"""Employee documents: list, upload, download and one employee's checklist (contract B5).

Access: the endpoint permission (controller), then the employee must be inside the caller's
organizational scope (404 otherwise), then the document must belong to that employee (404).
Every list, checklist view, download and upload is written to the audit log.

Upload checks, in order: document type, metadata, extension allowed for the type, size (413),
content really is the declared format, malware scan. Only then is the file encrypted and stored.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import malware_scan, storage
from app.core.config import get_settings
from app.core.crypto import EncryptionUnavailableError
from app.core.errors import NotFoundError, PayloadTooLargeError, ServiceUnavailableError
from app.core.file_inspection import detect, extension_of, format_for_extension, safe_file_name
from app.models.employee_document_model import EmployeeDocument, EmployeeDocumentEvent
from app.models.employee_model import Employee, EmployeeHistory
from app.models.reference_data_model import DocumentCategory, DocumentType
from app.repositories.employee_document_repository import EmployeeDocumentRepository
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.employee_document_schema import ChecklistItemOut, ChecklistTypeOut, DocumentChecklistOut, EmployeeDocumentOut
from app.schemas.employee_schema import NamedRefOut
from app.services.audit_service import AuditService
from app.services.document_support import completion, document_out, expires_in, extension_allowed, state_of, type_order
from app.services.employee_scope_service import EmployeeScopeService
from app.services.employee_support import Caller, company_today, parse_date
from app.utils.ids import body_id
from app.utils.validation import FieldErrors

MB = 1024 * 1024


def _size_label(n: int) -> str:
    return f"{n / MB:g} MB" if n >= MB else f"{max(1, n // 1024)} KB"


@dataclass
class UploadInput:
    file_name: str | None
    content: bytes | None
    document_type_id: str | None
    remarks: str | None
    document_date: str | None
    expiry_date: str | None


@dataclass
class Download:
    content: bytes
    file_name: str
    content_type: str


class EmployeeDocumentService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.repo = EmployeeDocumentRepository(session)
        self.employees = EmployeeRepository(session)
        self.audit = AuditService(session)
        self.scope_clause = EmployeeScopeService.clause(caller.scope)

    async def _employee(self, employee_id: uuid.UUID) -> Employee:
        employee = await self.employees.get_visible(employee_id, self.scope_clause)
        if employee is None:
            raise NotFoundError()  # out of scope looks the same as missing (A4)
        return employee

    async def _types(self) -> dict[uuid.UUID, DocumentType]:
        return {t.id: t for t in (await self.session.scalars(select(DocumentType))).all()}

    def _record(self, action: str, summary: str, employee: Employee, **kw) -> None:
        self.audit.record(module="Documents", action=action, summary=summary, entity_type="employee", entity_id=employee.id, entity_label=employee.full_name, **kw)

    # ---- List ---------------------------------------------------------------------------------------

    async def list(self, employee_id: uuid.UUID) -> list[EmployeeDocumentOut]:
        employee = await self._employee(employee_id)
        types = await self._types()
        docs = await self.repo.for_employee(employee.id)
        self._record("document.list_viewed", f"Documents of {employee.employee_code} viewed", employee)
        await self.session.commit()
        return [document_out(d, types[d.document_type_id].name) for d in docs]

    # ---- Download -----------------------------------------------------------------------------------

    async def download(self, employee_id: uuid.UUID, document_id: uuid.UUID) -> Download:
        employee = await self._employee(employee_id)
        document = await self.repo.get(employee.id, document_id)
        if document is None:
            raise NotFoundError()
        try:
            content = storage.get(document.storage_key)
        except (storage.StorageError, EncryptionUnavailableError):
            raise ServiceUnavailableError("This document cannot be opened right now.") from None
        if hashlib.sha256(content).hexdigest() != document.sha256:
            raise ServiceUnavailableError("This document cannot be opened right now.")
        self._record("document.downloaded", f"Document {document.file_name} of {employee.employee_code} opened", employee, changes=[{"field": "documentId", "before": None, "after": str(document.id)}])
        await self.session.commit()
        return Download(content=content, file_name=document.file_name, content_type=document.content_type)

    # ---- Upload -------------------------------------------------------------------------------------

    async def upload(self, employee_id: uuid.UUID, data: UploadInput) -> EmployeeDocumentOut:
        employee = await self._employee(employee_id)
        err = FieldErrors()

        document_type: DocumentType | None = None
        type_id = body_id(data.document_type_id)
        if not data.document_type_id:
            err.add("documentTypeId", "Select a document type.")
        else:
            document_type = await self.session.get(DocumentType, type_id) if type_id else None
            if document_type is None:
                err.add("documentTypeId", "Select an existing document type.")
            elif not document_type.active:
                err.add("documentTypeId", "This document type is no longer in use.")

        remarks = (data.remarks or "").strip() or None
        if remarks and len(remarks) > 200:
            err.add("remarks", "Keep notes under 200 characters.")
        document_date = expiry_date = None
        try:
            document_date = parse_date(data.document_date)
        except ValueError:
            err.add("documentDate", "Enter a valid date.")
        try:
            expiry_date = parse_date(data.expiry_date)
        except ValueError:
            err.add("expiryDate", "Enter a valid date.")
        if document_type and document_type.expiry_required and expiry_date is None and not err.has("expiryDate"):
            err.add("expiryDate", f"Enter the expiry date for the {document_type.name.lower()}.")
        if expiry_date and document_date and expiry_date <= document_date:
            err.add("expiryDate", "The expiry date must be after the document date.")

        file_name = safe_file_name(data.file_name)
        content = data.content
        if content is None:
            err.add("file", "Choose a file to upload.")
        elif len(content) == 0:
            err.add("file", "The file is empty.")
        elif document_type is not None:
            extension = extension_of(file_name)
            limit = min(document_type.max_size_bytes, get_settings().max_upload_bytes)
            if not extension_allowed(document_type, extension):
                allowed = ", ".join(e for e in document_type.allowed_extensions if format_for_extension(e))
                err.add("file", f"This document type accepts {allowed} files." if allowed else "This document type has no supported file types configured.")
            elif len(content) > limit:
                raise PayloadTooLargeError(
                    f"The file is larger than allowed for this document type ({_size_label(limit)}).",
                    details=[{"field": "file", "message": f"The file is larger than allowed for this document type ({_size_label(limit)})."}],
                )
            else:
                detected = detect(content)
                if detected is None or extension not in detected.extensions:
                    err.add("file", f"The file content is not a valid {extension} file.")
        err.raise_if_any()
        assert document_type is not None and content is not None
        detected = detect(content)
        assert detected is not None

        try:
            await malware_scan.scan(content)
        except malware_scan.MalwareFound:
            self._record("document.rejected_malware", f"Upload for {employee.employee_code} refused by the virus scan", employee)
            await self.session.commit()
            err.add("file", "The file was rejected by the virus scan.")
            err.raise_if_any()

        try:
            key = storage.put(content)
        except (OSError, EncryptionUnavailableError):
            raise ServiceUnavailableError("Documents cannot be stored right now.") from None
        try:
            document = EmployeeDocument(
                employee_id=employee.id, document_type_id=document_type.id, file_name=file_name, content_type=detected.content_type, size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(), storage_key=key, remarks=remarks, document_date=document_date, expiry_date=expiry_date,
                verification_status="pending", events=[EmployeeDocumentEvent(status="pending", comment="Uploaded")],
            )
            self.repo.add(document)
            # History shows the document type only; file names can themselves be sensitive.
            self.session.add(EmployeeHistory(employee_id=employee.id, action="document_uploaded", summary=f"Document uploaded: {document_type.name}", changes=["Documents"]))
            await self.session.flush()
            self._record("document.uploaded", f"{document_type.name} uploaded for {employee.employee_code}", employee, changes=[{"field": "documentId", "before": None, "after": str(document.id)}])
            await self.session.commit()
        except BaseException:
            storage.delete(key)  # never leave an unreferenced file behind
            raise
        await self.session.refresh(document, ["events"])
        return document_out(document, document_type.name)

    # ---- Checklist ----------------------------------------------------------------------------------

    async def checklist(self, employee_id: uuid.UUID) -> DocumentChecklistOut:
        employee = await self._employee(employee_id)
        types = [t for t in (await self._types()).values() if t.active]
        categories = {c.id: c for c in (await self.session.scalars(select(DocumentCategory))).all()}
        types.sort(key=lambda t: type_order(t, categories[t.category_id].name if t.category_id in categories else ""))
        latest = {k[1]: d for k, d in (await self.repo.latest_per_type([employee.id])).items()}
        settings = await self.repo.settings()
        today = company_today()
        result = completion(types, latest, today, settings.expiry_window_days)
        items = []
        for t in types:
            doc = latest.get(t.id)
            cat = categories.get(t.category_id)
            items.append(
                ChecklistItemOut(
                    document_type=ChecklistTypeOut(id=str(t.id), name=t.name, category=NamedRefOut(id=str(t.category_id), name=cat.name if cat else ""), required=t.required, expiry_required=t.expiry_required),
                    state=state_of(doc, today),
                    document=document_out(doc, t.name) if doc else None,
                    expires_in_days=expires_in(doc, today),
                )
            )
        self._record("document.checklist_viewed", f"Document checklist of {employee.employee_code} viewed", employee)
        await self.session.commit()
        return DocumentChecklistOut(employee_id=str(employee.id), items=items, expiry_window_days=settings.expiry_window_days, **result.counts())
