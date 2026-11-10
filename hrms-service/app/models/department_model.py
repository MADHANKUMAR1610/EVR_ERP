import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin


class Department(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A department of the company. Departments can be nested (parent_id)."""

    __tablename__ = "department"

    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("department.id", ondelete="RESTRICT"))
    # The department head is an employee (foreign key added by migration 0004; use_alter breaks the
    # department <-> employee cycle).
    head_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT", use_alter=True), index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (
        CheckConstraint("code ~ '^[A-Z0-9-]{1,10}$'", name="code_format"),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
        Index("ix_department_parent_id", "parent_id"),
    )
