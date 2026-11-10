"""Notifications through a transactional outbox (AUTH_INTEGRATION.md: POST /internal/notifications).

`queue()` writes the notification in the same transaction as the change it reports. The worker job
`notifications.deliver` posts pending ones to Platform with retries (exponential backoff), but only
once PLATFORM_NOTIFICATIONS_URL and PLATFORM_SERVICE_TOKEN are set (L28); until then they stay
queued and GET /hr/setup/notification-outbox shows the backlog.

The contract addresses `userIds` and `employeeIds`. Role recipients (an escalation to an HR role)
have no field in the contract, so they are sent as `roleCodes`, pending Platform's agreement.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.database.base import utcnow
from app.models.leave_model import NotificationOutbox
from app.schemas.leave_schema import NotificationOut, NotificationOutboxOut

logger = logging.getLogger("hrms.notifications")
BATCH = 50


def queue(session: AsyncSession, *, category: str, title: str, message: str, link: str | None = None, employee_ids: list[uuid.UUID] | None = None,
          user_ids: list[str] | None = None, role_codes: list[str] | None = None) -> None:
    employee_ids = [e for e in (employee_ids or []) if e]
    user_ids = [u for u in (user_ids or []) if u]
    role_codes = [r for r in (role_codes or []) if r]
    if not (employee_ids or user_ids or role_codes):
        return
    session.add(NotificationOutbox(category=category, title=title[:200], message=message[:1000], link=link, employee_ids=sorted(set(employee_ids)), user_ids=sorted(set(user_ids)),
                                   role_codes=sorted(set(role_codes)), status="pending", attempts=0, next_attempt_at=utcnow()))


def delivery_configured() -> bool:
    s = get_settings()
    from app.core.service_tokens import service_tokens

    return bool(s.platform_notifications_url and (s.platform_service_token or service_tokens().configured))


async def deliver_pending(session: AsyncSession, client: httpx.AsyncClient | None = None) -> dict:
    """Worker task. Returns counts; does nothing while delivery is not configured."""
    if not delivery_configured():
        return {"delivered": 0, "failed": 0, "skipped": "delivery not configured"}
    s = get_settings()
    rows = (await session.scalars(
        select(NotificationOutbox).where(NotificationOutbox.status == "pending", NotificationOutbox.next_attempt_at <= utcnow())
        .order_by(NotificationOutbox.created_at).limit(BATCH).with_for_update(skip_locked=True)
    )).all()
    delivered = failed = 0
    own = client is None
    client = client or httpx.AsyncClient(timeout=10)
    from app.core.service_tokens import bearer_for

    try:
        token = await bearer_for(s.platform_service_token)
    except Exception as exc:  # noqa: BLE001 - Identity unreachable: every row stays pending and is retried
        if own:
            await client.aclose()
        return {"delivered": 0, "failed": 0, "skipped": f"no service token: {type(exc).__name__}"}
    try:
        for n in rows:
            body = {"category": n.category, "title": n.title, "message": n.message, "link": n.link}
            if n.user_ids:
                body["userIds"] = list(n.user_ids)
            if n.employee_ids:
                body["employeeIds"] = [str(e) for e in n.employee_ids]
            if n.role_codes:
                body["roleCodes"] = list(n.role_codes)
            n.attempts += 1
            try:
                response = await client.post(s.platform_notifications_url, json=body, headers={"Authorization": f"Bearer {token}"})
                if response.status_code >= 300:
                    raise RuntimeError(f"HTTP {response.status_code}")
                n.status, n.delivered_at, n.last_error = "delivered", utcnow(), None
                delivered += 1
            except Exception as exc:  # noqa: BLE001 - kept on the row and retried
                n.last_error = f"{type(exc).__name__}: {exc}"[:500]
                if n.attempts >= s.notification_max_attempts:
                    n.status = "failed"
                    failed += 1
                else:
                    n.next_attempt_at = utcnow() + timedelta(minutes=2 ** min(n.attempts, 10))
                logger.warning("notification %s not delivered (attempt %s): %s", n.id, n.attempts, n.last_error)
    finally:
        if own:
            await client.aclose()
    await session.commit()
    return {"delivered": delivered, "failed": failed}


async def outbox_status(session: AsyncSession) -> NotificationOutboxOut:
    counts = dict((await session.execute(select(NotificationOutbox.status, func.count()).group_by(NotificationOutbox.status))).all())
    recent = (await session.scalars(select(NotificationOutbox).order_by(NotificationOutbox.created_at.desc()).limit(50))).all()
    return NotificationOutboxOut(
        delivery_configured=delivery_configured(), pending=counts.get("pending", 0), failed=counts.get("failed", 0), delivered=counts.get("delivered", 0),
        recent=[NotificationOut(id=str(n.id), category=n.category, title=n.title, status=n.status, attempts=n.attempts, next_attempt_at=n.next_attempt_at, delivered_at=n.delivered_at,
                                last_error=n.last_error, created_at=n.created_at) for n in recent],
    )
