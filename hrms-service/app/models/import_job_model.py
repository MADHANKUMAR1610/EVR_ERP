"""Background job for an employee import (contract B6 / A10).

The submitted rows are kept only until the job finishes, then cleared (they contain personal data);
the outcome (counts and per-row failures) is kept for the job owner.
"""

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin

JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


class EmployeeImportJob(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """created_by / created_by_name is the job owner; only the owner may read the job."""

    __tablename__ = "employee_import_job"

    status: Mapped[str] = mapped_column(String(10), nullable=False, default="queued")
    skip_duplicates: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # The owner's identity at submission time, used to run the job with the owner's scope and permissions.
    principal: Mapped[dict] = mapped_column(JSONB, nullable=False)
    rows: Mapped[list[dict] | None] = mapped_column(JSONB)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{rowNumber, messages[]}], failed and skipped rows with their reasons.
    failures: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))

    __table_args__ = (
        CheckConstraint(f"status IN ({', '.join(repr(s) for s in JOB_STATUSES)})", name="status"),
        CheckConstraint("processed BETWEEN 0 AND total", name="progress_range"),
        CheckConstraint("created_count + skipped_count + failed_count = processed", name="counts_add_up"),
        Index("ix_employee_import_job_status_created", "status", "created_at"),
        Index("ix_employee_import_job_owner", "created_by", "created_at"),
    )


