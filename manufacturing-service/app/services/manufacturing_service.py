"""Manufacturing reads (API_CONTRACTS.md: Production work orders, Dashboard). Read-only by owner decision.

Definitions used (each PENDING production planning; docs/DECISIONS.md):
- open work order: status not `completed`; due soon: open, customer due date within DUE_WINDOW_DAYS;
- open sales order: status not `draft` and not `dispatched`;
- units in production: work orders `in_progress`; tests pending: open work orders currently at the stage
  TESTING_STAGE_CODE (0 while it is not set); dispatches this week: sales orders dispatched this ISO week;
- monthly output: completed work orders per month (last 6 months), MVA = sum of kVA / 1000.
Schedule status and variance are read as stored (their calculation is an open question).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import BadRequestError, NotFoundError
from app.models.manufacturing_model import SalesOrder, WorkOrder, WorkOrderEvent, WorkOrderMaterial, WorkOrderStage, WorkOrderStageRecord
from app.repositories.base_repository import PageResult
from app.schemas.common import Page
from app.schemas.manufacturing_schema import (
    BlockerOut,
    DashboardKpisOut,
    DashboardSummaryOut,
    MaterialLineOut,
    MonthlyOutputOut,
    NextActionOut,
    PersonOut,
    ProductOut,
    RecentOrderOut,
    SalesOrderRefOut,
    ScheduleOut,
    StageCountOut,
    StageRecordOut,
    UnitOut,
    WorkOrderEventOut,
    WorkOrderListItemOut,
    WorkOrderOut,
    WorkOrderStageOut,
    WorkOrderSummaryOut,
)

SCHEDULE_RANK = case((WorkOrder.schedule_status == "delayed", 0), (WorkOrder.schedule_status == "at_risk", 1), else_=2)


def _f(v) -> float:
    return float(Decimal(str(v)))


class ManufacturingService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.s = settings

    def _today(self) -> date:
        return datetime.now(UTC).date()

    async def _stages(self) -> list[WorkOrderStage]:
        return list((await self.session.scalars(select(WorkOrderStage).where(WorkOrderStage.active.is_(True)).order_by(WorkOrderStage.sequence))).all())

    async def stages(self) -> list[WorkOrderStageOut]:
        return [WorkOrderStageOut(code=s.code, label=s.label, sequence=s.sequence) for s in await self._stages()]

    def _item(self, w: WorkOrder, so: SalesOrder, stage: WorkOrderStage, stage_count: int) -> dict:
        return dict(
            id=str(w.id), work_order_no=w.work_order_no, sales_order=SalesOrderRefOut(id=str(so.id), order_no=so.order_no, customer_name=so.customer_name),
            unit=UnitOut(index=w.unit_index, of=w.unit_of), product=ProductOut(rating_kva=_f(w.rating_kva), voltage_ratio=w.voltage_ratio, vector_group=w.vector_group, cooling=w.cooling),
            status=w.status, stage=WorkOrderStageOut(code=stage.code, label=stage.label, sequence=stage.sequence), stage_count=stage_count, priority=w.priority, work_centre=w.work_centre,
            planned_start=w.planned_start.isoformat(), planned_finish=w.planned_finish.isoformat(), customer_due_date=w.customer_due_date.isoformat(),
            schedule=ScheduleOut(status=w.schedule_status, variance_days=w.variance_days),
            blocker=BlockerOut(type=w.blocker_type, description=w.blocker_description or "", since=w.blocker_since.isoformat()) if w.blocker_type and w.blocker_since else None,
            next_action=NextActionOut(label=w.next_action_label, owner=PersonOut(id=w.next_action_owner_id, name=w.next_action_owner_name, role=w.next_action_owner_role),
                                      due_date=w.next_action_due.isoformat() if w.next_action_due else None),
        )

    async def list(self, *, q, stage, view, work_centre, sort, page: int, page_size: int) -> Page:
        stmt = select(WorkOrder, SalesOrder, WorkOrderStage).join(SalesOrder, SalesOrder.id == WorkOrder.sales_order_id).join(WorkOrderStage, WorkOrderStage.id == WorkOrder.stage_id)
        if q:
            like = f"%{q.lower()}%"
            stmt = stmt.where(or_(func.lower(WorkOrder.work_order_no).like(like), func.lower(SalesOrder.order_no).like(like), func.lower(SalesOrder.customer_name).like(like)))
        if stage:
            stmt = stmt.where(WorkOrderStage.code == stage)
        if work_centre:
            stmt = stmt.where(WorkOrder.work_centre == work_centre)
        if view == "delayed":
            stmt = stmt.where(WorkOrder.schedule_status == "delayed", WorkOrder.status != "completed")
        elif view == "blocked":
            stmt = stmt.where(WorkOrder.blocker_type.is_not(None), WorkOrder.status != "completed")
        elif view == "due_soon":
            stmt = stmt.where(WorkOrder.status != "completed", WorkOrder.customer_due_date <= self._today() + timedelta(days=self.s.due_window_days))
        name, _, direction = (sort or "plannedFinish:asc").partition(":")
        cols = {"workOrderNo": [WorkOrder.work_order_no], "plannedFinish": [WorkOrder.planned_finish], "customerDueDate": [WorkOrder.customer_due_date],
                "stage": [WorkOrderStage.sequence], "schedule": [SCHEDULE_RANK, WorkOrder.variance_days.desc()]}
        if name not in cols or direction not in ("", "asc", "desc"):
            raise BadRequestError(f"Sorting by '{sort}' is not supported.", details=[{"field": "sort", "message": f"Use {', '.join(cols)} with :asc or :desc."}])
        order = cols[name] if name == "schedule" else [c.desc() if direction == "desc" else c.asc() for c in cols[name]]
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self.session.execute(stmt.order_by(*order, WorkOrder.work_order_no).limit(page_size).offset((page - 1) * page_size))).all()
        count = len(await self._stages())
        items = [WorkOrderListItemOut(**self._item(w, so, st, count)) for w, so, st in rows]
        return Page.build(PageResult(items, page, page_size, total), items)

    async def get(self, work_order_id: str) -> WorkOrderOut:
        try:
            wid = uuid.UUID(work_order_id)
            cond = WorkOrder.id == wid
        except ValueError:
            cond = WorkOrder.work_order_no == work_order_id
        row = (await self.session.execute(select(WorkOrder, SalesOrder, WorkOrderStage).join(SalesOrder, SalesOrder.id == WorkOrder.sales_order_id)
                                          .join(WorkOrderStage, WorkOrderStage.id == WorkOrder.stage_id).where(cond))).first()
        if row is None:
            raise NotFoundError()
        w, so, st = row
        stages = await self._stages()
        records = {r.stage_id: r for r in (await self.session.scalars(select(WorkOrderStageRecord).where(WorkOrderStageRecord.work_order_id == w.id))).all()}
        stage_out = [StageRecordOut(code=s.code, label=s.label, state=records[s.id].state if s.id in records else ("current" if s.id == w.stage_id else "pending"),
                                    started_at=records[s.id].started_at.isoformat() if s.id in records and records[s.id].started_at else None,
                                    completed_at=records[s.id].completed_at.isoformat() if s.id in records and records[s.id].completed_at else None) for s in stages]
        materials = (await self.session.scalars(select(WorkOrderMaterial).where(WorkOrderMaterial.work_order_id == w.id).order_by(WorkOrderMaterial.item))).all()
        events = (await self.session.scalars(select(WorkOrderEvent).where(WorkOrderEvent.work_order_id == w.id).order_by(WorkOrderEvent.created_at.desc()))).all()
        return WorkOrderOut(**self._item(w, so, st, len(stages)), stages=stage_out, design_ref=w.design_ref,
                            materials=[MaterialLineOut(item=m.item, required=m.required, status=m.status, expected_date=m.expected_date.isoformat() if m.expected_date else None) for m in materials],
                            history=[WorkOrderEventOut(id=str(e.id), at=e.created_at, by=e.created_by_name, summary=e.summary) for e in events])

    async def summary(self) -> WorkOrderSummaryOut:
        open_ = WorkOrder.status != "completed"
        stages = await self._stages()
        by_stage = dict((await self.session.execute(select(WorkOrder.stage_id, func.count()).where(open_).group_by(WorkOrder.stage_id))).all())

        async def count(*conds) -> int:
            return await self.session.scalar(select(func.count()).select_from(WorkOrder).where(open_, *conds)) or 0

        return WorkOrderSummaryOut(
            by_stage=[StageCountOut(code=s.code, label=s.label, count=by_stage.get(s.id, 0)) for s in stages], open=await count(), delayed=await count(WorkOrder.schedule_status == "delayed"),
            at_risk=await count(WorkOrder.schedule_status == "at_risk"), blocked=await count(WorkOrder.blocker_type.is_not(None)),
            blocked_by_material=await count(WorkOrder.blocker_type == "material"), due_soon=await count(WorkOrder.customer_due_date <= self._today() + timedelta(days=self.s.due_window_days)),
            due_window_days=self.s.due_window_days, as_of=datetime.now(UTC),
        )

    async def dashboard(self) -> DashboardSummaryOut:
        today = self._today()
        week_start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time(), UTC)
        open_orders = await self.session.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.status.not_in(("draft", "dispatched")))) or 0
        in_production = await self.session.scalar(select(func.count()).select_from(WorkOrder).where(WorkOrder.status == "in_progress")) or 0
        tests = 0
        if self.s.testing_stage_code:
            tests = await self.session.scalar(select(func.count()).select_from(WorkOrder).join(WorkOrderStage, WorkOrderStage.id == WorkOrder.stage_id)
                                              .where(WorkOrder.status != "completed", WorkOrderStage.code == self.s.testing_stage_code)) or 0
        dispatches = await self.session.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.status == "dispatched", SalesOrder.dispatched_at >= week_start)) or 0
        first = today.replace(day=1)
        months = []
        for _ in range(6):
            months.append(first)
            first = (first - timedelta(days=1)).replace(day=1)
        months.reverse()
        start = datetime.combine(months[0], datetime.min.time(), UTC)
        month_of = func.to_char(func.timezone("UTC", WorkOrder.completed_at), literal_column("'YYYY-MM'"))
        done = (await self.session.execute(select(month_of, func.count(), func.coalesce(func.sum(WorkOrder.rating_kva), 0))
                                           .where(WorkOrder.status == "completed", WorkOrder.completed_at >= start).group_by(month_of))).all()
        by_month = {m: (n, kva) for m, n, kva in done}
        output = [MonthlyOutputOut(month=m.strftime("%Y-%m"), units_completed=by_month.get(m.strftime("%Y-%m"), (0, 0))[0],
                                   mva_completed=round(_f(by_month.get(m.strftime("%Y-%m"), (0, 0))[1]) / 1000, 3)) for m in months]
        recent = (await self.session.scalars(select(SalesOrder).order_by(SalesOrder.updated_at.desc(), SalesOrder.order_no.desc()).limit(10))).all()
        return DashboardSummaryOut(kpis=DashboardKpisOut(open_orders=open_orders, units_in_production=in_production, tests_pending=tests, dispatches_this_week=dispatches), monthly_output=output,
                                   recent_orders=[RecentOrderOut(id=str(o.id), order_no=o.order_no, customer_name=o.customer_name, rating_kva=_f(o.rating_kva), quantity=o.quantity, status=o.status,
                                                                 due_date=o.due_date.isoformat()) for o in recent])
