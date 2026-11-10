"""Performance (frontend performance.service.ts, contract E5). Field names match the frontend exactly.
HR setup schemas (rating scales, competencies, recommendation options) are additions without a frontend screen."""

from typing import Literal

from pydantic import Field

from app.schemas.attendance_schema import EmployeeRefOut, WorkflowEventOut
from app.schemas.common import CamelModel, ResponseModel, UtcDateTime

CycleStatus = Literal["draft", "goal_setting", "self_assessment", "manager_review", "closed"]
GoalStatus = Literal["not_started", "on_track", "at_risk", "off_track", "completed", "cancelled"]
ReviewStatus = Literal["not_started", "self_assessment", "manager_review", "completed"]
ActionStatus = Literal["planned", "in_progress", "done"]
ActionType = Literal["training", "mentoring", "project", "certification", "other"]


class RatingLevelOut(ResponseModel):
    value: int
    label: str
    description: str


class RatingScaleOut(ResponseModel):
    id: str
    name: str
    levels: list[RatingLevelOut]


class CompetencyOut(ResponseModel):
    id: str
    name: str
    description: str


class RecommendationOptionOut(ResponseModel):
    code: str
    label: str


class AppraisalCycleOut(ResponseModel):
    id: str
    name: str
    period_from: str
    period_to: str
    status: CycleStatus
    goal_setting_due: str
    self_assessment_due: str
    manager_review_due: str
    rating_scale: RatingScaleOut | None
    competencies: list[CompetencyOut]
    recommendation_options: list[RecommendationOptionOut]
    participants: int
    completed_reviews: int
    history: list[WorkflowEventOut]
    version: int


class CycleIn(CamelModel):
    name: str = Field(max_length=120)
    period_from: str = Field(max_length=10)
    period_to: str = Field(max_length=10)
    goal_setting_due: str = Field(max_length=10)
    self_assessment_due: str = Field(max_length=10)
    manager_review_due: str = Field(max_length=10)
    rating_scale_id: str | None = None
    competency_ids: list[str] = Field(default_factory=list, max_length=100)


class PerformanceConfigOut(ResponseModel):
    rating_scales: list[RatingScaleOut]
    competencies: list[CompetencyOut]


class VersionIn(CamelModel):
    version: int


# --- Goals ----------------------------------------------------------------------------------------------------


class GoalKpiOut(ResponseModel):
    metric: str
    unit: str
    baseline: float | None
    target: float
    current: float | None
    direction: Literal["increase", "decrease"]


class GoalKpiIn(CamelModel):
    metric: str = Field(max_length=120)
    unit: str = Field(max_length=40)
    baseline: float | None = None
    target: float
    direction: Literal["increase", "decrease"]


class ProgressUpdateOut(ResponseModel):
    id: str
    at: UtcDateTime
    by: str
    progress: int
    status: GoalStatus
    value: float | None
    note: str


class CycleRefOut(ResponseModel):
    id: str
    name: str


class GoalOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    cycle: CycleRefOut
    title: str
    description: str
    kpi: GoalKpiOut | None
    weight: float | None
    due_date: str
    status: GoalStatus
    progress: int
    updates: list[ProgressUpdateOut]
    version: int


class GoalIn(CamelModel):
    employee_id: str
    cycle_id: str
    title: str = Field(max_length=200)
    description: str = Field(default="", max_length=4000)
    kpi: GoalKpiIn | None = None
    weight: float | None = None
    due_date: str = Field(max_length=10)


class ProgressIn(CamelModel):
    progress: int
    status: GoalStatus
    value: float | None = None
    note: str = Field(default="", max_length=2000)
    version: int


# --- Reviews ---------------------------------------------------------------------------------------------------


class CompetencyRatingModel(CamelModel):
    competency_id: str
    rating: int | None = None
    comment: str = Field(default="", max_length=2000)


class AssessmentOut(ResponseModel):
    overall_rating: int | None
    competency_ratings: list[CompetencyRatingModel]
    strengths: str
    improvements: str
    comments: str
    submitted_at: UtcDateTime | None


class AssessmentIn(CamelModel):
    overall_rating: int | None = None
    competency_ratings: list[CompetencyRatingModel] = Field(default_factory=list, max_length=100)
    strengths: str = Field(default="", max_length=4000)
    improvements: str = Field(default="", max_length=4000)
    comments: str = Field(default="", max_length=4000)


