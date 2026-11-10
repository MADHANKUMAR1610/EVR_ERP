"""Compares a service's response/request schemas with the frontend TypeScript interfaces (same method as hrms tools/verify_contracts.py)."""
import importlib, os, re, sys
from pathlib import Path
from pydantic.alias_generators import to_camel

FE = Path(os.environ["FRONTEND_SRC"]) / "features"


def ts_fields(file, name):
    src = (FE / file).read_text()
    m = re.search(r'export interface ' + name + r'\b(?:\s+extends\s+([\w<>, ]+?))?\s*\{(.*?)\n\}', src, re.S)
    body = re.sub(r'/\*.*?\*/|//[^\n]*', '', m.group(2), flags=re.S)
    fields, depth = {}, 0
    for line in body.split('\n'):
        if depth == 0:
            mm = re.match(r'\s*(\w+)(\?)?:', line)
            if mm:
                fields[mm.group(1)] = bool(mm.group(2))
        depth += line.count('{') - line.count('}')
    parent = (m.group(1) or "").split("<", 1)[0].strip()
    if parent == "Paginated":
        fields.update({"items": False, "meta": False})
    elif parent:
        fields.update(ts_fields(file, parent))
    return fields


# Optional frontend fields a service deliberately never sends (documented).
ALLOWED_MISSING = {"AuthSession": {"accessToken"}}  # bearer-token transport only; sessions use the cookie


def check(pairs, allowed_extra):
    ok = True
    for file, name, model, kind in pairs:
        ts = ts_fields(file, name)
        py = {(f.serialization_alias or f.alias or to_camel(n)): (not f.is_required()) for n, f in model.model_fields.items()}
        if kind == "out":
            missing, extra = set(ts) - set(py) - ALLOWED_MISSING.get(name, set()), set(py) - set(ts) - allowed_extra.get(name, set())
        else:
            missing, extra = set(ts) - set(py), {k for k in set(py) - set(ts) if not py[k]}
        status = "OK" if not missing and not extra else "MISMATCH"
        ok &= status == "OK"
        print(f"{status:8} {name:28}" + (f" missing={sorted(missing)}" if missing else "") + (f" extra={sorted(extra)}" if extra else ""))
    return ok


svc = sys.argv[1]
if svc == "identity":
    from app.schemas import identity_schema as I
    AU, AD = "auth/types.ts", "admin/api/admin.service.ts"
    pairs = [(AU, "AuthUser", I.AuthUserOut, "out"), (AU, "AuthSession", I.AuthSessionOut, "out"), (AU, "LoginRequest", I.LoginIn, "in"),
             (AD, "UserAccount", I.UserAccountOut, "out"), (AD, "UserInput", I.UserIn, "in"), (AD, "NewUserInput", I.NewUserIn, "in"), (AD, "PasswordInput", I.PasswordResetIn, "in"),
             (AD, "UserActivity", I.UserActivityOut, "out"), (AD, "PermissionModule", I.PermissionModuleOut, "out"), (AD, "Role", I.RoleOut, "out"), (AD, "RoleInput", I.RoleIn, "in")]
    extra = {"AuthUser": {"employeeId", "mustChangePassword"}}  # documented additions
elif svc == "platform":
    from app.schemas import platform_schema as S
    AD, NT = "admin/api/admin.service.ts", "notifications/api/notifications.service.ts"
    pairs = [(AD, "CompanySettings", S.CompanySettingsOut, "out"), (AD, "AuditEvent", S.AuditEventOut, "out"), (AD, "AuditPage", S.AuditPageOut, "out"),
             (AD, "IntegrationSetting", S.IntegrationSettingOut, "out"), (AD, "Integration", S.IntegrationOut, "out"), (AD, "IntegrationSettingsInput", S.IntegrationIn, "in"),
             (AD, "AdminOverview", S.AdminOverviewOut, "out"), (NT, "AppNotification", S.NotificationOut, "out"), (NT, "NotificationFeed", S.NotificationFeedOut, "out"),
             (NT, "NotificationPreferences", S.NotificationPreferencesOut, "out")]
    extra = {}
else:
    from app.schemas import manufacturing_schema as M
    WO, DB = "production/api/workOrders.service.ts", "dashboard/api/dashboard.service.ts"
    pairs = [(WO, "WorkOrderStage", M.WorkOrderStageOut, "out"), (WO, "Blocker", M.BlockerOut, "out"), (WO, "Person", M.PersonOut, "out"), (WO, "WorkOrderListItem", M.WorkOrderListItemOut, "out"),
             (WO, "MaterialLine", M.MaterialLineOut, "out"), (WO, "WorkOrderEvent", M.WorkOrderEventOut, "out"), (WO, "WorkOrder", M.WorkOrderOut, "out"), (WO, "WorkOrderSummary", M.WorkOrderSummaryOut, "out"),
             (DB, "DashboardKpis", M.DashboardKpisOut, "out"), (DB, "MonthlyOutput", M.MonthlyOutputOut, "out"), (DB, "RecentOrder", M.RecentOrderOut, "out"), (DB, "DashboardSummary", M.DashboardSummaryOut, "out")]
    extra = {}
sys.exit(0 if check(pairs, extra) else 1)
