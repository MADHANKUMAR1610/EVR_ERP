"""Performance (Module 8, contract E5): rating scales, competencies, recommendation options, appraisal cycles
with their history, goals with progress updates, reviews with the manager assessment, development plans.

Nothing is pre-filled: scales, levels, competencies and recommendation options are entered by HR. No score is
ever computed; every rating is a level a person chose.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


WORKFLOW_ACTIONS = ("submitted", "approved", "rejected", "cancelled", "updated", "commented")


class RatingScale(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A rating scale; `levels` = [{"value": int, "label", "description"}], fixed once a cycle uses the scale."""

    __tablename__ = "rating_scale"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    levels: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class Competency(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "competency"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))


class PerformanceRecommendation(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    """A recommendation option (for example promotion, role change), entered by HR. Codes never change."""

    __tablename__ = "performance_recommendation"

    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))

    __table_args__ = (CheckConstraint("code ~ '^[a-z0-9_]{1,30}$'", name="code_format"),)


CYCLE_STATUSES = ("draft", "goal_setting", "self_assessment", "manager_review", "closed")


class AppraisalCycle(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "appraisal_cycle"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    goal_setting_due: Mapped[date] = mapped_column(Date, nullable=False)
    self_assessment_due: Mapped[date] = mapped_column(Date, nullable=False)
    manager_review_due: Mapped[date] = mapped_column(Date, nullable=False)
    rating_scale_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("rating_scale.id", ondelete="RESTRICT"))
    competency_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list, server_default=text("'{}'"))
    # Options in force when the cycle was created: [{"code", "label"}].
    recommendation_options: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'"))

    __table_args__ = (
        CheckConstraint(_in("status", CYCLE_STATUSES), name="status"),
        CheckConstraint("period_to >= period_from", name="dates"),
        CheckConstraint("goal_setting_due <= self_assessment_due AND self_assessment_due <= manager_review_due", name="due_order"),
    )


class AppraisalCycleEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Cycle history (WorkflowEvent shape), append-only."""

    __tablename__ = "appraisal_cycle_event"

    cycle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("appraisal_cycle.id", ondelete="RESTRICT"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint(_in("action", WORKFLOW_ACTIONS), name="action"),)


GOAL_STATUSES = ("not_started", "on_track", "at_risk", "off_track", "completed", "cancelled")


class Goal(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "goal"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False, index=True)
    cycle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("appraisal_cycle.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # {"metric", "unit", "baseline", "target", "direction"}; the current value is the latest progress value.
    kpi: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    weight: Mapped[float | None] = mapped_column(Numeric(5, 2))
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="not_started")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(_in("status", GOAL_STATUSES), name="status"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress"),
        CheckConstraint("weight IS NULL OR (weight > 0 AND weight <= 100)", name="weight"),
        CheckConstraint("status <> 'completed' OR progress = 100", name="completed_at_100"),
    )


class GoalProgressUpdate(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Append-only progress history of a goal."""

    __tablename__ = "goal_progress_update"

    goal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("goal.id", ondelete="RESTRICT"), nullable=False, index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    value: Mapped[float | None] = mapped_column(Numeric(18, 4))
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    __table_args__ = (CheckConstraint("progress BETWEEN 0 AND 100", name="progress"), CheckConstraint(_in("status", GOAL_STATUSES), name="status"))


REVIEW_STATUSES = ("not_started", "self_assessment", "manager_review", "completed")


class PerformanceReview(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "performance_review"

    cycle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("appraisal_cycle.id", ondelete="RESTRICT"), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False, index=True)
    reviewer_employee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_started")
    # {"overallRating", "competencyRatings": [{"competencyId", "rating", "comment"}], "strengths", "improvements", "comments", "submittedAt"}
    manager: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    manager_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recommendation: Mapped[str | None] = mapped_column(String(30))

    __table_args__ = (UniqueConstraint("cycle_id", "employee_id", name="uq_performance_review_cycle_employee"), CheckConstraint(_in("status", REVIEW_STATUSES), name="status"))


class PerformanceReviewEvent(UUIDPrimaryKeyMixin, AuditMixin, Base):
    """Review history (WorkflowEvent shape), append-only."""

    __tablename__ = "performance_review_event"

    review_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("performance_review.id", ondelete="RESTRICT"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (CheckConstraint(_in("action", WORKFLOW_ACTIONS), name="action"),)


ACTION_TYPES = ("training", "mentoring", "project", "certification", "other")
ACTION_STATUSES = ("planned", "in_progress", "done")


class DevelopmentPlan(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, Base):
    __tablename__ = "development_plan"

    employee_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    focus: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    owner_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active")

    __table_args__ = (CheckConstraint("status IN ('active', 'completed')", name="status"),)


class DevelopmentAction(UUIDPrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "development_action"

    plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("development_plan.id", ondelete="RESTRICT"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(15), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="planned")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(_in("type", ACTION_TYPES), name="type"),
        CheckConstraint(_in("status", ACTION_STATUSES), name="status"),
        CheckConstraint("(status = 'done') = (completed_at IS NOT NULL)", name="completed_at"),
        UniqueConstraint("plan_id", "position", name="uq_development_action_plan_position"),
        Index("ix_development_action_due", "status", "due_date"),
    )