class ManagerAssessmentIn(CamelModel):
    assessment: AssessmentIn
    recommendation: str | None = Field(default=None, max_length=30)
    submit: bool
    version: int


class ReviewEmployeeOut(EmployeeRefOut):
    designation: str


class ReviewCycleOut(ResponseModel):
    id: str
    name: str
    status: CycleStatus
    manager_review_due: str


class ReviewerOut(ResponseModel):
    id: str
    name: str


class ReviewGoalOut(ResponseModel):
    id: str
    title: str
    progress: int
    status: GoalStatus


class ReviewOut(ResponseModel):
    id: str
    employee: ReviewEmployeeOut
    cycle: ReviewCycleOut
    reviewer: ReviewerOut
    status: ReviewStatus
    rating_scale: RatingScaleOut | None
    competencies: list[CompetencyOut]
    recommendation_options: list[RecommendationOptionOut]
    self: AssessmentOut | None
    manager: AssessmentOut | None
    recommendation: str | None
    goals: list[ReviewGoalOut]
    history: list[WorkflowEventOut]
    can_assess: bool
    version: int


class ReviewListItemOut(ResponseModel):
    id: str
    employee: ReviewEmployeeOut
    cycle: ReviewCycleOut
    reviewer: ReviewerOut
    status: ReviewStatus
    recommendation: str | None
    version: int
    self_submitted_at: UtcDateTime | None
    manager_submitted_at: UtcDateTime | None
    manager_rating_label: str | None


# --- Development plans -----------------------------------------------------------------------------------------


class DevelopmentActionOut(ResponseModel):
    id: str
    title: str
    type: ActionType
    due_date: str
    status: ActionStatus
    completed_at: UtcDateTime | None


class DevelopmentPlanOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    title: str
    focus: str
    owner: str
    status: Literal["active", "completed"]
    actions: list[DevelopmentActionOut]
    created_at: UtcDateTime
    version: int


class ActionIn(CamelModel):
    title: str = Field(max_length=200)
    type: ActionType
    due_date: str = Field(max_length=10)


class PlanIn(CamelModel):
    employee_id: str
    title: str = Field(max_length=200)
    focus: str = Field(default="", max_length=4000)
    actions: list[ActionIn] = Field(max_length=50)


class ActionUpdateIn(CamelModel):
    status: ActionStatus
    version: int


# --- Summary ---------------------------------------------------------------------------------------------------


class GoalCountsOut(ResponseModel):
    total: int
    at_risk: int
    off_track: int
    completed: int


class GoalAtRiskOut(ResponseModel):
    id: str
    employee: EmployeeRefOut
    title: str
    status: GoalStatus
    progress: int
    due_date: str


class ReviewsByStatusOut(ResponseModel):
    not_started: int = Field(serialization_alias="not_started")
    self_assessment: int = Field(serialization_alias="self_assessment")
    manager_review: int = Field(serialization_alias="manager_review")
    completed: int = Field(serialization_alias="completed")


class PerformanceSummaryOut(ResponseModel):
    active_cycle: AppraisalCycleOut | None
    reviews_by_status: ReviewsByStatusOut
    awaiting_my_assessment: int
    goals: GoalCountsOut
    goals_at_risk: list[GoalAtRiskOut]
    overdue_development_actions: int
    as_of: UtcDateTime


# --- HR setup (additions) --------------------------------------------------------------------------------------


class RatingLevelIn(CamelModel):
    value: int = Field(ge=0, le=100)
    label: str = Field(max_length=60)
    description: str = Field(default="", max_length=500)


class RatingScaleIn(CamelModel):
    name: str = Field(max_length=120)
    levels: list[RatingLevelIn] = Field(max_length=20)
    active: bool = True
    version: int | None = None


class RatingScaleSetupOut(RatingScaleOut):
    active: bool
    in_use: bool
    version: int


class CompetencyIn(CamelModel):
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=2000)
    active: bool = True
    version: int | None = None


class CompetencySetupOut(CompetencyOut):
    active: bool
    version: int


class RecommendationIn(CamelModel):
    code: str = Field(max_length=30)
    label: str = Field(max_length=120)
    active: bool = True
    version: int | None = None


class RecommendationSetupOut(RecommendationOptionOut):
    id: str
    active: bool
    version: int
