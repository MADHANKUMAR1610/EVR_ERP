"""Permission checks (same rules as the frontend, HRMS and Identity)."""

from collections.abc import Iterable


class A:
    VIEW = "admin:view"
    SETTINGS_VIEW = "admin:settings.view"
    SETTINGS_MANAGE = "admin:settings.manage"
    AUDIT_VIEW = "admin:audit.view"
    INTEGRATIONS_VIEW = "admin:integrations.view"
    INTEGRATIONS_MANAGE = "admin:integrations.manage"


def has_permission(granted: Iterable[str], required: str) -> bool:
    granted = set(granted)
    if "*" in granted or required in granted:
        return True
    return f"{required.split(':', 1)[0]}:*" in granted


def has_any(granted: Iterable[str], required: Iterable[str]) -> bool:
    granted = set(granted)
    return any(has_permission(granted, r) for r in required)
