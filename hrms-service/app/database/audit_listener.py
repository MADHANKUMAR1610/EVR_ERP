"""Fills the audit columns on every flush, from the authenticated principal in the request context.

Because this runs for every session, no service can forget the audit fields, and values supplied in
a request body are always overwritten. Work outside a request (worker, scripts) must set the system
principal explicitly with `acting_as(SYSTEM_PRINCIPAL)`; otherwise the flush is refused.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.core.context import Principal, current_principal, principal_var
from app.database.base import AuditMixin, utcnow


class MissingActorError(RuntimeError):
    """A write was attempted without an authenticated or system actor."""


@contextmanager
def acting_as(principal: Principal) -> Iterator[None]:
    token = principal_var.set(principal)
    try:
        yield
    finally:
        principal_var.reset(token)


@event.listens_for(Session, "before_flush")
def _fill_audit_columns(session: Session, _flush_context, _instances) -> None:
    changed = [o for o in session.new if isinstance(o, AuditMixin)] + [o for o in session.dirty if isinstance(o, AuditMixin) and session.is_modified(o)]
    if not changed:
        return
    principal = current_principal()
    if principal is None:
        raise MissingActorError("Refusing to write without an actor: set the request principal or use acting_as(SYSTEM_PRINCIPAL).")
    actor, name = principal.actor_uuid, principal.name[:200]
    now = utcnow()
    for obj in session.new:
        if isinstance(obj, AuditMixin):
            obj.created_at, obj.created_by, obj.created_by_name = now, actor, name
            obj.updated_at, obj.updated_by, obj.updated_by_name = now, actor, name
    for obj in session.dirty:
        if isinstance(obj, AuditMixin) and session.is_modified(obj):
            obj.updated_at, obj.updated_by, obj.updated_by_name = now, actor, name
