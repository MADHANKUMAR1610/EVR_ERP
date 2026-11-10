"""Shared payroll helpers: component definitions, period output, amount masking, month bounds."""

from __future__ import annotations

import calendar
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import P
from app.models.department_model import Department
from app.models.payroll_model import PayrollPeriod, PayrollPeriodEvent, SalaryComponent
from app.schemas.attendance_schema import WorkflowEventOut
from app.schemas.payroll_schema import PayrollPeriodOut
from app.services.employee_support import Caller
from app.services.payroll.engine import ComponentDef, dec

MODULE = "Payroll"


def component_def(c: SalaryComponent) -> ComponentDef:
    return ComponentDef(id=str(c.id), code=c.code, name=c.name, type=c.type, formula=c.formula, rate=dec(c.rate), base=tuple(c.base or ()),
                        base_cap=dec(c.base_cap), max_amount=dec(c.max_amount), slabs=tuple(c.slabs or ()), prorate=c.prorate)


def can_amounts(caller: Caller) -> bool:
    return caller.has(P.PAYROLL_VIEW_AMOUNTS)


def amt(value, allowed: bool) -> float | None:
    """A money value for output: a number, or null without hr.payroll:view-amounts."""
    if not allowed or value is None:
        return None
    return float(Decimal(str(value)))


def month_bounds(month: str) -> tuple[date, date]:
    y, m = int(month[:4]), int(month[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def month_label(month: str) -> str:
    y, m = int(month[:4]), int(month[5:7])
    return f"{calendar.month_name[m]} {y}"


async def period_out(session: AsyncSession, p: PayrollPeriod) -> PayrollPeriodOut:
    events = (await session.scalars(select(PayrollPeriodEvent).where(PayrollPeriodEvent.period_id == p.id).order_by(PayrollPeriodEvent.created_at, PayrollPeriodEvent.id))).all()
    return PayrollPeriodOut(
        id=str(p.id), month=p.month, label=month_label(p.month), **{"from": p.from_date.isoformat()}, to=p.to_date.isoformat(), status=p.status, currency=p.currency,
        employees_included=p.employees_included, calculated_at=p.calculated_at,
        history=[WorkflowEventOut(id=str(e.id), action=e.action, at=e.created_at, by=e.created_by_name, comment=e.comment) for e in events], version=p.version,
    )


async def departments(session: AsyncSession) -> dict[uuid.UUID, str]:
    return {d.id: d.name for d in (await session.scalars(select(Department))).all()}


FINALIZED = ("approved", "payslips_published")
