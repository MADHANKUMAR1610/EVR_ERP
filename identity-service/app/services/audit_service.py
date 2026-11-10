"""Records important business actions in the append-only audit log.

`record()` adds the entry to the caller's session, so it is committed (or rolled back) together with
the business change. `record_denial()` uses its own short transaction, because the request that was
denied will not commit anything.
"""

import logging
from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.context import Principal, current_principal, current_request_id
from app.models.audit_log_model import AuditLog
from app.repositories.audit_log_repository import AuditLogRepository

logger = logging.getLogger("identity.audit")

# Values of these fields are never stored, only the fact that they changed.
MASKED_FIELDS = {"password", "token", "secret", "bankaccount", "bank_account", "accountnumber", "account_number", "ifsc", "pan", "aadhaar", "uan", "salary", "amount", "gross", "net"}
MASK = "••••"


def _is_masked(field: str) -> bool:
    key = field.replace(".", "_").replace("-", "_").lower()
    return any(m in key for m in MASKED_FIELDS)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:500]


def diff(before: dict[str, Any], after: dict[str, Any], labels: dict[str, str] | None = None) -> list[dict[str, str | None]]:
    """[{field, before, after}] for fields whose value changed, with sensitive values masked."""
    labels = labels or {}
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        masked = _is_masked(key)
        changes.append({"field": labels.get(key, key), "before": MASK if masked and old is not None else _text(old), "after": MASK if masked and new is not None else _text(new)})
    return changes


class AuditService:
    def __init__(self, session: AsyncSession):
        self.repo = AuditLogRepository(session)

    @staticmethod
    def _entry(
        principal: Principal,
        *,
        module: str,
        action: str,
        summary: str,
        result: str = "success",
        entity_type: str | None = None,
        entity_id: Any = None,
        entity_label: str | None = None,
        changes: Iterable[dict[str, Any]] | None = None,
    ) -> AuditLog:
        return AuditLog(
            created_by=principal.actor_uuid,
            actor_user_id=principal.user_id,
            actor_name=principal.name,
            module=module,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            entity_label=entity_label,
            result=result,
            request_id=current_request_id(),
            summary=summary,
            changes=list(changes) if changes else None,
        )

    def record(self, *, module: str, action: str, summary: str, **kwargs: Any) -> None:
        principal = current_principal()
        if principal is None:
            raise RuntimeError("Audit entries need an actor.")
        self.repo.add(self._entry(principal, module=module, action=action, summary=summary, **kwargs))


async def record_denial(factory: async_sessionmaker[AsyncSession], principal: Principal, required: str, path: str) -> None:
    """Writes a 'denied' entry in its own transaction. Failures here never hide the 403."""
    try:
        async with factory() as session:
            session.add(
                AuditService._entry(principal, module="Access", action="access_denied", result="denied", summary=f"Request refused: missing permission {required} for {path}")
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - auditing a denial must not change the response
        logger.exception("could not record access denial")
