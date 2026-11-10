import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin
from app.models.department_model import Department


class Designation(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A job title. It may be limited to some departments (empty = any department)."""

    __tablename__ = "designation"

    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    department_links: Mapped[list["DesignationDepartment"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="DesignationDepartment.created_at")

    __table_args__ = (CheckConstraint("code ~ '^[A-Z0-9-]{1,10}$'", name="code_format"),)


class DesignationDepartment(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "designation_department"

    designation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("designation.id", ondelete="CASCADE"), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("department.id", ondelete="RESTRICT"), nullable=False, index=True)

    department: Mapped[Department] = relationship(lazy="selectin")

    __table_args__ = (UniqueConstraint("designation_id", "department_id"),)
