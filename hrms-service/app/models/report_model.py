"""Reports (Module 9, contract Part F): the append-only log of report runs and exports shown as report activity."""

from sqlalchemy import CheckConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class ReportActivity(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "report_activity"

    report_id: Mapped[str] = mapped_column(String(40), nullable=False)
    report_title: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    format: Mapped[str | None] = mapped_column(String(4))

    __table_args__ = (
        CheckConstraint("action IN ('generated', 'exported')", name="action"),
        CheckConstraint("format IS NULL OR format IN ('csv', 'xlsx')", name="format"),
        CheckConstraint("(action = 'exported') = (format IS NOT NULL)", name="format_with_export"),
        Index("ix_report_activity_created", "created_at"),
    )
