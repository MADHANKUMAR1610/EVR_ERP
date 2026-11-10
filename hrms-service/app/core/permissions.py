"""Permission catalogue and matching rules, identical to the frontend.

Codes have the form "<module>:<action>". "<module>:*" grants every action of a module, "*" grants
everything (frontend `src/shared/permissions/permissions.ts`). The catalogue below is copied from
the frontend's `src/features/hr/permissions.ts` and `src/features/admin/permissions.ts`.

Roles and their permissions are managed by the Identity service; HRMS only reads the effective
permission list from the verified token.
"""

from collections.abc import Iterable


class P:
    """HR permission codes (frontend `HrPermission`)."""

    DASHBOARD_VIEW = "hr.dashboard:view"
    EMPLOYEES_VIEW = "hr.employees:view"
    EMPLOYEES_CREATE = "hr.employees:create"
    EMPLOYEES_EDIT = "hr.employees:edit"
    EMPLOYEES_CHANGE_STATUS = "hr.employees:change-status"
    EMPLOYEES_IMPORT = "hr.employees:import"
    EMPLOYEES_EXPORT = "hr.employees:export"
    EMPLOYEES_VIEW_CONTACT = "hr.employees:view-contact"
    EMPLOYEES_VIEW_SENSITIVE = "hr.employees:view-sensitive"
    DOCUMENTS_VIEW = "hr.documents:view"
    DOCUMENTS_UPLOAD = "hr.documents:upload"
    DOCUMENTS_DELETE = "hr.documents:delete"
    ATTENDANCE_VIEW = "hr.attendance:view"
    ATTENDANCE_CORRECTIONS_VIEW = "hr.attendance-corrections:view"
    ATTENDANCE_CORRECTIONS_SUBMIT = "hr.attendance-corrections:submit"
    ATTENDANCE_CORRECTIONS_APPROVE = "hr.attendance-corrections:approve"
    DEVICES_VIEW = "hr.devices:view"
    DEVICES_MANAGE = "hr.devices:manage"
    SHIFTS_VIEW = "hr.shifts:view"
    SHIFTS_MANAGE = "hr.shifts:manage"
    SHIFTS_ASSIGN = "hr.shifts:assign"
    # New in Module 5 (owner decision): back-dated shift assignments. Identity must add it to its catalogue.
    SHIFTS_ASSIGN_BACKDATED = "hr.shifts:assign-backdated"
    LEAVE_VIEW = "hr.leave:view"
    LEAVE_APPROVE = "hr.leave:approve"
    LEAVE_APPLY_ON_BEHALF = "hr.leave:apply-on-behalf"
    LEAVE_BALANCES_VIEW = "hr.leave-balances:view"
    LEAVE_POLICIES_VIEW = "hr.leave-policies:view"
    LEAVE_POLICIES_MANAGE = "hr.leave-policies:manage"
    LEAVE_WORKFLOWS_MANAGE = "hr.leave-workflows:manage"
    PERMISSION_REQUESTS_VIEW = "hr.permission-requests:view"
    PERMISSION_REQUESTS_APPROVE = "hr.permission-requests:approve"
    OVERTIME_VIEW = "hr.overtime:view"
    OVERTIME_APPROVE = "hr.overtime:approve"
    APPROVALS_VIEW = "hr.approvals:view"
    APPROVALS_ACT = "hr.approvals:act"
    PAYROLL_VIEW = "hr.payroll:view"
    PAYROLL_VIEW_AMOUNTS = "hr.payroll:view-amounts"
    PAYROLL_PROCESS = "hr.payroll:process"
    PAYROLL_REVIEW = "hr.payroll:review"
    PAYROLL_APPROVE = "hr.payroll:approve"
    PAYROLL_CONFIG_MANAGE = "hr.payroll-config:manage"
    PAYROLL_ASSIGNMENTS_MANAGE = "hr.payroll-assignments:manage"
    PAYSLIPS_VIEW = "hr.payslips:view"
    PERFORMANCE_VIEW = "hr.performance:view"
    PERFORMANCE_CYCLES_MANAGE = "hr.performance-cycles:manage"
    GOALS_MANAGE = "hr.goals:manage"
    REVIEWS_ASSESS = "hr.performance-reviews:assess"
    DEVELOPMENT_PLANS_MANAGE = "hr.development-plans:manage"
    REPORTS_VIEW = "hr.reports:view"
    REPORTS_PAYROLL_VIEW = "hr.reports-payroll:view"
    SETTINGS_VIEW = "hr.settings:view"
    SETTINGS_MANAGE = "hr.settings:manage"
    ACCESS_MANAGE = "hr.access:manage"
    INTEGRATIONS_MANAGE = "hr.integrations:manage"
    SELF_VIEW = "hr.self:view"
    SELF_SUBMIT_REQUESTS = "hr.self:submit-requests"
    SELF_VIEW_PAYSLIPS = "hr.self:view-payslips"


class A:
    """Administration permission codes (frontend `AdminPermission`) used by HRMS-owned admin endpoints."""

    VIEW = "admin:view"
    USERS_VIEW = "admin:users.view"  # Identity-owned screens that read HRMS reference lists
    USERS_MANAGE = "admin:users.manage"
    ORGANIZATION_VIEW = "admin:organization.view"
    ORGANIZATION_MANAGE = "admin:organization.manage"
    WORKFLOWS_VIEW = "admin:workflows.view"
    WORKFLOWS_MANAGE = "admin:workflows.manage"
    WORKFLOWS_PUBLISH = "admin:workflows.publish"
    POLICIES_VIEW = "admin:policies.view"
    POLICIES_MANAGE = "admin:policies.manage"
    POLICIES_PAYROLL_MANAGE = "admin:policies.payroll-manage"
    AUDIT_VIEW = "admin:audit.view"


def catalogue() -> list[str]:
    """Every permission code HRMS knows (HR + the administration codes HRMS checks)."""
    codes = [v for k, v in vars(P).items() if k.isupper()] + [v for k, v in vars(A).items() if k.isupper()]
    return sorted(set(codes))


def has_permission(granted: Iterable[str], required: str) -> bool:
    granted = set(granted)
    if "*" in granted or required in granted:
        return True
    module = required.split(":", 1)[0]
    return f"{module}:*" in granted


def has_any(granted: Iterable[str], required: Iterable[str]) -> bool:
    granted = set(granted)
    return any(has_permission(granted, r) for r in required)
