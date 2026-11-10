"""Employee documents: metadata (the file itself is in private, encrypted storage), verification
history and the document settings HR configures."""

import uuid
from datetime import date

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin

VERIFICATION_STATUSES = ("pending", "verified", "rejected")


class EmployeeDocument(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """One uploaded copy. created_at / created_by_name are the upload time and uploader."""

    __tablename__ = "employee_document"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False)
    document_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_type.id", ondelete="RESTRICT"), nullable=False)
    file_name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Random key of the encrypted file in private storage; never sent to clients.
    storage_key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    remarks: Mapped[str | None] = mapped_column(String(200))
    document_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    verification_status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending", server_default="pending")

    events: Mapped[list["EmployeeDocumentEvent"]] = relationship(lazy="selectin", order_by="EmployeeDocumentEvent.created_at", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(f"verification_status IN ({', '.join(repr(s) for s in VERIFICATION_STATUSES)})", name="verification_status"),
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("expiry_date IS NULL OR document_date IS NULL OR expiry_date > document_date", name="expiry_after_document_date"),
        Index("ix_employee_document_employee_type", "employee_id", "document_type_id", "created_at"),
    )


class EmployeeDocumentEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Verification history of a document (oldest first). Append-only (database trigger)."""

    __tablename__ = "employee_document_event"

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_document.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint(f"status IN ({', '.join(repr(s) for s in VERIFICATION_STATUSES)})", name="status"),)


class DocumentSettings(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """Company document settings (one row). Values are HR configuration, pending HR confirmation."""

    __tablename__ = "document_settings"

    singleton: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"), unique=True)
    # Copies expiring within this many days count as "expiring soon" (contract B5; the mock used 30).
    expiry_window_days: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("singleton", name="single_row"),
        CheckConstraint("expiry_window_days BETWEEN 1 AND 366", name="expiry_window_range"),
    )
