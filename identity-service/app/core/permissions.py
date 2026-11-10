"""Permission checks (same rules as the frontend and HRMS) and the permission catalogue (contract G3).

Codes are "<module>:<action>". "<module>:*" grants every action of a module and "*" grants everything.
The catalogue is built from `permission_codes.CODES`: one row per module, the eight matrix actions as
columns, and every other code of the module as an `extra` entry.
"""

from collections.abc import Iterable

from app.core.permission_codes import CODES

ROLES_MANAGE = "admin:roles.manage"
ACTIONS = ("view", "create", "edit", "delete", "approve", "reject", "export", "configure")
ACTION_ALIASES = {"manage": "configure"}

GROUP_LABELS = {"hr": "HR", "admin": "Administration", "erp": "ERP modules"}


class Perm:
    USERS_VIEW = "admin:users.view"
    USERS_MANAGE = "admin:users.manage"
    ROLES_VIEW = "admin:roles.view"
    ROLES_MANAGE = ROLES_MANAGE


def has_permission(granted: Iterable[str], required: str) -> bool:
    granted = set(granted)
    if "*" in granted or required in granted:
        return True
    module = required.split(":", 1)[0]
    return f"{module}:*" in granted


def has_any(granted: Iterable[str], required: Iterable[str]) -> bool:
    granted = set(granted)
    return any(has_permission(granted, r) for r in required)


def known(code: str) -> bool:
    """A code is valid when it is in the catalogue, or a wildcard ("*", "<module>:*")."""
    return code == "*" or code in CODES or (code.endswith(":*") and any(c.split(":", 1)[0] == code[:-2] for c in CODES))


def _humanize(text: str) -> str:
    return text.replace("hr.", "").replace("-", " ").replace(".", " ").replace("_", " ").strip().capitalize()


def _row_of(code: str) -> tuple[str, str, str]:
    """(row id, group, action) for a code."""
    module, action = code.split(":", 1)
    if module == "admin":
        area, _, act = action.rpartition(".")
        return (f"admin.{area}" if area else "admin"), "admin", act
    return module, ("hr" if module.startswith("hr.") else "erp"), action


def catalogue() -> list[dict]:
    rows: dict[str, dict] = {}
    for code in CODES:
        row_id, group, action = _row_of(code)
        row = rows.setdefault(row_id, {"id": row_id, "group": GROUP_LABELS[group], "label": _humanize(row_id.split(".", 1)[-1] if group == "admin" and "." in row_id else row_id) if row_id != "admin" else "Administration",
                                       "actions": {}, "extra": []})
        column = ACTION_ALIASES.get(action, action)
        if column in ACTIONS and column not in row["actions"]:
            row["actions"][column] = code
            if column == "approve":
                row["actions"].setdefault("reject", code)  # approve and reject share one code
        else:
            row["extra"].append({"code": code, "label": _humanize(action)})
    order = {"HR": 0, "Administration": 1, "ERP modules": 2}
    return sorted(rows.values(), key=lambda r: (order[r["group"]], r["label"]))
