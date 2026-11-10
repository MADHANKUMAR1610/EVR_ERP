import uuid
from datetime import time

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, SmallInteger, String, Time, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin
from app.models.department_model import Department


class Shift(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A working shift. Times are local company time; `overnight` means the shift ends the next day."""

    __tablename__ = "shift"

    code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    overnight: Mapped[bool] = mapped_column(Boolean, nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    grace_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    # ISO weekdays 1 (Monday) to 7 (Sunday).
    working_days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    department_links: Mapped[list["ShiftDepartment"]] = relationship(cascade="all, delete-orphan", lazy="selectin", order_by="ShiftDepartment.created_at")

    __table_args__ = (
        CheckConstraint("start_time <> end_time", name="start_differs_from_end"),
        CheckConstraint("overnight = (end_time < start_time)", name="overnight_matches_times"),
        CheckConstraint("break_minutes >= 0 AND grace_minutes >= 0", name="non_negative_minutes"),
        CheckConstraint("cardinality(working_days) > 0 AND working_days <@ ARRAY[1,2,3,4,5,6,7]::smallint[]", name="working_days"),
        Index("uq_shift_code_lower", func.lower(code), unique=True),
    )


class ShiftDepartment(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "shift_department"

    shift_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shift.id", ondelete="CASCADE"), nullable=False)
    department_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("department.id", ondelete="RESTRICT"), nullable=False, index=True)

    department: Mapped[Department] = relationship(lazy="selectin")

    __table_args__ = (UniqueConstraint("shift_id", "department_id"),)
