"""One service's slice of the audit screen (contract G10), from its own append-only audit_log.

The same module is used by Platform, Identity and HRMS: each answers the newest `limit` matching events, the
total count and the facets; Platform merges the slices and pages them. Values were masked when written.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailedError
from app.models.audit_log_model import AuditLog

MAX_LIMIT = 1000


def parse_day(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationFailedError(details=[{"field": field, "message": "Enter the date as YYYY-MM-DD."}]) from None


def _filtered(*, start: date | None, end: date | None, actor_id: str | None, module: str | None, action: str | None, result: str | None, q: str | None, tz: str = "UTC") -> Select:
    stmt = select(AuditLog)
    zone = ZoneInfo(tz)
    if start:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(start, time.min, zone))
    if end:
        stmt = stmt.where(AuditLog.created_at < datetime.combine(end + timedelta(days=1), time.min, zone))
    if actor_id:
        stmt = stmt.where(AuditLog.actor_user_id == actor_id)
    if module:
        stmt = stmt.where(AuditLog.module == module)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if result:
        stmt = stmt.where(AuditLog.result == result)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(AuditLog.summary).like(like), func.lower(AuditLog.actor_name).like(like), func.lower(AuditLog.entity_label).like(like)))
    return stmt


def event_json(a: AuditLog) -> dict:
    return {"id": str(a.id), "at": a.created_at.isoformat(), "actor": {"id": a.actor_user_id, "name": a.actor_name}, "module": a.module, "action": a.action,
            "record": {"type": a.entity_type, "id": a.entity_id or "", "label": a.entity_label or ""} if a.entity_type else None,
            "result": a.result, "summary": a.summary, "changes": a.changes}


async def audit_slice(session: AsyncSession, *, start: str | None, end: str | None, actor_id: str | None, module: str | None, action: str | None, result: str | None, q: str | None,
                      limit: int) -> dict:
    s, e = parse_day(start, "from"), parse_day(end, "to")
    if s and e and e < s:
        raise ValidationFailedError(details=[{"field": "to", "message": "The range must end on or after its start."}])
    stmt = _filtered(start=s, end=e, actor_id=actor_id, module=module, action=action, result=result, q=q)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await session.scalars(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(min(max(limit, 1), MAX_LIMIT)))).all()
    modules = sorted((await session.scalars(select(AuditLog.module).distinct())).all())
    actions = sorted((await session.scalars(select(AuditLog.action).distinct())).all())
    actors = [{"id": i, "name": n} for i, n in (await session.execute(select(AuditLog.actor_user_id, func.max(AuditLog.actor_name)).group_by(AuditLog.actor_user_id).order_by(func.max(AuditLog.actor_name)))).all()]
    return {"items": [event_json(a) for a in rows], "total": total, "facets": {"modules": modules, "actions": actions, "actors": actors}}
