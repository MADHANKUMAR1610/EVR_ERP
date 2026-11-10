"""HR → Performance (frontend performance.http.ts, contract E5), plus the HR setup additions (MODULE_8_DECISIONS.md)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.permissions import P
from app.schemas.common import Page, PageParams, page_params
from app.schemas.performance_schema import (
    ActionUpdateIn,
    AppraisalCycleOut,
    CompetencyIn,
    CompetencySetupOut,
    CycleIn,
    DevelopmentPlanOut,
    GoalIn,
    GoalOut,
    ManagerAssessmentIn,
    PerformanceConfigOut,
    PerformanceSummaryOut,
    PlanIn,
    ProgressIn,
    RatingScaleIn,
    RatingScaleSetupOut,
    RecommendationIn,
    RecommendationSetupOut,
    ReviewListItemOut,
    ReviewOut,
    VersionIn,
)
from app.services.employee_support import caller_context
from app.services.performance_service import PerformanceService
from app.utils.ids import path_id

router = APIRouter(prefix="/hr/performance", tags=["Performance"])
setup_router = APIRouter(prefix="/hr/setup", tags=["HR setup"])
Params = Annotated[PageParams, Depends(page_params)]
Dept = Annotated[str | None, Query(alias="departmentId")]
Cycle = Annotated[str | None, Query(alias="cycleId")]

VIEW = [Depends(require(P.PERFORMANCE_VIEW))]
CYCLES = [Depends(require(P.PERFORMANCE_CYCLES_MANAGE))]
GOALS = [Depends(require(P.GOALS_MANAGE))]
ASSESS = [Depends(require(P.REVIEWS_ASSESS))]
PLANS = [Depends(require(P.DEVELOPMENT_PLANS_MANAGE))]


async def _service(session, principal) -> PerformanceService:
    return PerformanceService(session, await caller_context(session, principal))


@router.get("/summary", response_model=PerformanceSummaryOut, dependencies=VIEW, summary="Performance dashboard")
async def summary(session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).summary()


@router.get("/configuration", response_model=PerformanceConfigOut, dependencies=VIEW, summary="Active rating scales and competencies")
async def configuration(session: DbSession):
    return await PerformanceService(session).configuration()


@router.get("/cycles", response_model=list[AppraisalCycleOut], dependencies=VIEW, summary="Appraisal cycles")
async def cycles(session: DbSession):
    return await PerformanceService(session).cycles()


@router.post("/cycles", response_model=AppraisalCycleOut, status_code=status.HTTP_201_CREATED, dependencies=CYCLES, summary="Create a cycle (draft)")
async def create_cycle(data: CycleIn, session: DbSession):
    return await PerformanceService(session).create_cycle(data)


@router.post("/cycles/{cycle_id}/advance", response_model=AppraisalCycleOut, dependencies=CYCLES, summary="Move a cycle to its next phase (409 while another cycle runs)")
async def advance_cycle(cycle_id: str, data: VersionIn, session: DbSession):
    return await PerformanceService(session).advance_cycle(path_id(cycle_id), data)


@router.get("/goals", response_model=Page[GoalOut], dependencies=VIEW, summary="Goals (organizational scope)")
async def goals(session: DbSession, principal: CurrentPrincipal, params: Params, cycle_id: Cycle = None,
                status_: Annotated[Literal["not_started", "on_track", "at_risk", "off_track", "completed", "cancelled"] | None, Query(alias="status")] = None, department_id: Dept = None):
    return await (await _service(session, principal)).goals(q=params.q, cycle_id=cycle_id, status=status_, department_id=department_id, sort=params.sort, page=params.page, page_size=params.page_size)


@router.get("/goals/{goal_id}", response_model=GoalOut, dependencies=VIEW, summary="One goal with its progress updates")
async def goal(goal_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).goal(path_id(goal_id))


@router.post("/goals", response_model=GoalOut, status_code=status.HTTP_201_CREATED, dependencies=GOALS, summary="Create a goal")
async def create_goal(data: GoalIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).create_goal(data)


@router.post("/goals/{goal_id}/progress", response_model=GoalOut, dependencies=GOALS, summary="Record progress (appended to the updates)")
async def record_progress(goal_id: str, data: ProgressIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).record_progress(path_id(goal_id), data)


@router.get("/reviews", response_model=Page[ReviewListItemOut], dependencies=VIEW, summary="Reviews (organizational scope, plus those assigned to the caller)")
async def reviews(session: DbSession, principal: CurrentPrincipal, params: Params, cycle_id: Cycle = None,
                  status_: Annotated[Literal["not_started", "self_assessment", "manager_review", "completed"] | None, Query(alias="status")] = None,
                  department_id: Dept = None, assigned_to_me: Annotated[bool, Query(alias="assignedToMe")] = False):
    return await (await _service(session, principal)).reviews(q=params.q, cycle_id=cycle_id, status=status_, department_id=department_id, assigned_to_me=assigned_to_me,
                                                             sort=params.sort, page=params.page, page_size=params.page_size)


@router.get("/reviews/{review_id}", response_model=ReviewOut, dependencies=[Depends(require(P.PERFORMANCE_VIEW, P.REVIEWS_ASSESS))], summary="One review; canAssess is decided here")
async def review(review_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).review(path_id(review_id))


@router.put("/reviews/{review_id}/manager-assessment", response_model=ReviewOut, dependencies=ASSESS, summary="Save a draft, or submit (completes the review); assigned reviewer only")
async def manager_assessment(review_id: str, data: ManagerAssessmentIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).save_manager_assessment(path_id(review_id), data)


@router.get("/development-plans", response_model=Page[DevelopmentPlanOut], dependencies=VIEW, summary="Development plans (organizational scope)")
async def plans(session: DbSession, principal: CurrentPrincipal, params: Params, status_: Annotated[Literal["active", "completed"] | None, Query(alias="status")] = None, department_id: Dept = None):
    return await (await _service(session, principal)).plans(q=params.q, status=status_, department_id=department_id, page=params.page, page_size=params.page_size)


@router.post("/development-plans", response_model=DevelopmentPlanOut, status_code=status.HTTP_201_CREATED, dependencies=PLANS, summary="Create a development plan")
async def create_plan(data: PlanIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).create_plan(data)


@router.patch("/development-plans/{plan_id}/actions/{action_id}", response_model=DevelopmentPlanOut, dependencies=PLANS, summary="Change an action's status (the plan completes when all are done)")
async def update_action(plan_id: str, action_id: str, data: ActionUpdateIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).update_action(path_id(plan_id), path_id(action_id), data)


# ---- HR setup (additions) ------------------------------------------------------------------------------------------------


@setup_router.get("/rating-scales", response_model=list[RatingScaleSetupOut], dependencies=CYCLES, summary="Rating scales")
async def setup_scales(session: DbSession):
    return await PerformanceService(session).setup_scales()


@setup_router.post("/rating-scales", response_model=RatingScaleSetupOut, status_code=status.HTTP_201_CREATED, dependencies=CYCLES, summary="Create a rating scale")
async def create_scale(data: RatingScaleIn, session: DbSession):
    return await PerformanceService(session).save_scale(None, data)


@setup_router.put("/rating-scales/{scale_id}", response_model=RatingScaleSetupOut, dependencies=CYCLES, summary="Update a rating scale (levels fixed once used)")
async def update_scale(scale_id: str, data: RatingScaleIn, session: DbSession):
    return await PerformanceService(session).save_scale(path_id(scale_id), data)


@setup_router.get("/competencies", response_model=list[CompetencySetupOut], dependencies=CYCLES, summary="Competencies")
async def setup_competencies(session: DbSession):
    return await PerformanceService(session).setup_competencies()


@setup_router.post("/competencies", response_model=CompetencySetupOut, status_code=status.HTTP_201_CREATED, dependencies=CYCLES, summary="Create a competency")
async def create_competency(data: CompetencyIn, session: DbSession):
    return await PerformanceService(session).save_competency(None, data)


@setup_router.put("/competencies/{competency_id}", response_model=CompetencySetupOut, dependencies=CYCLES, summary="Update a competency")
async def update_competency(competency_id: str, data: CompetencyIn, session: DbSession):
    return await PerformanceService(session).save_competency(path_id(competency_id), data)


@setup_router.get("/performance-recommendations", response_model=list[RecommendationSetupOut], dependencies=CYCLES, summary="Recommendation options")
async def setup_recommendations(session: DbSession):
    return await PerformanceService(session).setup_recommendations()


@setup_router.post("/performance-recommendations", response_model=RecommendationSetupOut, status_code=status.HTTP_201_CREATED, dependencies=CYCLES, summary="Create a recommendation option")
async def create_recommendation(data: RecommendationIn, session: DbSession):
    return await PerformanceService(session).save_recommendation(None, data)


@setup_router.put("/performance-recommendations/{rec_id}", response_model=RecommendationSetupOut, dependencies=CYCLES, summary="Update a recommendation option (code never changes)")
async def update_recommendation(rec_id: str, data: RecommendationIn, session: DbSession):
    return await PerformanceService(session).save_recommendation(path_id(rec_id), data)
