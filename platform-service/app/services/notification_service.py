"""Notifications (contracts B2, G8): the caller's feed, history, read marks and preferences, plus delivery for other services.

- Every endpoint returns only the caller's own notifications (404 for anyone else's).
- Links must be app-relative paths ("/..."); anything else is dropped.
- Channels: in-app is always available. Email and SMS are shown as unavailable: no delivery integration is
  built yet, so the backend forces them off (G8) and never claims external delivery.
- A user who switched a category's in-app channel off does not receive it, unless the category is mandatory
  (NOTIFICATION_MANDATORY_CATEGORIES, empty until HR/IT decide).
- Delivery from services (POST /internal/notifications) resolves employeeIds and roleCodes to Identity users with a
  service token.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.context import Principal
from app.core.errors import NotFoundError, ServiceUnavailableError, ValidationFailedError
from app.core.service_tokens import ServiceTokenProvider
from app.models.platform_model import CATEGORIES, Notification, NotificationPreference
from app.repositories.base_repository import PageResult
from app.schemas.common import PageMeta
from app.schemas.platform_schema import (
    CategoryPreferenceOut,
    ChannelStateOut,
    DeliveryOut,
    InternalNotificationIn,
    NotificationFeedOut,
    NotificationOut,
    NotificationPageOut,
    NotificationPreferencesIn,
    NotificationPreferencesOut,
)
from app.services import peers
from app.utils.validation import ensure_version

LABELS = {
    "approval": ("Approvals", "Requests waiting for your decision and decisions on your requests."),
    "attendance": ("Attendance", "Attendance corrections and exceptions."),
    "leave": ("Leave", "Leave applications, decisions and balances."),
    "overtime": ("Overtime", "Overtime requests and decisions."),
    "payroll": ("Payroll", "Payroll periods and payslips."),
    "employee": ("Employees", "Employee record changes."),
    "documents": ("Documents", "Document uploads, verification and expiry."),
    "performance": ("Performance", "Appraisal cycles, goals and reviews."),
    "system": ("System", "Account and system messages."),
}
NOT_BUILT = "Delivery by {} is not set up yet: no delivery integration has been built."


def _out(n: Notification) -> NotificationOut:
    return NotificationOut(id=str(n.id), title=n.title, message=n.message, category=n.category, created_at=n.created_at, read=n.read_at is not None, link=n.link)


def _safe_link(link: str | None) -> str | None:
    return link if link and link.startswith("/") and not link.startswith("//") else None


class NotificationService:
    def __init__(self, session: AsyncSession, settings: Settings, caller: Principal | None = None):
        self.session = session
        self.s = settings
        self.caller = caller

    def _mine(self):
        return Notification.user_id == self.caller.user_id

    async def _unread(self) -> int:
        return await self.session.scalar(select(func.count()).select_from(Notification).where(self._mine(), Notification.read_at.is_(None))) or 0

    async def feed(self, limit: int) -> NotificationFeedOut:
        rows = (await self.session.scalars(select(Notification).where(self._mine()).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit))).all()
        return NotificationFeedOut(items=[_out(n) for n in rows], unread_count=await self._unread())

    async def history(self, *, category: str | None, status: str | None, page: int, page_size: int) -> NotificationPageOut:
        stmt = select(Notification).where(self._mine())
        if category:
            stmt = stmt.where(Notification.category == category)
        if status == "read":
            stmt = stmt.where(Notification.read_at.is_not(None))
        elif status == "unread":
            stmt = stmt.where(Notification.read_at.is_(None))
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self.session.scalars(stmt.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(page_size).offset((page - 1) * page_size))).all()
        r = PageResult([], page, page_size, total)
        return NotificationPageOut(items=[_out(n) for n in rows], meta=PageMeta(page=page, page_size=page_size, total_items=total, total_pages=r.total_pages), unread_count=await self._unread())

    async def mark_read(self, notification_id: uuid.UUID) -> None:
        n = await self.session.scalar(select(Notification).where(Notification.id == notification_id, self._mine()))
        if n is None:
            raise NotFoundError()
        if n.read_at is None:
            await self.session.execute(update(Notification).where(Notification.id == n.id).values(read_at=datetime.now(UTC)).execution_options(synchronize_session=False))
            await self.session.commit()

    async def mark_all_read(self) -> None:
        await self.session.execute(update(Notification).where(self._mine(), Notification.read_at.is_(None)).values(read_at=datetime.now(UTC)).execution_options(synchronize_session=False))
        await self.session.commit()

    # ---- Preferences ------------------------------------------------------------------------------------------

    def _channels(self) -> list[ChannelStateOut]:
        return [ChannelStateOut(channel="in_app", available=True), ChannelStateOut(channel="email", available=False, reason=NOT_BUILT.format("email")),
                ChannelStateOut(channel="sms", available=False, reason=NOT_BUILT.format("SMS"))]

    def _prefs_out(self, p: NotificationPreference | None) -> NotificationPreferencesOut:
        stored = p.categories if p else {}
        mandatory = set(self.s.notification_mandatory_categories)
        cats = []
        for c in CATEGORIES:
            label, description = LABELS[c]
            in_app = True if c in mandatory else bool(stored.get(c, {}).get("in_app", True))
            cats.append(CategoryPreferenceOut(category=c, label=label, description=description, channels={"in_app": in_app, "email": False, "sms": False}, mandatory=c in mandatory))
        return NotificationPreferencesOut(channels=self._channels(), categories=cats, version=p.version if p else 0)

    async def preferences(self) -> NotificationPreferencesOut:
        return self._prefs_out(await self.session.scalar(select(NotificationPreference).where(NotificationPreference.user_id == self.caller.user_id)))

    async def save_preferences(self, data: NotificationPreferencesIn) -> NotificationPreferencesOut:
        p = await self.session.scalar(select(NotificationPreference).where(NotificationPreference.user_id == self.caller.user_id).with_for_update())
        if p is None and data.version != 0:
            from app.core.errors import StaleVersionError

            raise StaleVersionError()
        if p is not None:
            ensure_version(p, data.version)
        mandatory = set(self.s.notification_mandatory_categories)
        stored = dict(p.categories) if p else {}
        for choice in data.categories:
            # Unavailable channels are forced off; mandatory categories keep in-app delivery.
            stored[choice.category] = {"in_app": True if choice.category in mandatory else bool(choice.channels.get("in_app", True)), "email": False, "sms": False}
        if p is None:
            p = NotificationPreference(user_id=self.caller.user_id, categories=stored)
            self.session.add(p)
        else:
            p.categories = stored
        await self.session.commit()
        await self.session.refresh(p)
        return self._prefs_out(p)

    # ---- Delivery for other services -----------------------------------------------------------------------------

    async def deliver(self, data: InternalNotificationIn, source: str) -> DeliveryOut:
        if not data.title.strip():
            raise ValidationFailedError(details=[{"field": "title", "message": "Enter a title."}])
        recipients = {u for u in data.user_ids if u}
        if data.employee_ids or data.role_codes:
            provider = ServiceTokenProvider(self.s.identity_base_url, self.s.identity_client_id, self.s.identity_client_secret)
            if not provider.configured:
                raise ServiceUnavailableError("Recipients by employee or role need the Identity service (IDENTITY_BASE_URL and client credentials).")
            token = await provider.token()
            params = {"employeeIds": ",".join(data.employee_ids) or None, "roleIds": ",".join(data.role_codes) or None, "activeOnly": "true", "limit": 200}
            users = await peers.get_json(self.s.identity_base_url, "/internal/users", token, params, name="Identity") or []
            recipients |= {u["id"] for u in users}
        prefs = {p.user_id: p.categories for p in (await self.session.scalars(select(NotificationPreference).where(NotificationPreference.user_id.in_(recipients)))).all()} if recipients else {}
        mandatory = data.category in set(self.s.notification_mandatory_categories)
        delivered = skipped = 0
        for user_id in sorted(recipients):
            if not mandatory and prefs.get(user_id, {}).get(data.category, {}).get("in_app", True) is False:
                skipped += 1
                continue
            self.session.add(Notification(user_id=user_id, category=data.category, title=data.title.strip(), message=(data.message or "").strip() or None, link=_safe_link(data.link), source=source))
            delivered += 1
        await self.session.commit()
        return DeliveryOut(delivered=delivered, skipped=skipped)
