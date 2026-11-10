"""Platform: company settings (G7), notifications and preferences (B2, G8), integrations (G9).

Nothing is pre-filled: company settings stay empty until an administrator saves them. Integration secrets are
stored encrypted (Fernet) and never returned.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin

CATEGORIES = ("approval", "attendance", "leave", "overtime", "payroll", "employee", "documents", "performance", "system")


class CompanySettings(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """One row (singleton) once saved."""

    __tablename__ = "company_settings"

    singleton: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, unique=True)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    registration_number: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    tax_id: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    address: Mapped[dict] = mapped_column(JSONB, nullable=False)
    phone: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    time_zone: Mapped[str] = mapped_column(String(60), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    locale: Mapped[str] = mapped_column(String(35), nullable=False)
    date_format: Mapped[str] = mapped_column(String(12), nullable=False)
    time_format: Mapped[str] = mapped_column(String(3), nullable=False)
    week_start: Mapped[int] = mapped_column(Integer, nullable=False)
    working_days: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    fiscal_year_start_month: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint("singleton", name="singleton"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("week_start BETWEEN 1 AND 7", name="week_start"),
        CheckConstraint("fiscal_year_start_month BETWEEN 1 AND 12", name="fiscal_month"),
        CheckConstraint("time_format IN ('24h', '12h')", name="time_format"),
    )


class Notification(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """One notification for one user (Identity user id)."""

    __tablename__ = "notification"

    user_id: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(500))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(60), nullable=False)

    __table_args__ = (
        CheckConstraint("category IN (" + ", ".join(f"'{c}'" for c in CATEGORIES) + ")", name="category"),
        CheckConstraint("link IS NULL OR (link LIKE '/%' AND link NOT LIKE '//%')", name="app_relative_link"),
        Index("ix_notification_user_created", "user_id", "created_at"),
    )


class NotificationPreference(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A user's channel choices per category: {category: {in_app, email, sms}}. Missing = in-app on."""

    __tablename__ = "notification_preference"

    user_id: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    categories: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class Integration(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A connection to an outside system. `values` holds non-secret settings; `secrets` holds Fernet tokens."""

    __tablename__ = "integration"

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    values: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'"))
    secrets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'"))
    connection_status: Mapped[str] = mapped_column(String(12), nullable=False, default="unknown")
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        UniqueConstraint("code", name="uq_integration_code"),
        CheckConstraint("connection_status IN ('connected', 'disconnected', 'error', 'unknown')", name="connection_status"),
    )
