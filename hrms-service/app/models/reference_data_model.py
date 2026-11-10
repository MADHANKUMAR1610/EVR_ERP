"""Company-configured reference lists used by employee records, documents and payroll fields.

All values are set by HR (setup file or /hr/setup endpoints); nothing here is a statutory rule.
"""

import uuid

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin

TONES = ("neutral", "info", "success", "warning", "danger", "primary")


class _CodedItem(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin):
    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class EmploymentType(_CodedItem, Base):
    __tablename__ = "employment_type"


class WorkLocation(_CodedItem, Base):
    __tablename__ = "work_location"


class AttendancePolicyOption(_CodedItem, Base):
    """Named attendance policy an employee follows (its rules live in HR Policies)."""

    __tablename__ = "attendance_policy_option"
    description: Mapped[str | None] = mapped_column(Text)


class OvertimePolicyOption(_CodedItem, Base):
    __tablename__ = "overtime_policy_option"
    description: Mapped[str | None] = mapped_column(Text)


class EmployeeStatus(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A step of the employee lifecycle, with the statuses it may move to."""

    __tablename__ = "employee_status"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    tone: Mapped[str] = mapped_column(String(10), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    allowed_on_create: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # HR configuration (pending HR confirmation, see docs/HR_CONFIRMATION_PENDING.md):
    # employees in this status no longer work here (excluded from pickers, counts, head/deactivation checks).
    employment_ended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # a reason must be entered when an employee is moved into this status.
    reason_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))

    transitions: Mapped[list["EmployeeStatusTransition"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", foreign_keys="EmployeeStatusTransition.from_status_id", order_by="EmployeeStatusTransition.to_code"
    )

    __table_args__ = (
        CheckConstraint("code ~ '^[a-z][a-z0-9_]*$'", name="code_format"),
        CheckConstraint(f"tone IN ({', '.join(repr(t) for t in TONES)})", name="tone"),
    )


class EmployeeStatusTransition(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "employee_status_transition"

    from_status_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee_status.id", ondelete="CASCADE"), nullable=False)
    to_code: Mapped[str] = mapped_column(String(30), ForeignKey("employee_status.code", ondelete="RESTRICT", onupdate="RESTRICT"), nullable=False)

    __table_args__ = (UniqueConstraint("from_status_id", "to_code"),)


class DocumentCategory(_CodedItem, Base):
    __tablename__ = "document_category"


class DocumentType(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A kind of employee document and its upload rules (company configuration)."""

    __tablename__ = "document_type"

    code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("document_category.id", ondelete="RESTRICT"), nullable=False, index=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    expiry_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    allowed_extensions: Mapped[list[str]] = mapped_column(ARRAY(String(10)), nullable=False)
    max_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    category: Mapped[DocumentCategory] = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint("max_size_bytes > 0", name="max_size_positive"),
        CheckConstraint("cardinality(allowed_extensions) > 0", name="has_extensions"),
    )


class PayrollFieldDefinition(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A payroll field shown on the employee form. The approved list comes from Finance/HR."""

    __tablename__ = "payroll_field_definition"

    key: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    max_length: Mapped[int | None] = mapped_column(Integer)
    pattern: Mapped[str | None] = mapped_column(String(200))
    pattern_message: Mapped[str | None] = mapped_column(String(200))
    options: Mapped[list[dict] | None] = mapped_column(JSONB)
    hint: Mapped[str | None] = mapped_column(String(300))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (
        CheckConstraint("key ~ '^[a-z][A-Za-z0-9]*$'", name="key_format"),
        CheckConstraint("type IN ('text', 'select', 'date', 'number')", name="type"),
    )
