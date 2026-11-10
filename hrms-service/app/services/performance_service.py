"""Performance (Module 8, contract E5; MODULE_8_DECISIONS.md).

- Scales, competencies and recommendation options are HR-entered (setup additions). No score is ever computed.
- Cycles: draft -> goal_setting -> self_assessment -> manager_review -> closed, one phase per advance; only one
  cycle runs at a time (409). Leaving draft creates one review per participant (pending rule 118).
- Goals: optional KPI and weight (employee's total in the cycle <= 100%), due date inside the cycle; progress
  updates are appended; a completed goal is at 100%.
- Reviews: the assigned reviewer (reporting manager) with hr.performance-reviews:assess saves a draft or submits
  while the cycle is in manager_review; submit completes the review.
- Development plans complete when every action is done.
Lists follow the caller's organizational scope; a reviewer also sees the reviews assigned to them.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ConflictError, ForbiddenError, InvalidTransitionError, NotFoundError, ValidationFailedError
from app.core.permissions import P
from app.models.designation_model import Designation
from app.models.employee_model import Employee
from app.models.performance_model import (
    AppraisalCycle,
    AppraisalCycleEvent,
    Competency,
    DevelopmentAction,
    DevelopmentPlan,
    Goal,
    GoalProgressUpdate,
    PerformanceRecommendation,
    PerformanceReview,
    PerformanceReviewEvent,
    RatingScale,
)
from app.models.reference_data_model import EmployeeStatus
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import text_match
from app.schemas.attendance_schema import WorkflowEventOut
from app.schemas.common import Page
from app.schemas.performance_schema import (
    ActionUpdateIn,
    AppraisalCycleOut,
    AssessmentOut,
    CompetencyIn,
    CompetencyOut,
    CompetencyRatingModel,
    CompetencySetupOut,
    CycleIn,
    CycleRefOut,
    DevelopmentActionOut,
    DevelopmentPlanOut,
    GoalAtRiskOut,
    GoalCountsOut,
    GoalIn,
    GoalKpiOut,
    GoalOut,
    ManagerAssessmentIn,
    PerformanceConfigOut,
    PerformanceSummaryOut,
    PlanIn,
    ProgressIn,
    ProgressUpdateOut,
    RatingLevelOut,
    RatingScaleIn,
    RatingScaleOut,
    RatingScaleSetupOut,
    RecommendationIn,
    RecommendationOptionOut,
    RecommendationSetupOut,
    ReviewCycleOut,
    ReviewEmployeeOut,
    ReviewerOut,
    ReviewGoalOut,
    ReviewListItemOut,
    ReviewOut,
    ReviewsByStatusOut,
    VersionIn,
)
from app.services.attendance.attendance_read_service import employee_ref
from app.services.audit_service import AuditService, diff
from app.services.employee_scope_service import EmployeeScopeService, caller_employee_id
from app.services.employee_support import Caller, company_today, parse_date
from app.services.payroll.common import departments
from app.utils.ids import body_id
from app.utils.validation import FieldErrors, ensure_version

MODULE = "Performance"
NEXT_PHASE = {"draft": "goal_setting", "goal_setting": "self_assessment", "self_assessment": "manager_review", "manager_review": "closed"}
PHASE_LABEL = {"goal_setting": "goal setting", "self_assessment": "self-assessment", "manager_review": "manager review", "closed": "closed"}
RUNNING = ("goal_setting", "self_assessment", "manager_review")
RECOMMENDATION_CODE = re.compile(r"^[a-z0-9_]{1,30}$")
NOT_ASSIGNED = ReviewerOut(id="", name="Not assigned")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _date(err: FieldErrors, field: str, value: str | None, label: str) -> date | None:
    try:
        d = parse_date(value)
    except ValueError:
        d = None
    if d is None:
        err.add(field, f"Enter the {label} as YYYY-MM-DD.")
    return d


def _num(v) -> float | None:
    return None if v is None else float(Decimal(str(v)))


def _scale_out(s: RatingScale | None) -> RatingScaleOut | None:
    if s is None:
        return None
    return RatingScaleOut(id=str(s.id), name=s.name, levels=[RatingLevelOut(**lv) for lv in sorted(s.levels, key=lambda x: x["value"])])


def _events(rows) -> list[WorkflowEventOut]:
    return [WorkflowEventOut(id=str(e.id), action=e.action, at=e.created_at, by=e.created_by_name, comment=e.comment) for e in rows]


class PerformanceService:
    def __init__(self, session: AsyncSession, caller: Caller | None = None):
        self.session = session
        self.caller = caller
        self.audit = AuditService(session)

    # ---- Shared lookups ----------------------------------------------------------------------------------------

    def _scope(self):
        return EmployeeScopeService.clause(self.caller.scope)

    async def _employee_in_scope(self, employee_id: uuid.UUID | None) -> Employee | None:
        if employee_id is None:
            return None
        return await self.session.scalar(select(Employee).where(Employee.id == employee_id, self._scope()))

    async def _competencies(self) -> dict[uuid.UUID, Competency]:
        return {c.id: c for c in (await self.session.scalars(select(Competency))).all()}

    async def _cycle(self, cycle_id: uuid.UUID, *, for_update: bool = False) -> AppraisalCycle:
        stmt = select(AppraisalCycle).where(AppraisalCycle.id == cycle_id)
        c = await self.session.scalar(stmt.with_for_update() if for_update else stmt)
        if c is None:
            raise NotFoundError()
        return c

    def _me(self) -> uuid.UUID | None:
        return caller_employee_id(self.caller.principal) if self.caller else None

    # ---- Setup: rating scales, competencies, recommendation options (additions) -------------------------------------

    async def _scales_in_use(self) -> set[uuid.UUID]:
        return set((await self.session.scalars(select(AppraisalCycle.rating_scale_id).where(AppraisalCycle.rating_scale_id.is_not(None)))).all())

    async def setup_scales(self) -> list[RatingScaleSetupOut]:
        used = await self._scales_in_use()
        rows = (await self.session.scalars(select(RatingScale).order_by(func.lower(RatingScale.name)))).all()
        return [RatingScaleSetupOut(**_scale_out(s).model_dump(), active=s.active, in_use=s.id in used, version=s.version) for s in rows]

    async def save_scale(self, scale_id: uuid.UUID | None, data: RatingScaleIn) -> RatingScaleSetupOut:
        err = FieldErrors()
        name = data.name.strip()
        if not 2 <= len(name) <= 120:
            err.add("name", "Enter a name of 2-120 characters.")
        if len(data.levels) < 2:
            err.add("levels", "A scale needs at least two levels.")
        values = [lv.value for lv in data.levels]
        if len(set(values)) != len(values):
            err.add("levels", "Each level needs a different value.")
        labels = [lv.label.strip() for lv in data.levels]
        if any(not label for label in labels) or len({label.lower() for label in labels}) != len(labels):
            err.add("levels", "Each level needs a different label.")
        if await self.session.scalar(select(RatingScale.id).where(func.lower(RatingScale.name) == name.lower(), RatingScale.id != (scale_id or uuid.uuid4()))):
            err.add("name", "Another scale already uses this name.")
        levels = [{"value": lv.value, "label": lv.label.strip(), "description": lv.description.strip()} for lv in sorted(data.levels, key=lambda x: x.value)]
        before: dict = {}
        if scale_id is not None:
            s = await self.session.get(RatingScale, scale_id)
            if s is None:
                raise NotFoundError()
            ensure_version(s, data.version)
            if levels != sorted(s.levels, key=lambda x: x["value"]) and scale_id in await self._scales_in_use():
                err.add("levels", "The levels of a scale used by a cycle cannot change. Create a new scale instead.")
        err.raise_if_any()
        if scale_id is None:
            s = RatingScale(name=name, levels=levels, active=data.active)
            self.session.add(s)
        else:
            before = {"name": s.name, "levels": s.levels, "active": s.active}
            s.name, s.levels, s.active = name, levels, data.active
        await self.session.flush()
        self.audit.record(module=MODULE, action="rating_scale.saved", summary=f"Rating scale {name} saved", entity_type="rating_scale", entity_id=s.id, entity_label=name,
                          changes=diff(before, {"name": name, "levels": levels, "active": data.active}))
        await self.session.commit()
        return RatingScaleSetupOut(**_scale_out(s).model_dump(), active=s.active, in_use=s.id in await self._scales_in_use(), version=s.version)

    async def setup_competencies(self) -> list[CompetencySetupOut]:
        rows = (await self.session.scalars(select(Competency).order_by(func.lower(Competency.name)))).all()
        return [CompetencySetupOut(id=str(c.id), name=c.name, description=c.description, active=c.active, version=c.version) for c in rows]

    async def save_competency(self, competency_id: uuid.UUID | None, data: CompetencyIn) -> CompetencySetupOut:
        err = FieldErrors()
        name = data.name.strip()
        if not 2 <= len(name) <= 120:
            err.add("name", "Enter a name of 2-120 characters.")
        if await self.session.scalar(select(Competency.id).where(func.lower(Competency.name) == name.lower(), Competency.id != (competency_id or uuid.uuid4()))):
            err.add("name", "Another competency already uses this name.")
        err.raise_if_any()
        if competency_id is None:
            c = Competency(name=name, description=data.description.strip(), active=data.active)
            self.session.add(c)
        else:
            c = await self.session.get(Competency, competency_id)
            if c is None:
                raise NotFoundError()
            ensure_version(c, data.version)
            c.name, c.description, c.active = name, data.description.strip(), data.active
        await self.session.flush()
        self.audit.record(module=MODULE, action="competency.saved", summary=f"Competency {name} saved", entity_type="competency", entity_id=c.id, entity_label=name)
        await self.session.commit()
        return CompetencySetupOut(id=str(c.id), name=c.name, description=c.description, active=c.active, version=c.version)

    async def setup_recommendations(self) -> list[RecommendationSetupOut]:
        rows = (await self.session.scalars(select(PerformanceRecommendation).order_by(PerformanceRecommendation.code))).all()
        return [RecommendationSetupOut(id=str(r.id), code=r.code, label=r.label, active=r.active, version=r.version) for r in rows]

    async def save_recommendation(self, rec_id: uuid.UUID | None, data: RecommendationIn) -> RecommendationSetupOut:
        err = FieldErrors()
        code, label = data.code.strip().lower(), data.label.strip()
        if not RECOMMENDATION_CODE.match(code):
            err.add("code", "Use 1-30 lower-case letters, digits or '_'.")
        if not 2 <= len(label) <= 120:
            err.add("label", "Enter a label of 2-120 characters.")
        if await self.session.scalar(select(PerformanceRecommendation.id).where(PerformanceRecommendation.code == code, PerformanceRecommendation.id != (rec_id or uuid.uuid4()))):
            err.add("code", "Another option already uses this code.")
        err.raise_if_any()
        if rec_id is None:
            r = PerformanceRecommendation(code=code, label=label, active=data.active)
            self.session.add(r)
        else:
            r = await self.session.get(PerformanceRecommendation, rec_id)
            if r is None:
                raise NotFoundError()
            ensure_version(r, data.version)
            if r.code != code:
                raise ValidationFailedError(details=[{"field": "code", "message": "The code of an option cannot be changed."}])
            r.label, r.active = label, data.active
        await self.session.flush()
        self.audit.record(module=MODULE, action="performance_recommendation.saved", summary=f"Recommendation option {code} saved", entity_type="performance_recommendation", entity_id=r.id, entity_label=label)
        await self.session.commit()
        return RecommendationSetupOut(id=str(r.id), code=r.code, label=r.label, active=r.active, version=r.version)

    # ---- Configuration and cycles ----------------------------------------------------------------------------------

    async def configuration(self) -> PerformanceConfigOut:
        scales = (await self.session.scalars(select(RatingScale).where(RatingScale.active.is_(True)).order_by(func.lower(RatingScale.name)))).all()
        comps = (await self.session.scalars(select(Competency).where(Competency.active.is_(True)).order_by(func.lower(Competency.name)))).all()
        return PerformanceConfigOut(rating_scales=[_scale_out(s) for s in scales], competencies=[CompetencyOut(id=str(c.id), name=c.name, description=c.description) for c in comps])

    async def _cycle_out(self, c: AppraisalCycle, comps: dict | None = None) -> AppraisalCycleOut:
        comps = comps if comps is not None else await self._competencies()
        scale = await self.session.get(RatingScale, c.rating_scale_id) if c.rating_scale_id else None
        participants = await self.session.scalar(select(func.count()).select_from(PerformanceReview).where(PerformanceReview.cycle_id == c.id)) or 0
        completed = await self.session.scalar(select(func.count()).select_from(PerformanceReview).where(PerformanceReview.cycle_id == c.id, PerformanceReview.status == "completed")) or 0
        events = (await self.session.scalars(select(AppraisalCycleEvent).where(AppraisalCycleEvent.cycle_id == c.id).order_by(AppraisalCycleEvent.created_at, AppraisalCycleEvent.id))).all()
        return AppraisalCycleOut(
            id=str(c.id), name=c.name, period_from=c.period_from.isoformat(), period_to=c.period_to.isoformat(), status=c.status, goal_setting_due=c.goal_setting_due.isoformat(),
            self_assessment_due=c.self_assessment_due.isoformat(), manager_review_due=c.manager_review_due.isoformat(), rating_scale=_scale_out(scale),
            competencies=[CompetencyOut(id=str(comps[i].id), name=comps[i].name, description=comps[i].description) for i in c.competency_ids if i in comps],
            recommendation_options=[RecommendationOptionOut(**o) for o in c.recommendation_options], participants=participants, completed_reviews=completed,
            history=_events(events), version=c.version,
        )

    async def cycles(self) -> list[AppraisalCycleOut]:
        comps = await self._competencies()
        rows = (await self.session.scalars(select(AppraisalCycle).order_by(AppraisalCycle.period_from.desc(), AppraisalCycle.name))).all()
        return [await self._cycle_out(c, comps) for c in rows]

    async def create_cycle(self, data: CycleIn) -> AppraisalCycleOut:
        err = FieldErrors()
        name = data.name.strip()
        if not 2 <= len(name) <= 120:
            err.add("name", "Enter a name of 2-120 characters.")
        elif await self.session.scalar(select(AppraisalCycle.id).where(func.lower(AppraisalCycle.name) == name.lower())):
            err.add("name", "Another cycle already uses this name.")
        start = _date(err, "periodFrom", data.period_from, "period start")
        end = _date(err, "periodTo", data.period_to, "period end")
        g = _date(err, "goalSettingDue", data.goal_setting_due, "goal-setting deadline")
        s = _date(err, "selfAssessmentDue", data.self_assessment_due, "self-assessment deadline")
        m = _date(err, "managerReviewDue", data.manager_review_due, "manager-review deadline")
        if start and end and end < start:
            err.add("periodTo", "The period must end on or after its start.")
        if g and s and s < g:
            err.add("selfAssessmentDue", "The self-assessment deadline must be on or after the goal-setting deadline.")
        if s and m and m < s:
            err.add("managerReviewDue", "The manager-review deadline must be on or after the self-assessment deadline.")
        scale = None
        if data.rating_scale_id:
            scale = await self.session.get(RatingScale, body_id(data.rating_scale_id)) if body_id(data.rating_scale_id) else None
            if scale is None or not scale.active:
                err.add("ratingScaleId", "Choose an active rating scale, or none for written feedback only.")
        comps = await self._competencies()
        ids = [body_id(i) for i in data.competency_ids]
        if any(i not in comps or not comps[i].active for i in ids):
            err.add("competencyIds", "Choose active competencies.")
        elif len(set(ids)) != len(ids):
            err.add("competencyIds", "Each competency can be chosen once.")
        err.raise_if_any()
        options = [{"code": r.code, "label": r.label} for r in (await self.session.scalars(select(PerformanceRecommendation).where(PerformanceRecommendation.active.is_(True)).order_by(PerformanceRecommendation.code))).all()]
        c = AppraisalCycle(name=name, period_from=start, period_to=end, status="draft", goal_setting_due=g, self_assessment_due=s, manager_review_due=m,
                           rating_scale_id=scale.id if scale else None, competency_ids=ids, recommendation_options=options)
        self.session.add(c)
        await self.session.flush()
        self.session.add(AppraisalCycleEvent(cycle_id=c.id, action="updated", comment="Cycle created"))
        self.audit.record(module=MODULE, action="appraisal_cycle.created", summary=f"Appraisal cycle {name} created", entity_type="appraisal_cycle", entity_id=c.id, entity_label=name)
        await self.session.commit()
        return await self._cycle_out(c, comps)

    async def _participants(self, c: AppraisalCycle) -> list[Employee]:
        ended = select(EmployeeStatus.code).where(EmployeeStatus.employment_ended.is_(True))
        return list((await self.session.scalars(select(Employee).where(Employee.joining_date <= c.period_to, Employee.status_code.not_in(ended)))).all())

    async def advance_cycle(self, cycle_id: uuid.UUID, data: VersionIn) -> AppraisalCycleOut:
        c = await self._cycle(cycle_id, for_update=True)
        ensure_version(c, data.version)
        nxt = NEXT_PHASE.get(c.status)
        if nxt is None:
            raise InvalidTransitionError("A closed cycle cannot move to another phase.")
        if c.status == "draft":
            other = await self.session.scalar(select(AppraisalCycle).where(AppraisalCycle.id != c.id, AppraisalCycle.status.in_(RUNNING)))
            if other is not None:
                raise ConflictError(f"The cycle {other.name} is still running. Close it before starting another.")
            existing = set((await self.session.scalars(select(PerformanceReview.employee_id).where(PerformanceReview.cycle_id == c.id))).all())
            for e in await self._participants(c):
                if e.id not in existing:
                    self.session.add(PerformanceReview(cycle_id=c.id, employee_id=e.id, reviewer_employee_id=e.reporting_manager_id, status="not_started"))
        reviews = list((await self.session.scalars(select(PerformanceReview).where(PerformanceReview.cycle_id == c.id, PerformanceReview.status != "completed"))).all())
        if nxt in ("self_assessment", "manager_review"):
            managers = dict((await self.session.execute(select(Employee.id, Employee.reporting_manager_id).where(Employee.id.in_([r.employee_id for r in reviews])))).all()) if reviews else {}
            for r in reviews:
                r.status = nxt
                if nxt == "manager_review" and r.manager is None:
                    r.reviewer_employee_id = managers.get(r.employee_id)
        c.status = nxt
        self.session.add(AppraisalCycleEvent(cycle_id=c.id, action="updated", comment=f"Moved to {PHASE_LABEL[nxt]}"))
        await self.session.flush()
        self.audit.record(module=MODULE, action="appraisal_cycle.advanced", summary=f"Appraisal cycle {c.name} moved to {PHASE_LABEL[nxt]}", entity_type="appraisal_cycle", entity_id=c.id, entity_label=c.name)
        await self.session.commit()
        await self.session.refresh(c)
        return await self._cycle_out(c)

    # ---- Goals ----------------------------------------------------------------------------------------------------------

    async def _goal_out(self, g: Goal, employees: dict, cycles: dict, depts: dict) -> GoalOut:
        updates = (await self.session.scalars(select(GoalProgressUpdate).where(GoalProgressUpdate.goal_id == g.id).order_by(GoalProgressUpdate.created_at, GoalProgressUpdate.id))).all()
        kpi = None
        if g.kpi:
            current = next((u.value for u in reversed(updates) if u.value is not None), None)
            kpi = GoalKpiOut(metric=g.kpi["metric"], unit=g.kpi["unit"], baseline=g.kpi.get("baseline"), target=g.kpi["target"], current=_num(current), direction=g.kpi["direction"])
        c = cycles[g.cycle_id]
        return GoalOut(id=str(g.id), employee=employee_ref(employees[g.employee_id], depts), cycle=CycleRefOut(id=str(c.id), name=c.name), title=g.title, description=g.description,
                       kpi=kpi, weight=_num(g.weight), due_date=g.due_date.isoformat(), status=g.status, progress=g.progress,
                       updates=[ProgressUpdateOut(id=str(u.id), at=u.created_at, by=u.created_by_name, progress=u.progress, status=u.status, value=_num(u.value), note=u.note) for u in updates],
                       version=g.version)

    async def _goal_context(self, goals: list[Goal]) -> tuple[dict, dict, dict]:
        employees = {e.id: e for e in (await self.session.scalars(select(Employee).where(Employee.id.in_({g.employee_id for g in goals})))).all()} if goals else {}
        cycles = {c.id: c for c in (await self.session.scalars(select(AppraisalCycle).where(AppraisalCycle.id.in_({g.cycle_id for g in goals})))).all()} if goals else {}
        return employees, cycles, await departments(self.session)

    async def goals(self, *, q, cycle_id, status, department_id, sort, page: int, page_size: int) -> Page:
        stmt = select(Goal).join(Employee, Employee.id == Goal.employee_id).where(self._scope())
        if q:
            stmt = stmt.where(or_(text_match(q), func.lower(Goal.title).contains(q.lower(), autoescape=True)))
        if cycle_id:
            stmt = stmt.where(Goal.cycle_id == body_id(cycle_id)) if body_id(cycle_id) else stmt.where(false())
        if status:
            stmt = stmt.where(Goal.status == status)
        if department_id:
            stmt = stmt.where(Employee.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        name, _, direction = (sort or "dueDate:asc").partition(":")
        cols = {"dueDate": Goal.due_date, "title": func.lower(Goal.title), "employee": func.lower(Employee.full_name), "progress": Goal.progress, "status": Goal.status}
        if name not in cols or direction not in ("", "asc", "desc"):
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": f"Use {', '.join(cols)} with :asc or :desc."}])
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = cols[name]
        rows = list((await self.session.scalars(stmt.order_by(col.desc() if direction == "desc" else col.asc(), Goal.id).limit(page_size).offset((page - 1) * page_size))).all())
        ctx = await self._goal_context(rows)
        items = [await self._goal_out(g, *ctx) for g in rows]
        return Page.build(PageResult(rows, page, page_size, total), items)

    async def _goal_in_scope(self, goal_id: uuid.UUID, *, for_update: bool = False) -> Goal:
        stmt = select(Goal).join(Employee, Employee.id == Goal.employee_id).where(Goal.id == goal_id, self._scope())
        g = await self.session.scalar(stmt.with_for_update(of=Goal) if for_update else stmt)
        if g is None:
            raise NotFoundError()
        return g

    async def goal(self, goal_id: uuid.UUID) -> GoalOut:
        g = await self._goal_in_scope(goal_id)
        return await self._goal_out(g, *await self._goal_context([g]))

    async def create_goal(self, data: GoalIn) -> GoalOut:
        err = FieldErrors()
        employee = await self._employee_in_scope(body_id(data.employee_id))
        if employee is None:
            err.add("employeeId", "Choose an employee within your organizational scope.")
        cycle = await self.session.get(AppraisalCycle, body_id(data.cycle_id)) if body_id(data.cycle_id) else None
        if cycle is None:
            err.add("cycleId", "Choose an existing appraisal cycle.")
        elif cycle.status == "closed":
            err.add("cycleId", "Goals cannot be added to a closed cycle.")
        title = data.title.strip()
        if not 3 <= len(title) <= 200:
            err.add("title", "Enter a title of 3-200 characters.")
        due = _date(err, "dueDate", data.due_date, "due date")
        if due and cycle and not cycle.period_from <= due <= cycle.period_to:
            err.add("dueDate", f"The due date must be within the cycle ({cycle.period_from.isoformat()} to {cycle.period_to.isoformat()}).")
        kpi = None
        if data.kpi is not None:
            if not data.kpi.metric.strip():
                err.add("kpi.metric", "Enter the metric.")
            kpi = {"metric": data.kpi.metric.strip(), "unit": data.kpi.unit.strip(), "baseline": data.kpi.baseline, "target": data.kpi.target, "direction": data.kpi.direction}
        if data.weight is not None:
            if not 0 < data.weight <= 100:
                err.add("weight", "Enter a weight above 0 and up to 100%.")
            elif employee is not None and cycle is not None:
                used = await self.session.scalar(select(func.coalesce(func.sum(Goal.weight), 0)).where(Goal.employee_id == employee.id, Goal.cycle_id == cycle.id, Goal.status != "cancelled")) or 0
                if Decimal(str(used)) + Decimal(str(data.weight)) > 100:
                    err.add("weight", f"The employee's goals in this cycle would weigh {Decimal(str(used)) + Decimal(str(data.weight)):g}%; the total cannot exceed 100%.")
        err.raise_if_any()
        g = Goal(employee_id=employee.id, cycle_id=cycle.id, title=title, description=data.description.strip(), kpi=kpi, weight=data.weight, due_date=due, status="not_started", progress=0)
        self.session.add(g)
        await self.session.flush()
        self.audit.record(module=MODULE, action="goal.created", summary=f"Goal '{title}' for {employee.employee_code} in {cycle.name}", entity_type="goal", entity_id=g.id, entity_label=title)
        await self.session.commit()
        return await self._goal_out(g, *await self._goal_context([g]))

    async def record_progress(self, goal_id: uuid.UUID, data: ProgressIn) -> GoalOut:
        g = await self._goal_in_scope(goal_id, for_update=True)
        ensure_version(g, data.version)
        cycle = await self.session.get(AppraisalCycle, g.cycle_id)
        err = FieldErrors()
        if cycle.status == "closed":
            raise InvalidTransitionError("The cycle is closed: its goals can no longer change.")
        if not 0 <= data.progress <= 100:
            err.add("progress", "Enter progress from 0 to 100.")
        if data.status == "completed" and data.progress != 100:
            err.add("progress", "A completed goal must be at 100%.")
        if data.value is not None and not g.kpi:
            err.add("value", "This goal has no KPI to record a value for.")
        err.raise_if_any()
        g.progress, g.status = data.progress, data.status
        self.session.add(GoalProgressUpdate(goal_id=g.id, progress=data.progress, status=data.status, value=data.value, note=data.note.strip()))
        await self.session.flush()
        self.audit.record(module=MODULE, action="goal.progress_recorded", summary=f"Goal '{g.title}': {data.progress}% ({data.status})", entity_type="goal", entity_id=g.id, entity_label=g.title)
        await self.session.commit()
        await self.session.refresh(g)
        return await self._goal_out(g, *await self._goal_context([g]))

    # ---- Reviews ---------------------------------------------------------------------------------------------------------

    def _visible_reviews(self):
        """In organizational scope, or assigned to the caller."""
        me = self._me()
        return or_(self._scope(), PerformanceReview.reviewer_employee_id == me) if me else self._scope()

    async def _review_parts(self, reviews: list[PerformanceReview]) -> dict:
        ids = {r.employee_id for r in reviews} | {r.reviewer_employee_id for r in reviews if r.reviewer_employee_id}
        employees = {e.id: e for e in (await self.session.scalars(select(Employee).where(Employee.id.in_(ids))))} if ids else {}
        cycles = {c.id: c for c in (await self.session.scalars(select(AppraisalCycle).where(AppraisalCycle.id.in_({r.cycle_id for r in reviews}))))} if reviews else {}
        designations = {d.id: d.name for d in (await self.session.scalars(select(Designation))).all()}
        scales = {s.id: s for s in (await self.session.scalars(select(RatingScale))).all()}
        return {"employees": employees, "cycles": cycles, "designations": designations, "depts": await departments(self.session), "scales": scales}

    def _review_head(self, r: PerformanceReview, parts: dict) -> tuple[ReviewEmployeeOut, ReviewCycleOut, ReviewerOut]:
        e = parts["employees"][r.employee_id]
        c = parts["cycles"][r.cycle_id]
        ref = employee_ref(e, parts["depts"])
        reviewer = parts["employees"].get(r.reviewer_employee_id) if r.reviewer_employee_id else None
        return (ReviewEmployeeOut(**ref.model_dump(), designation=parts["designations"].get(e.designation_id, "")),
                ReviewCycleOut(id=str(c.id), name=c.name, status=c.status, manager_review_due=c.manager_review_due.isoformat()),
                ReviewerOut(id=str(reviewer.id), name=reviewer.full_name) if reviewer else NOT_ASSIGNED)

    async def reviews(self, *, q, cycle_id, status, department_id, assigned_to_me: bool, sort, page: int, page_size: int) -> Page:
        stmt = select(PerformanceReview).join(Employee, Employee.id == PerformanceReview.employee_id).where(self._visible_reviews())
        if assigned_to_me:
            me = self._me()
            stmt = stmt.where(PerformanceReview.reviewer_employee_id == me) if me else stmt.where(false())
        if q:
            stmt = stmt.where(text_match(q))
        if cycle_id:
            stmt = stmt.where(PerformanceReview.cycle_id == body_id(cycle_id)) if body_id(cycle_id) else stmt.where(false())
        if status:
            stmt = stmt.where(PerformanceReview.status == status)
        if department_id:
            stmt = stmt.where(Employee.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        name, _, direction = (sort or "employee:asc").partition(":")
        cols = {"employee": func.lower(Employee.full_name), "employeeCode": Employee.employee_code, "status": PerformanceReview.status}
        if name not in cols or direction not in ("", "asc", "desc"):
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": f"Use {', '.join(cols)} with :asc or :desc."}])
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        col = cols[name]
        rows = list((await self.session.scalars(stmt.order_by(col.desc() if direction == "desc" else col.asc(), PerformanceReview.id).limit(page_size).offset((page - 1) * page_size))).all())
        parts = await self._review_parts(rows)
        items = []
        for r in rows:
            employee, cycle, reviewer = self._review_head(r, parts)
            label = None
            if r.manager_submitted_at and r.manager and r.manager.get("overallRating") is not None:
                c = parts["cycles"][r.cycle_id]
                scale = parts["scales"].get(c.rating_scale_id)
                label = next((lv["label"] for lv in (scale.levels if scale else []) if lv["value"] == r.manager["overallRating"]), None)
            items.append(ReviewListItemOut(id=str(r.id), employee=employee, cycle=cycle, reviewer=reviewer, status=r.status, recommendation=r.recommendation, version=r.version,
                                           self_submitted_at=None, manager_submitted_at=r.manager_submitted_at, manager_rating_label=label))
        return Page.build(PageResult(rows, page, page_size, total), items)

    async def _review_visible(self, review_id: uuid.UUID, *, for_update: bool = False) -> PerformanceReview:
        stmt = select(PerformanceReview).join(Employee, Employee.id == PerformanceReview.employee_id).where(PerformanceReview.id == review_id, self._visible_reviews())
        r = await self.session.scalar(stmt.with_for_update(of=PerformanceReview) if for_update else stmt)
        if r is None:
            raise NotFoundError()
        return r

    def _can_assess(self, r: PerformanceReview, c: AppraisalCycle) -> bool:
        me = self._me()
        return bool(me and r.reviewer_employee_id == me and self.caller.has(P.REVIEWS_ASSESS) and c.status == "manager_review" and r.status != "completed")

    async def review(self, review_id: uuid.UUID) -> ReviewOut:
        r = await self._review_visible(review_id)
        return await self._review_out(r)

    async def _review_out(self, r: PerformanceReview) -> ReviewOut:
        parts = await self._review_parts([r])
        employee, cycle_out, reviewer = self._review_head(r, parts)
        c = parts["cycles"][r.cycle_id]
        comps = await self._competencies()
        goals = (await self.session.scalars(select(Goal).where(Goal.cycle_id == c.id, Goal.employee_id == r.employee_id).order_by(Goal.due_date, Goal.id))).all()
        events = (await self.session.scalars(select(PerformanceReviewEvent).where(PerformanceReviewEvent.review_id == r.id).order_by(PerformanceReviewEvent.created_at, PerformanceReviewEvent.id))).all()
        manager = None
        if r.manager is not None:
            m = r.manager
            manager = AssessmentOut(overall_rating=m.get("overallRating"), competency_ratings=[CompetencyRatingModel(**x) for x in m.get("competencyRatings", [])], strengths=m.get("strengths", ""),
                                    improvements=m.get("improvements", ""), comments=m.get("comments", ""), submitted_at=r.manager_submitted_at)
        return ReviewOut(
            id=str(r.id), employee=employee, cycle=cycle_out, reviewer=reviewer, status=r.status, rating_scale=_scale_out(parts["scales"].get(c.rating_scale_id)),
            competencies=[CompetencyOut(id=str(comps[i].id), name=comps[i].name, description=comps[i].description) for i in c.competency_ids if i in comps],
            recommendation_options=[RecommendationOptionOut(**o) for o in c.recommendation_options], self=None, manager=manager, recommendation=r.recommendation,
            goals=[ReviewGoalOut(id=str(g.id), title=g.title, progress=g.progress, status=g.status) for g in goals], history=_events(events),
            can_assess=self._can_assess(r, c), version=r.version,
        )

    async def save_manager_assessment(self, review_id: uuid.UUID, data: ManagerAssessmentIn) -> ReviewOut:
        r = await self._review_visible(review_id, for_update=True)
        ensure_version(r, data.version)
        c = await self.session.get(AppraisalCycle, r.cycle_id)
        me = self._me()
        if not (me and r.reviewer_employee_id == me and self.caller.has(P.REVIEWS_ASSESS)):
            raise ForbiddenError("Only the assigned reviewer may assess this review.")
        if r.status == "completed":
            raise InvalidTransitionError("The review is completed; its assessment can no longer change.")
        if c.status != "manager_review":
            raise InvalidTransitionError("Manager assessments are possible while the cycle is in manager review.")
        scale = await self.session.get(RatingScale, c.rating_scale_id) if c.rating_scale_id else None
        values = {lv["value"] for lv in scale.levels} if scale else set()
        a = data.assessment
        err = FieldErrors()
        if a.overall_rating is not None and (scale is None or a.overall_rating not in values):
            err.add("assessment.overallRating", "Choose a level of the cycle's rating scale." if scale else "This cycle has no rating scale: leave the rating empty.")
        allowed = {str(i) for i in c.competency_ids}
        given = {}
        for i, x in enumerate(a.competency_ratings):
            if x.competency_id not in allowed:
                err.add(f"assessment.competencyRatings.{i}.competencyId", "This competency is not part of the cycle.")
            elif x.competency_id in given:
                err.add(f"assessment.competencyRatings.{i}.competencyId", "Each competency can be rated once.")
            if x.rating is not None and (scale is None or x.rating not in values):
                err.add(f"assessment.competencyRatings.{i}.rating", "Choose a level of the cycle's rating scale." if scale else "This cycle has no rating scale: leave the rating empty.")
            given[x.competency_id] = x
        codes = {o["code"] for o in c.recommendation_options}
        if data.recommendation is not None and data.recommendation not in codes:
            err.add("recommendation", "Choose one of the cycle's recommendation options.")
        if data.submit:
            if scale is not None and a.overall_rating is None:
                err.add("assessment.overallRating", "Choose the overall rating.")
            if scale is not None and any(cid not in given or given[cid].rating is None for cid in allowed):
                err.add("assessment.competencyRatings", "Rate every competency of the cycle.")
            if not a.strengths.strip():
                err.add("assessment.strengths", "Describe the strengths.")
            if not a.improvements.strip():
                err.add("assessment.improvements", "Describe the areas for improvement.")
            if data.recommendation is None:
                err.add("recommendation", "Choose a recommendation." if codes else "This cycle has no recommendation options; HR must add them before reviews can be submitted.")
        err.raise_if_any()
        ordered = [given[str(i)] for i in c.competency_ids if str(i) in given]
        r.manager = {"overallRating": a.overall_rating, "competencyRatings": [x.model_dump(by_alias=True) for x in ordered], "strengths": a.strengths.strip(),
                     "improvements": a.improvements.strip(), "comments": a.comments.strip()}
        r.recommendation = data.recommendation
        if data.submit:
            r.status, r.manager_submitted_at = "completed", _utcnow()
        self.session.add(PerformanceReviewEvent(review_id=r.id, action="submitted" if data.submit else "updated", comment="Manager assessment submitted" if data.submit else "Manager assessment draft saved"))
        await self.session.flush()
        e = await self.session.get(Employee, r.employee_id)
        self.audit.record(module=MODULE, action="review.assessment_submitted" if data.submit else "review.assessment_saved",
                          summary=f"Manager assessment of {e.employee_code} in {c.name} {'submitted' if data.submit else 'saved as draft'}", entity_type="performance_review", entity_id=r.id, entity_label=e.full_name)
        await self.session.commit()
        await self.session.refresh(r)
        return await self._review_out(r)

    # ---- Development plans -----------------------------------------------------------------------------------------------

    async def _plan_out(self, p: DevelopmentPlan, employees: dict, depts: dict) -> DevelopmentPlanOut:
        actions = (await self.session.scalars(select(DevelopmentAction).where(DevelopmentAction.plan_id == p.id).order_by(DevelopmentAction.position))).all()
        return DevelopmentPlanOut(id=str(p.id), employee=employee_ref(employees[p.employee_id], depts), title=p.title, focus=p.focus, owner=p.owner_name, status=p.status,
                                  actions=[DevelopmentActionOut(id=str(a.id), title=a.title, type=a.type, due_date=a.due_date.isoformat(), status=a.status, completed_at=a.completed_at) for a in actions],
                                  created_at=p.created_at, version=p.version)

    async def plans(self, *, q, status, department_id, page: int, page_size: int) -> Page:
        stmt = select(DevelopmentPlan).join(Employee, Employee.id == DevelopmentPlan.employee_id).where(self._scope())
        if q:
            stmt = stmt.where(or_(text_match(q), func.lower(DevelopmentPlan.title).contains(q.lower(), autoescape=True)))
        if status:
            stmt = stmt.where(DevelopmentPlan.status == status)
        if department_id:
            stmt = stmt.where(Employee.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = list((await self.session.scalars(stmt.order_by(DevelopmentPlan.created_at.desc(), DevelopmentPlan.id).limit(page_size).offset((page - 1) * page_size))).all())
        employees = {e.id: e for e in (await self.session.scalars(select(Employee).where(Employee.id.in_({p.employee_id for p in rows}))))} if rows else {}
        depts = await departments(self.session)
        return Page.build(PageResult(rows, page, page_size, total), [await self._plan_out(p, employees, depts) for p in rows])

    async def create_plan(self, data: PlanIn) -> DevelopmentPlanOut:
        err = FieldErrors()
        employee = await self._employee_in_scope(body_id(data.employee_id))
        if employee is None:
            err.add("employeeId", "Choose an employee within your organizational scope.")
        title = data.title.strip()
        if not 3 <= len(title) <= 200:
            err.add("title", "Enter a title of 3-200 characters.")
        if not data.actions:
            err.add("actions", "Add at least one action.")
        dues = []
        for i, a in enumerate(data.actions):
            if not 3 <= len(a.title.strip()) <= 200:
                err.add(f"actions.{i}.title", "Enter a title of 3-200 characters.")
            dues.append(_date(err, f"actions.{i}.dueDate", a.due_date, "due date"))
        err.raise_if_any()
        p = DevelopmentPlan(employee_id=employee.id, title=title, focus=data.focus.strip(), owner_name=self.caller.principal.name, status="active")
        self.session.add(p)
        await self.session.flush()
        for i, (a, due) in enumerate(zip(data.actions, dues)):
            self.session.add(DevelopmentAction(plan_id=p.id, position=i, title=a.title.strip(), type=a.type, due_date=due, status="planned"))
        await self.session.flush()
        self.audit.record(module=MODULE, action="development_plan.created", summary=f"Development plan '{title}' for {employee.employee_code} ({len(data.actions)} actions)",
                          entity_type="development_plan", entity_id=p.id, entity_label=title)
        await self.session.commit()
        return await self._plan_out(p, {employee.id: employee}, await departments(self.session))

    async def update_action(self, plan_id: uuid.UUID, action_id: uuid.UUID, data: ActionUpdateIn) -> DevelopmentPlanOut:
        p = await self.session.scalar(select(DevelopmentPlan).join(Employee, Employee.id == DevelopmentPlan.employee_id).where(DevelopmentPlan.id == plan_id, self._scope()).with_for_update(of=DevelopmentPlan))
        if p is None:
            raise NotFoundError()
        ensure_version(p, data.version)
        a = await self.session.scalar(select(DevelopmentAction).where(DevelopmentAction.id == action_id, DevelopmentAction.plan_id == p.id))
        if a is None:
            raise NotFoundError()
        before = a.status
        a.status = data.status
        a.completed_at = (a.completed_at or _utcnow()) if data.status == "done" else None
        await self.session.flush()
        statuses = (await self.session.scalars(select(DevelopmentAction.status).where(DevelopmentAction.plan_id == p.id))).all()
        p.status = "completed" if all(s == "done" for s in statuses) else "active"
        p.updated_at = _utcnow()  # the plan's version changes with every action update (optimistic locking on the plan)
        await self.session.flush()
        self.audit.record(module=MODULE, action="development_action.updated", summary=f"Action '{a.title}': {before} -> {data.status}", entity_type="development_plan", entity_id=p.id, entity_label=p.title)
        await self.session.commit()
        await self.session.refresh(p)
        e = await self.session.get(Employee, p.employee_id)
        return await self._plan_out(p, {e.id: e}, await departments(self.session))

    # ---- Summary --------------------------------------------------------------------------------------------------------------

    async def summary(self) -> PerformanceSummaryOut:
        active = await self.session.scalar(select(AppraisalCycle).where(AppraisalCycle.status.in_(RUNNING)).limit(1))
        counts = {"not_started": 0, "self_assessment": 0, "manager_review": 0, "completed": 0}
        goals = GoalCountsOut(total=0, at_risk=0, off_track=0, completed=0)
        at_risk: list[GoalAtRiskOut] = []
        awaiting = 0
        me = self._me()
        if active is not None:
            rows = (await self.session.execute(select(PerformanceReview.status, func.count()).join(Employee, Employee.id == PerformanceReview.employee_id)
                                               .where(PerformanceReview.cycle_id == active.id, self._visible_reviews()).group_by(PerformanceReview.status))).all()
            counts.update(dict(rows))
            if me and self.caller.has(P.REVIEWS_ASSESS) and active.status == "manager_review":
                awaiting = await self.session.scalar(select(func.count()).select_from(PerformanceReview).where(PerformanceReview.cycle_id == active.id, PerformanceReview.reviewer_employee_id == me,
                                                                                                             PerformanceReview.status != "completed")) or 0
            base = select(Goal.status, func.count()).join(Employee, Employee.id == Goal.employee_id).where(Goal.cycle_id == active.id, self._scope(), Goal.status != "cancelled").group_by(Goal.status)
            by = dict((await self.session.execute(base)).all())
            goals = GoalCountsOut(total=sum(by.values()), at_risk=by.get("at_risk", 0), off_track=by.get("off_track", 0), completed=by.get("completed", 0))
            risky = list((await self.session.scalars(select(Goal).join(Employee, Employee.id == Goal.employee_id).where(Goal.cycle_id == active.id, self._scope(), Goal.status.in_(("at_risk", "off_track")))
                                                     .order_by(Goal.due_date, Goal.id).limit(10))).all())
            employees = {e.id: e for e in (await self.session.scalars(select(Employee).where(Employee.id.in_({g.employee_id for g in risky}))))} if risky else {}
            depts = await departments(self.session)
            at_risk = [GoalAtRiskOut(id=str(g.id), employee=employee_ref(employees[g.employee_id], depts), title=g.title, status=g.status, progress=g.progress, due_date=g.due_date.isoformat()) for g in risky]
        overdue = await self.session.scalar(select(func.count()).select_from(DevelopmentAction).join(DevelopmentPlan, DevelopmentPlan.id == DevelopmentAction.plan_id)
                                            .join(Employee, Employee.id == DevelopmentPlan.employee_id).where(DevelopmentAction.status != "done", DevelopmentAction.due_date < company_today(), self._scope())) or 0
        return PerformanceSummaryOut(active_cycle=await self._cycle_out(active) if active else None, reviews_by_status=ReviewsByStatusOut(**counts), awaiting_my_assessment=awaiting,
                                     goals=goals, goals_at_risk=at_risk, overdue_development_actions=overdue, as_of=_utcnow())
