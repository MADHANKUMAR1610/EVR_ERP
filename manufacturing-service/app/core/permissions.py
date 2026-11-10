"""Permission checks (same rules as the frontend, HRMS and Identity)."""

from collections.abc import Iterable


class M:
    DASHBOARD_VIEW = "dashboard:view"
    MANUFACTURING_VIEW = "manufacturing:view"


def has_permission(granted: Iterable[str], required: str) -> bool:
    granted = set(granted)
    if "*" in granted or required in granted:
        return True
    return f"{required.split(':', 1)[0]}:*" in granted


def has_any(granted: Iterable[str], required: Iterable[str]) -> bool:
    granted = set(granted)
    return any(has_permission(granted, r) for r in required)
