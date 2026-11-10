from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log_model import AuditLog
from app.repositories.base_repository import PageResult, paginate


class AuditLogRepository:
    """Insert and query audit entries. There is deliberately no update or delete method."""

    def __init__(self, session: AsyncSession):
        self.session = session

    def add(self, entry: AuditLog) -> None:
        self.session.add(entry)

    async def search(
        self,
        *,
        page: int,
        page_size: int,
        actor_user_id: str | None = None,
        module: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        result: str | None = None,
        request_id: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        q: str | None = None,
    ) -> PageResult[AuditLog]:
        stmt: Select = select(AuditLog)
        if actor_user_id:
            stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
        if module:
            stmt = stmt.where(AuditLog.module == module)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if entity_type:
            stmt = stmt.where(AuditLog.entity_type == entity_type)
        if entity_id:
            stmt = stmt.where(AuditLog.entity_id == entity_id)
        if result:
            stmt = stmt.where(AuditLog.result == result)
        if request_id:
            stmt = stmt.where(AuditLog.request_id == request_id)
        if date_from:
            stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min, timezone.utc))
        if date_to:
            stmt = stmt.where(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), time.min, timezone.utc))
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(AuditLog.summary.ilike(like), AuditLog.entity_label.ilike(like), AuditLog.actor_name.ilike(like)))
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id)
        return await paginate(self.session, stmt, page, page_size)

    async def count(self) -> int:
        return int(await self.session.scalar(select(func.count()).select_from(AuditLog)) or 0)
