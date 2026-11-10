"""Declarative base and the mixins every business table uses.

- `UUIDPrimaryKeyMixin`: opaque UUID ids (returned to the frontend as strings).
- `AuditMixin`: created_at / created_by / updated_at / updated_by. The user columns are filled by
  `app.database.audit_listener` from the authenticated principal, never from request data.
- `VersionMixin`: integer `version` for optimistic concurrency (SQLAlchemy `version_id_col`), so a
  concurrent update raises StaleDataError -> 409 STALE_VERSION.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, MetaData, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Stable constraint names so Alembic migrations are deterministic.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class AuditMixin:
    """The four mandatory audit columns, plus the actors' display names (the frontend shows
    "updated by <name>" and HRMS cannot read the Identity database). Set by the audit listener."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_name: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    updated_by_name: Mapped[str] = mapped_column(String(200), nullable=False)


class VersionMixin:
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    @declared_attr.directive
    def __mapper_args__(cls) -> dict:  # noqa: N805
        return {"version_id_col": cls.version}


# Tables that intentionally do not carry all four audit columns (documented in docs/DATABASE.md).
AUDIT_FIELD_EXCEPTIONS = {
    "audit_log": "Insert-only history: has created_at/created_by, never updated.",
}
