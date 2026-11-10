"""Shared pieces of the document services: response building and the checklist rules.

The checklist rules are the ones the contract proposes (B5, question D23, pending HR confirmation):
the latest copy of each type decides its state; a copy is expired when its expiry date is before
today; a required type is completed when its latest copy is verified or awaiting verification.
Which types are required, and the expiry window, are HR configuration.
"""

from dataclasses import dataclass
from datetime import date

from app.core.file_inspection import format_for_extension
from app.models.employee_document_model import EmployeeDocument
from app.models.reference_data_model import DocumentType
from app.schemas.employee_document_schema import DocumentVerificationOut, EmployeeDocumentOut, VerificationEventOut
from app.schemas.employee_schema import NamedRefOut


def previewable(content_type: str) -> bool:
    return content_type == "application/pdf" or content_type.startswith("image/")


def document_out(d: EmployeeDocument, type_name: str) -> EmployeeDocumentOut:
    history = [VerificationEventOut(status=e.status, at=e.created_at, by=e.created_by_name, comment=e.comment) for e in d.events]
    decision = next((e for e in reversed(d.events) if e.status != "pending"), None)
    return EmployeeDocumentOut(
        id=str(d.id),
        employee_id=str(d.employee_id),
        document_type=NamedRefOut(id=str(d.document_type_id), name=type_name),
        file_name=d.file_name,
        content_type=d.content_type,
        size_bytes=d.size_bytes,
        remarks=d.remarks,
        document_date=d.document_date.isoformat() if d.document_date else None,
        expiry_date=d.expiry_date.isoformat() if d.expiry_date else None,
        uploaded_at=d.created_at,
        uploaded_by=d.created_by_name,
        previewable=previewable(d.content_type),
        verification=DocumentVerificationOut(
            status=d.verification_status,
            reviewed_by=decision.created_by_name if decision else None,
            reviewed_at=decision.created_at if decision else None,
            comment=decision.comment if decision else None,
            history=history,
        ),
    )


def type_order(t: DocumentType, category_name: str) -> tuple:
    """Required first, grouped by category, then by name (the frontend's documented order)."""
    return (not t.required, category_name.lower(), t.name.lower())


def state_of(doc: EmployeeDocument | None, today: date) -> str:
    if doc is None:
        return "missing"
    if doc.expiry_date is not None and doc.expiry_date < today:
        return "expired"
    return {"pending": "pending_verification", "verified": "verified", "rejected": "rejected"}[doc.verification_status]


def expires_in(doc: EmployeeDocument | None, today: date) -> int | None:
    return (doc.expiry_date - today).days if doc is not None and doc.expiry_date is not None else None


@dataclass
class Completion:
    required_count: int = 0
    completed_count: int = 0
    verified_count: int = 0
    awaiting_verification_count: int = 0
    expiring_soon_count: int = 0
    pending_types: list | None = None  # required types not completed, as NamedRefOut

    @property
    def status(self) -> str:
        if self.completed_count < self.required_count:
            return "documents_pending"
        if self.awaiting_verification_count:
            return "awaiting_verification"
        return "complete"

    def counts(self) -> dict:
        return {
            "required_count": self.required_count, "completed_count": self.completed_count, "verified_count": self.verified_count,
            "awaiting_verification_count": self.awaiting_verification_count, "expiring_soon_count": self.expiring_soon_count, "status": self.status,
        }


def completion(types: list[DocumentType], latest: dict, today: date, window_days: int) -> Completion:
    """`types`: active types to count (optionally one category); `latest`: type id -> latest copy."""
    c = Completion(pending_types=[])
    for t in types:
        doc = latest.get(t.id)
        state = state_of(doc, today)
        days = expires_in(doc, today)
        if state in ("verified", "pending_verification") and days is not None and 0 <= days <= window_days:
            c.expiring_soon_count += 1
        if not t.required:
            continue
        c.required_count += 1
        if state in ("verified", "pending_verification"):
            c.completed_count += 1
        else:
            c.pending_types.append(NamedRefOut(id=str(t.id), name=t.name))
        if state == "verified":
            c.verified_count += 1
        if state == "pending_verification":
            c.awaiting_verification_count += 1
    return c


def extension_allowed(document_type: DocumentType, extension: str) -> bool:
    return extension in document_type.allowed_extensions and format_for_extension(extension) is not None
