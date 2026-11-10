"""Identity: roles, user accounts, sessions and account history (contract B1, G2, G3).

Passwords are stored only as Argon2id hashes. Employee, department and manager names are a snapshot taken
from HRMS when the account is saved (HRMS owns those records; Identity keeps only their ids and names).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin

USER_STATUSES = ("active", "invited", "inactive", "locked")


class Role(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "role"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Codes as stored: wildcards and unknown codes are kept unchanged (G3).
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False, default=list, server_default=text("'{}'"))
    system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (Index("uq_role_name_lower", func.lower(name), unique=True),)


class UserAccount(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "user_account"

    username: Mapped[str] = mapped_column(String(60), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    password_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    role_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    # Snapshot of HRMS records (ids are opaque strings, no foreign key across services).
    department_id: Mapped[str | None] = mapped_column(String(60))
    department_name: Mapped[str | None] = mapped_column(String(160))
    employee_id: Mapped[str | None] = mapped_column(String(60))
    employee_code: Mapped[str | None] = mapped_column(String(40))
    employee_name: Mapped[str | None] = mapped_column(String(160))
    manager_id: Mapped[str | None] = mapped_column(String(60))
    manager_name: Mapped[str | None] = mapped_column(String(160))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("status IN ('active', 'invited', 'inactive', 'locked')", name="status"),
        Index("uq_user_account_username_lower", func.lower(username), unique=True),
        Index("uq_user_account_email_lower", func.lower(email), unique=True),
        Index("uq_user_account_employee_id", "employee_id", unique=True, postgresql_where=text("employee_id IS NOT NULL")),
    )


class UserSession(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """A signed-in session. The token's `sid` is this id; a revoked session's tokens stop working everywhere."""

    __tablename__ = "user_session"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(40))
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class UserAccountEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Account history shown on the user screen (append-only). Never contains a password."""

    __tablename__ = "user_account_event"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user_account.id", ondelete="RESTRICT"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)


class ServiceTokenIssue(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Service tokens issued to other services (client-credentials), by token id, for the audit of service access."""

    __tablename__ = "service_token_issue"

    client_id: Mapped[str] = mapped_column(String(60), nullable=False)
    jti: Mapped[str] = mapped_column(String(60), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("jti", name="uq_service_token_issue_jti"),)
