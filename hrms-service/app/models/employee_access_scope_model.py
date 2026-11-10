"""Organizational scope per Identity role: which employee records a role may reach (decision Q12)."""

import uuid

from sqlalchemy import Boolean, CheckConstraint, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin

SCOPE_TYPES = ("all", "departments", "headed_departments", "reporting_tree", "own_record")


class EmployeeAccessScope(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "employee_access_scope"

    role_code: Mapped[str] = mapped_column(String(100), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Only for scope_type 'departments'. Plain IDs (no FK on array elements); the service validates them.
    department_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (
        CheckConstraint(f"scope_type IN ({', '.join(repr(t) for t in SCOPE_TYPES)})", name="scope_type"),
        CheckConstraint("scope_type = 'departments' OR cardinality(department_ids) = 0", name="departments_only_for_departments"),
        CheckConstraint("scope_type <> 'departments' OR cardinality(department_ids) > 0", name="departments_listed"),
        # One row per role and scope type; a role may combine several types.
        CheckConstraint("length(role_code) > 0", name="role_code_not_empty"),
        UniqueConstraint("role_code", "scope_type"),
    )
