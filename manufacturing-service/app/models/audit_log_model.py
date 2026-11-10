"""Append-only audit history of important identity and access actions.

Not editable through any API. The migration adds a trigger that rejects UPDATE, DELETE and
TRUNCATE, and the deployment guide grants the application role only INSERT and SELECT.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UUIDPrimaryKeyMixin, utcnow


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_log"

    # created_at / created_by: when and by whom (the actor). Never updated.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now())
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_name: Mapped[str] = mapped_column(String(200), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    entity_label: Mapped[str | None] = mapped_column(String(200))
    result: Mapped[str] = mapped_column(String(10), nullable=False)  # success | failure | denied
    request_id: Mapped[str | None] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    changes: Mapped[list[dict] | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_audit_log_created_at", "created_at"),
        Index("ix_audit_log_actor_user_id", "actor_user_id"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_module_action", "module", "action"),
        Index("ix_audit_log_request_id", "request_id"),
    )
