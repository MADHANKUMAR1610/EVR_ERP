"""Who may read each HR reference list (the GET endpoints in reference_data_controller).

Each list is open only to the permissions of the frontend screens that use it, derived from
src/features/**/pages.ts, navigation.ts and the components that call the referenceData hooks.
No list contains employee data; employee pickers use /hr/employees/lookup (module 2), which is
scoped separately. Setup-only fields (sort order, version, audit columns) are served only by /hr/setup.

When a frontend screen starts using a list, add its permission here (and a test).
"""

from app.core.permissions import A, P

# Department filters appear on almost every HR register and on the admin user and organization screens.
DEPARTMENTS = frozenset(
    {
        A.USERS_VIEW, A.USERS_MANAGE, A.ORGANIZATION_VIEW, A.ORGANIZATION_MANAGE,  # admin Users, Organization
        P.EMPLOYEES_VIEW, P.EMPLOYEES_CREATE, P.EMPLOYEES_EDIT, P.EMPLOYEES_IMPORT,  # directory, form, import
        P.DOCUMENTS_VIEW,  # employee documents
        P.SHIFTS_VIEW, P.SHIFTS_MANAGE, P.ATTENDANCE_VIEW, P.ATTENDANCE_CORRECTIONS_VIEW,  # shifts, attendance
        P.LEAVE_VIEW, P.LEAVE_POLICIES_VIEW, P.LEAVE_POLICIES_MANAGE, P.LEAVE_BALANCES_VIEW,  # leave
        P.APPROVALS_VIEW, P.PERMISSION_REQUESTS_VIEW, P.OVERTIME_VIEW,  # approvals, requests
        P.PAYROLL_VIEW, P.PAYROLL_VIEW_AMOUNTS, P.PAYROLL_PROCESS, P.PAYROLL_REVIEW, P.PAYSLIPS_VIEW,  # payroll
        P.PERFORMANCE_VIEW,  # goals, reviews, development plans
        P.REPORTS_VIEW, P.REPORTS_PAYROLL_VIEW,  # report filters
    }
)
# My Leave and My Payslips share the HR registers, which request the department list but never show
# it in self-service. Those callers get only the departments they are entitled to see (their own,
# once employee records exist in module 2) instead of a 403 on every page load.
DEPARTMENTS_SELF = frozenset({P.SELF_VIEW, P.SELF_SUBMIT_REQUESTS, P.SELF_VIEW_PAYSLIPS})

EMPLOYEE_FIELDS = frozenset({P.EMPLOYEES_VIEW, P.EMPLOYEES_CREATE, P.EMPLOYEES_EDIT, P.EMPLOYEES_IMPORT})  # directory filters, form, import
DESIGNATIONS = EMPLOYEE_FIELDS
EMPLOYMENT_TYPES = EMPLOYEE_FIELDS
# Status labels also appear in My Tasks / Approval Inbox (status-change tasks).
EMPLOYEE_STATUSES = EMPLOYEE_FIELDS | {P.EMPLOYEES_CHANGE_STATUS, P.APPROVALS_VIEW}
# Field level: the allowed moves between statuses are needed only to change a status.
EMPLOYEE_STATUS_TRANSITIONS = frozenset({P.EMPLOYEES_CHANGE_STATUS})

EMPLOYEE_FORM = frozenset({P.EMPLOYEES_CREATE, P.EMPLOYEES_EDIT})
WORK_LOCATIONS = EMPLOYEE_FORM | {P.EMPLOYEES_IMPORT}
SHIFT_OPTIONS = EMPLOYEE_FORM
ATTENDANCE_POLICY_OPTIONS = EMPLOYEE_FORM
OVERTIME_POLICY_OPTIONS = EMPLOYEE_FORM

DOCUMENT_TYPES = frozenset({P.DOCUMENTS_VIEW, P.DOCUMENTS_UPLOAD})
PAYROLL_FIELDS = frozenset({P.EMPLOYEES_VIEW_SENSITIVE})  # HRMS_API_CONTRACTS.md

# Employee picker (GET /hr/employees/lookup): the contract's codes plus every screen that hosts a
# picker. Results are also limited to the caller's organizational scope and to 4 fields.
EMPLOYEE_LOOKUP = frozenset(
    {
        P.EMPLOYEES_VIEW, P.DOCUMENTS_VIEW,  # contract B4
        P.EMPLOYEES_CREATE, P.EMPLOYEES_EDIT,  # employee form: reporting manager
        P.DOCUMENTS_UPLOAD,  # upload for an employee
        P.LEAVE_APPLY_ON_BEHALF,  # leave / permission / overtime on behalf
        P.SHIFTS_ASSIGN, P.PAYROLL_ASSIGNMENTS_MANAGE,  # shift and payroll assignment
        P.GOALS_MANAGE, P.DEVELOPMENT_PLANS_MANAGE,  # performance
        A.ORGANIZATION_MANAGE, A.USERS_MANAGE,  # department head, change manager, link a login
    }
)
