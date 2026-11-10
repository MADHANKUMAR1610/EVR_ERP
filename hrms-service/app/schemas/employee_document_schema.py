"""Employee documents (frontend documents.service.ts, contract B5). Field names match exactly."""

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel, ResponseModel, UtcDateTime
from app.schemas.employee_schema import NamedRefOut

VerificationStatus = Literal["pending", "verified", "rejected"]
ChecklistState = Literal["missing", "pending_verification", "verified", "rejected", "expired"]
CompletionStatus = Literal["complete", "awaiting_verification", "documents_pending"]


class VerificationEventOut(ResponseModel):
    status: VerificationStatus
    at: UtcDateTime
    by: str
    comment: str | None = None


class DocumentVerificationOut(ResponseModel):
    status: VerificationStatus
    reviewed_by: str | None = None
    reviewed_at: UtcDateTime | None = None
    comment: str | None = None
    history: list[VerificationEventOut]


class EmployeeDocumentOut(ResponseModel):
    id: str
    employee_id: str
    document_type: NamedRefOut
    file_name: str
    content_type: str
    size_bytes: int
    remarks: str | None = None
    document_date: str | None = None
    expiry_date: str | None = None
    uploaded_at: UtcDateTime
    uploaded_by: str
    previewable: bool
    verification: DocumentVerificationOut


class ChecklistTypeOut(ResponseModel):
    id: str
    name: str
    category: NamedRefOut
    required: bool
    expiry_required: bool


class ChecklistItemOut(ResponseModel):
    document_type: ChecklistTypeOut
    state: ChecklistState
    document: EmployeeDocumentOut | None
    expires_in_days: int | None


class CompletionCountsOut(ResponseModel):
    required_count: int
    completed_count: int
    verified_count: int
    awaiting_verification_count: int
    expiring_soon_count: int
    status: CompletionStatus


class DocumentChecklistOut(CompletionCountsOut):
    employee_id: str
    items: list[ChecklistItemOut]
    expiry_window_days: int


class ComplianceEmployeeOut(ResponseModel):
    id: str
    employee_code: str
    full_name: str
    department: NamedRefOut
    designation: NamedRefOut


class DocumentComplianceRowOut(CompletionCountsOut):
    employee: ComplianceEmployeeOut
    pending_documents: list[NamedRefOut]


class ComplianceSummaryOut(ResponseModel):
    required_documents_total: int
    required_documents_provided: int
    missing_required_documents: int
    employees_complete: int
    employees_with_pending_documents: int
    documents_awaiting_verification: int
    documents_expiring_soon: int
    expiry_window_days: int
    as_of: UtcDateTime


class AttentionDocumentOut(ResponseModel):
    id: str
    type_id: str
    type_name: str


class ExpiringItemOut(ResponseModel):
    employee: ComplianceEmployeeOut
    document: AttentionDocumentOut
    expiry_date: str
    expires_in_days: int


class AwaitingItemOut(ResponseModel):
    employee: ComplianceEmployeeOut
    document: AttentionDocumentOut
    uploaded_at: UtcDateTime


class MissingItemOut(ResponseModel):
    employee: ComplianceEmployeeOut
    missing: list[NamedRefOut]


class ExpiringListOut(ResponseModel):
    total: int
    items: list[ExpiringItemOut]


class AwaitingListOut(ResponseModel):
    total: int
    items: list[AwaitingItemOut]


class MissingListOut(ResponseModel):
    total: int
    items: list[MissingItemOut]


class ComplianceAttentionOut(ResponseModel):
    expiring_soon: ExpiringListOut
    awaiting_verification: AwaitingListOut
    missing_required: MissingListOut


class DocumentSettingsOut(ResponseModel):
    expiry_window_days: int
    version: int
    updated_at: UtcDateTime
    updated_by: str


class DocumentSettingsIn(CamelModel):
    expiry_window_days: int = Field(ge=1, le=366)
    version: int | None = None
