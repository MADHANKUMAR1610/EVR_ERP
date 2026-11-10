"""Request-scoped context: the request ID and the authenticated principal.

Set by middleware and the authentication dependency; read by logging, the audit listener and the
audit service. Values never come from the request body.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID

# Fixed actor for work done by the background worker and maintenance scripts.
SYSTEM_ACTOR_ID = UUID("00000000-0000-0000-0000-000000000001")
SYSTEM_ACTOR_NAME = "system"


@dataclass(frozen=True)
class Principal:
    """The caller, as asserted by a verified token."""

    user_id: str
    name: str
    permissions: frozenset[str]
    roles: frozenset[str] = field(default_factory=frozenset)
    employee_id: str | None = None
    session_id: str | None = None

    @property
    def actor_uuid(self) -> UUID:
        """The user ID as a UUID for audit columns. Non-UUID IDs are mapped deterministically."""
        try:
            return UUID(self.user_id)
        except ValueError:
            from uuid import NAMESPACE_URL, uuid5

            return uuid5(NAMESPACE_URL, f"evr-user:{self.user_id}")


SYSTEM_PRINCIPAL = Principal(user_id=str(SYSTEM_ACTOR_ID), name=SYSTEM_ACTOR_NAME, permissions=frozenset({"*"}))

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
principal_var: ContextVar[Principal | None] = ContextVar("principal", default=None)


def current_request_id() -> str | None:
    return request_id_var.get()


def current_principal() -> Principal | None:
    return principal_var.get()
