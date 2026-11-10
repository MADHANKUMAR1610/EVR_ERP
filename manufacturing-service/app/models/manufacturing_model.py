"""Manufacturing (read-only APIs; owner decision): the shop-floor route, sales orders, work orders with their stage
records, materials, events, blocker and next action (API_CONTRACTS.md: Dashboard, Production work orders).

The tables are filled by production planning or an ERP import, not by these APIs (no write endpoints are
specified). Schedule status and variance are stored as supplied: how they are calculated is an open question.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


ORDER_STATUSES = ("draft", "confirmed", "in_design", "in_production", "testing", "ready_to_dispatch", "dispatched", "on_hold")
WORK_ORDER_STATUSES = ("not_started", "in_progress", "on_hold", "completed")
SCHEDULE_STATUSES = ("on_track", "at_risk", "delayed")
BLOCKER_TYPES = ("material", "quality", "engineering", "capacity")
STAGE_STATES = ("done", "current", "pending")
MATERIAL_STATUSES = ("issued", "available", "short", "on_order")


class WorkOrderStage(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A step of the shop-floor route (configuration; the UI never hard-codes stages)."""

    __tablename__ = "work_order_stage"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class SalesOrder(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "sales_order"

    order_no: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    rating_kva: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint(_in("status", ORDER_STATUSES), name="status"), CheckConstraint("quantity > 0", name="quantity"))


class WorkOrder(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "work_order"

    work_order_no: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    sales_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sales_order.id", ondelete="RESTRICT"), nullable=False, index=True)
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_of: Mapped[int] = mapped_column(Integer, nullable=False)
    rating_kva: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    voltage_ratio: Mapped[str] = mapped_column(String(40), nullable=False)
    vector_group: Mapped[str] = mapped_column(String(20), nullable=False)
    cooling: Mapped[str] = mapped_column(String(20), nullable=False)
    design_ref: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    stage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work_order_stage.id", ondelete="RESTRICT"), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(6), nullable=False, default="normal")
    work_centre: Mapped[str] = mapped_column(String(80), nullable=False)
    planned_start: Mapped[date] = mapped_column(Date, nullable=False)
    planned_finish: Mapped[date] = mapped_column(Date, nullable=False)
    customer_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # As supplied by production planning (calculation pending).
    schedule_status: Mapped[str] = mapped_column(String(10), nullable=False)
    variance_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocker_type: Mapped[str | None] = mapped_column(String(12))
    blocker_description: Mapped[str | None] = mapped_column(Text)
    blocker_since: Mapped[date | None] = mapped_column(Date)
    next_action_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    next_action_owner_id: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    next_action_owner_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    next_action_owner_role: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    next_action_due: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (
        CheckConstraint(_in("status", WORK_ORDER_STATUSES), name="status"),
        CheckConstraint(_in("schedule_status", SCHEDULE_STATUSES), name="schedule_status"),
        CheckConstraint("priority IN ('high', 'normal')", name="priority"),
        CheckConstraint("blocker_type IS NULL OR " + _in("blocker_type", BLOCKER_TYPES), name="blocker_type"),
        CheckConstraint("(blocker_type IS NULL) = (blocker_since IS NULL)", name="blocker_complete"),
        CheckConstraint("unit_index BETWEEN 1 AND unit_of", name="unit"),
        CheckConstraint("planned_finish >= planned_start", name="dates"),
        Index("ix_work_order_status_due", "status", "customer_due_date"),
    )


class WorkOrderStageRecord(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "work_order_stage_record"

    work_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work_order.id", ondelete="RESTRICT"), nullable=False)
    stage_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work_order_stage.id", ondelete="RESTRICT"), nullable=False)
    state: Mapped[str] = mapped_column(String(8), nullable=False)
    started_at: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (UniqueConstraint("work_order_id", "stage_id", name="uq_work_order_stage_record"), CheckConstraint(_in("state", STAGE_STATES), name="state"))


class WorkOrderMaterial(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "work_order_material"

    work_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work_order.id", ondelete="RESTRICT"), nullable=False, index=True)
    item: Mapped[str] = mapped_column(String(200), nullable=False)
    required: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date)

    __table_args__ = (CheckConstraint(_in("status", MATERIAL_STATUSES), name="status"),)


class WorkOrderEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Work-order history (append-only)."""

    __tablename__ = "work_order_event"

    work_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("work_order.id", ondelete="RESTRICT"), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
