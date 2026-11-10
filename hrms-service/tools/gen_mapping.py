"""Builds docs/API_MAPPING.md from tools/endpoint_map.tsv (frontend HTTP calls + contract permissions).

    python tools/gen_mapping.py
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
from collections import Counter

rows = [l.rstrip('\n').split('\t') for l in open(HERE / 'endpoint_map.tsv', encoding='utf-8')]
# Some contract cells were captured with the tail of a response shape before the permission ("… } | perm").
for r in rows:
    if ' | ' in r[4]:
        r[4] = r[4].rsplit(' | ', 1)[1].strip()

# Endpoints implemented and tested, by module (see docs/MODULE_REPORTS.md).
DONE = {('GET', '/admin/departments'), ('POST', '/admin/departments'), ('PUT', '/admin/departments/{did}'),
        ('GET', '/admin/designations'), ('POST', '/admin/designations'), ('PUT', '/admin/designations/{did}'),
        ('GET', '/hr/shifts'), ('POST', '/hr/shifts'), ('PUT', '/hr/shifts/{id}'),
        *{('GET', p) for p in ['/hr/departments', '/hr/designations', '/hr/employment-types', '/hr/employee-statuses', '/hr/work-locations',
                               '/hr/shifts/options', '/hr/attendance-policies/options', '/hr/overtime-policies/options', '/hr/document-types',
                               '/hr/employees/payroll-fields']},
        # Module 2
        ('GET', '/hr/employees'), ('POST', '/hr/employees'), ('GET', '/hr/employees/{employeeId}'), ('PATCH', '/hr/employees/{employeeId}'),
        ('GET', '/hr/employees/lookup'), ('GET', '/hr/employees/{employeeId}/history'), ('POST', '/hr/employees/{employeeId}/status-changes'),
        ('GET', '/admin/reporting-lines'), ('POST', '/admin/reporting-lines/{eid}'),
        # Module 3
        ('GET', '/hr/employees/{employeeId}/documents'), ('POST', '/hr/employees/{employeeId}/documents'),
        ('GET', '/hr/employees/{employeeId}/documents/{documentId}/content'), ('GET', '/hr/employees/{employeeId}/document-checklist'),
        ('GET', '/hr/document-compliance'), ('GET', '/hr/document-compliance/summary'), ('GET', '/hr/document-compliance/attention'),
        # Module 4
        ('GET', '/hr/employee-imports/fields'), ('POST', '/hr/employee-imports/validate'), ('POST', '/hr/employee-imports'), ('GET', '/hr/employee-imports/{jobId}'),
        # Module 5 (G6 policies: areas attendance, shifts, overtime only so far)
        ('GET', '/admin/workflow-processes'), ('GET', '/admin/workflows'), ('GET', '/admin/workflows/{wid}'), ('PUT', '/admin/workflows/{wid}'), ('POST', '/admin/workflows'),
        ('POST', '/admin/workflows/{wid}/publication'), ('POST', '/admin/workflows/{wid}/archive'), ('GET', '/admin/policies/{area}'), ('PUT', '/admin/policies/{area}'),
        ('GET', '/hr/attendance/summary'), ('GET', '/hr/attendance/daily'), ('GET', '/hr/attendance/daily/{employeeId}'), ('GET', '/hr/attendance/monthly'),
        ('GET', '/hr/attendance/monthly/{employeeId}'), ('GET', '/hr/attendance/monthly/export'), ('GET', '/hr/attendance/employees/{employeeId}/calendar'),
        ('GET', '/hr/attendance/events'), ('GET', '/hr/attendance/events/{id}'), ('GET', '/hr/attendance/corrections'), ('GET', '/hr/attendance/corrections/{id}'),
        ('POST', '/hr/attendance/corrections'), ('POST', '/hr/attendance/corrections/{id}/decision'), ('POST', '/hr/shifts/{id}/assignments'),
        ('GET', '/hr/attendance-devices'), ('GET', '/hr/attendance-devices/{id}/sync-history'),
        # Module 6 (leave management + Part B; G6 area `leave`)
        ('GET', '/hr/leave-types'), ('GET', '/hr/leave/summary'), ('GET', '/hr/leave/requests'), ('GET', '/hr/leave/requests/{rid}'), ('GET', '/hr/leave/requests/estimate'),
        ('POST', '/hr/leave/requests'), ('POST', '/hr/leave/requests/{rid}/decision'), ('POST', '/hr/leave/requests/{rid}/cancellation'), ('POST', '/hr/leave/requests/{rid}/comments'),
        ('GET', '/hr/leave/approval-workflows'), ('GET', '/hr/leave/approval-workflows/options'), ('PUT', '/hr/leave/approval-workflows/{wid}'), ('POST', '/hr/leave/approval-workflows'),
        ('GET', '/hr/leave/balances'), ('GET', '/hr/me/leave/balances'), ('GET', '/hr/leave/policies'), ('GET', '/hr/holidays'),
        ('GET', '/hr/permission-requests'), ('GET', '/hr/permission-requests/{rid}'), ('POST', '/hr/permission-requests'), ('POST', '/hr/permission-requests/{rid}/decision'),
        ('GET', '/hr/overtime-requests'), ('GET', '/hr/overtime-requests/{rid}'), ('POST', '/hr/overtime-requests'), ('POST', '/hr/overtime-requests/{rid}/decision'),
        ('GET', '/hr/approvals'),
        # Modules 7 and 8 (payroll E4/H4 with the G6 area `payroll`; performance E5)
        *{tuple(line.split('\t')[2:4]) for line in open(HERE / 'endpoint_map.tsv', encoding='utf-8') if line.startswith(('payroll\t', 'performance\t', 'reports\t', 'workspace\t'))}}

fill = {
    ('PUT', '/admin/departments/{did}'): 'admin:organization.manage', ('POST', '/admin/departments'): 'admin:organization.manage',
    ('PUT', '/admin/designations/{did}'): 'admin:organization.manage', ('POST', '/admin/designations'): 'admin:organization.manage',
    ('GET', '/admin/workflows'): 'admin:workflows.view', ('GET', '/admin/workflows/{wid}'): 'admin:workflows.view',
    ('PUT', '/admin/workflows/{wid}'): 'admin:workflows.manage', ('POST', '/admin/workflows'): 'admin:workflows.manage',
    ('POST', '/auth/login'): 'public (rate-limited)', ('POST', '/auth/logout'): 'signed in', ('GET', '/auth/session'): 'signed in (401 = signed out)',
    ('GET', '/dashboard/summary'): 'dashboard:view',
    ('POST', '/hr/shifts'): 'hr.shifts:manage', ('PUT', '/hr/shifts/{id}'): 'hr.shifts:manage',
    ('GET', '/hr/employees/{employeeId}/documents/{documentId}/content'): 'hr.documents:view + organizational scope',
    ('GET', '/hr/employees/{employeeId}/document-checklist'): 'hr.documents:view + organizational scope',
    ('GET', '/hr/document-compliance'): 'hr.documents:view (employees in scope)', ('GET', '/hr/document-compliance/summary'): 'hr.documents:view (employees in scope)',
    ('GET', '/hr/document-compliance/attention'): 'hr.documents:view (employees in scope)',
    ('GET', '/hr/employee-imports/fields'): 'hr.employees:import (contact columns need view-contact)', ('POST', '/hr/employee-imports/validate'): 'hr.employees:import + organizational scope per row',
    ('POST', '/hr/employee-imports'): 'hr.employees:import + organizational scope per row', ('GET', '/hr/employee-imports/{jobId}'): 'hr.employees:import (own job)',
    ('GET', '/hr/employees'): 'hr.employees:view + organizational scope', ('POST', '/hr/employees'): 'hr.employees:create (+ view-sensitive for payroll, view-contact for contact)',
    ('GET', '/hr/employees/lookup'): 'picker screens (reference_access.EMPLOYEE_LOOKUP); results limited to organizational scope',
    ('GET', '/hr/employees/{employeeId}/history'): 'hr.employees:view + organizational scope',
    ('POST', '/hr/employees/{employeeId}/status-changes'): 'hr.employees:change-status + organizational scope',
    ('POST', '/hr/permission-requests/{rid}/decision'): 'hr.permission-requests:approve, or assigned approver',
    ('POST', '/hr/overtime-requests/{rid}/decision'): 'hr.overtime:approve, or assigned approver',
    ('POST', '/hr/payroll/periods/{periodId}/validation'): 'hr.payroll:process', ('GET', '/hr/payroll/periods/{periodId}/validation'): 'hr.payroll:process',
    ('GET', '/hr/payroll/salary-components'): 'hr.payroll:view', ('GET', '/hr/payroll/salary-structures'): 'hr.payroll:view',
    ('GET', '/hr/payroll/employee-salaries'): 'hr.payroll:view-amounts', ('GET', '/hr/payroll/employee-salaries/{employeeId}'): 'hr.payroll:view-amounts',
    ('GET', '/hr/payroll/reports/register'): 'hr.reports-payroll:view + hr.payroll:view-amounts', ('GET', '/hr/payroll/reports/register/export'): 'hr.reports-payroll:view + hr.payroll:view-amounts',
    ('GET', '/hr/performance/cycles'): 'hr.performance:view', ('POST', '/hr/performance/cycles'): 'hr.performance-cycles:manage',
    ('GET', '/hr/performance/goals'): 'hr.performance:view (scoped)', ('GET', '/hr/performance/goals/{gid}'): 'hr.performance:view (scoped)',
    ('POST', '/hr/performance/goals'): 'hr.goals:manage',
    ('GET', '/hr/performance/development-plans'): 'hr.performance:view (scoped)', ('POST', '/hr/performance/development-plans'): 'hr.development-plans:manage',
    ('PATCH', '/hr/performance/development-plans/{pid}/actions/{aid}'): 'hr.development-plans:manage',
    ('GET', '/hr/workspace/summary'): 'hr.dashboard:view', ('GET', '/hr/tasks'): 'hr.approvals:view',
    ('GET', '/hr/activity'): 'hr.dashboard:view', ('GET', '/hr/upcoming-events'): 'hr.dashboard:view',
    ('GET', '/notifications'): 'signed in (own)', ('POST', '/notifications/{id}/read'): 'signed in (own)', ('POST', '/notifications/read-all'): 'signed in (own)',
    ('GET', '/production/work-order-stages'): 'manufacturing:view', ('GET', '/production/work-orders'): 'manufacturing:view',
    ('GET', '/production/work-orders/{id}'): 'manufacturing:view', ('GET', '/production/work-orders/summary'): 'manufacturing:view',
}
# Reference lists: only the screens that use them (app/core/reference_access.py).
EMP = 'hr.employees:view, :create, :edit or :import'
FORM = 'hr.employees:create or :edit'
for p, perm in {
    '/hr/departments': 'any HR register or admin Users/Organization permission (see reference_access.DEPARTMENTS); self-service: own department only',
    '/hr/designations': EMP, '/hr/employment-types': EMP,
    '/hr/employee-statuses': EMP + ', hr.employees:change-status or hr.approvals:view; transitions only with change-status',
    '/hr/work-locations': FORM + ' or hr.employees:import', '/hr/shifts/options': FORM,
    '/hr/attendance-policies/options': FORM, '/hr/overtime-policies/options': FORM,
    '/hr/document-types': 'hr.documents:view or hr.documents:upload',
}.items():
    fill[('GET', p)] = perm
fill[('GET', '/hr/employees/payroll-fields')] = 'hr.employees:view-sensitive'


def owner(p):
    if p.startswith(('/auth', '/admin/users', '/admin/roles', '/admin/permissions')):
        return 'Identity (other developer)'
    if p.startswith(('/admin/settings', '/admin/integrations', '/admin/overview', '/admin/audit', '/notifications')):
        return 'Platform (other developer)'
    if p.startswith(('/dashboard', '/production')):
        return 'Manufacturing (other developer)'
    return 'HRMS'


CTL = [('/hr/shifts/{id}/assignments', 'attendance'), ('/hr/attendance-policies', 'reference_data'), ('/hr/overtime-policies', 'reference_data'), ('/hr/document-types', 'reference_data'),
       ('/hr/employee-imports', 'employee_import'), ('/hr/employees/payroll-fields', 'reference_data'),
       ('/hr/employees/{employeeId}/document', 'employee_document'), ('/hr/document-compliance', 'document_compliance'), ('/hr/employees', 'employee'),
       ('/hr/attendance/corrections', 'attendance'), ('/hr/attendance/events', 'attendance'),
       ('/hr/attendance-devices', 'attendance'), ('/hr/attendance', 'attendance'), ('/hr/shifts/options', 'reference_data'), ('/hr/shifts', 'shift'),
       ('/hr/leave/approval-workflows', 'leave'), ('/hr/leave/balances', 'leave'), ('/hr/me/leave', 'leave'),
       ('/hr/leave/policies', 'leave'), ('/hr/leave-types', 'leave'), ('/hr/leave', 'leave'), ('/hr/holidays', 'leave'),
       ('/hr/permission-requests', 'short_request'), ('/hr/overtime-requests', 'short_request'), ('/hr/approvals', 'approvals'),
       ('/hr/payroll/configuration', 'payroll_configuration'), ('/hr/payroll/employees', 'payroll_configuration'),
       ('/hr/payroll/periods', 'payroll_period'), ('/hr/payroll/salary', 'salary_structure'), ('/hr/payroll/employee-salaries', 'employee_salary'),
       ('/hr/payroll/payslips', 'payslip'), ('/hr/me/payslips', 'payslip'), ('/hr/payroll/reports', 'payroll_report'),
       ('/hr/performance/cycles', 'performance_cycle'), ('/hr/performance/goals', 'goal'), ('/hr/performance/reviews', 'performance_review'),
       ('/hr/performance/development', 'development_plan'), ('/hr/performance', 'performance_cycle'),
       ('/hr/reports', 'report'), ('/hr/workspace', 'hr_workspace'), ('/hr/tasks', 'hr_workspace'), ('/hr/activity', 'hr_workspace'),
       ('/hr/upcoming', 'hr_workspace'),
       ('/hr/departments', 'reference_data'), ('/hr/designations', 'reference_data'), ('/hr/employment-types', 'reference_data'),
       ('/hr/employee-statuses', 'reference_data'), ('/hr/work-locations', 'reference_data'), ('/hr/attendance-policies', 'reference_data'),
       ('/hr/overtime-policies', 'reference_data'), ('/hr/document-types', 'reference_data'),
       ('/admin/departments', 'department'), ('/admin/designations', 'designation'), ('/admin/reporting-lines', 'reporting_line'),
       ('/admin/workflow', 'attendance_admin'), ('/admin/policies', 'attendance_admin'),
       ('/admin/users', 'user'), ('/admin/roles', 'role'), ('/admin/permissions', 'role'), ('/auth', 'auth'),
       ('/admin/settings', 'company_settings'), ('/admin/integrations', 'integration'), ('/admin/audit', 'audit_event'),
       ('/admin/overview', 'admin_overview'), ('/notifications', 'notification'), ('/dashboard', '—'), ('/production', '—')]


def controller(p):
    for pre, c in CTL:
        if p.startswith(pre):
            return c
    return '?'


out = ["# HRMS Backend: API Endpoint Mapping", "",
       "Generated from the frontend's HTTP services (`src/features/**/api/*.http.ts`) and the permissions in `HRMS_API_CONTRACTS.md`.",
       "Paths are relative to `/api/v1`. **Owner** follows decisions Q1 and Q2 in `ANALYSIS.md`: rows owned by the other developer are not built in hrms-service.",
       "**Status**: ✅ implemented and tested in hrms-service; blank = not yet built.",
       "Permissions in *italics* were not listed in the contract and are taken from the frontend's page and action permissions.", "",
       "| # | Method | Path | Owner | Controller | Permission | Status |", "|---|---|---|---|---|---|---|"]
cnt = Counter()
unknown = 0
for i, (area, name, m, p, perm) in enumerate(rows, 1):
    k = (m, p)
    if perm:
        pm = perm
    elif k in fill:
        pm = '*' + fill[k] + '*'
    else:
        pm = '**?**'
        unknown += 1
    o = owner(p)
    cnt[o] += 1
    c = controller(p)
    c = c if c == '—' else f"`{c}_controller`"
    out.append(f"| {i} | {m} | `{p}` | {o} | {c} | {pm} | {'✅' if k in DONE else ''} |")
out += ["", "**Endpoints by owner:** " + ", ".join(f"{k}: {v}" for k, v in cnt.items()),
        f"**Implemented:** {sum(1 for r in rows if (r[2], r[3]) in DONE)} of {cnt['HRMS']} HRMS endpoints.", "",
        "## Additional HRMS endpoints (not called by the current frontend)", "",
        "HR maintains the reference lists through these endpoints (decision Q4); the setup YAML loader uses the same services.", "",
        "| Method | Path | Controller | Permission | Status |", "|---|---|---|---|---|"]
for m, p in [('GET', '/hr/setup/{kind}'), ('POST', '/hr/setup/{kind}'), ('PUT', '/hr/setup/{kind}/{id}')]:
    out.append(f"| {m} | `{p}` — kind: employment-types, work-locations, attendance-policies, overtime-policies, document-categories | `reference_setup_controller` | {'hr.settings:view or hr.settings:manage' if m == 'GET' else 'hr.settings:manage'} | ✅ |")
for kind in ['employee-statuses', 'document-types', 'payroll-fields', 'employee-access-scopes']:
    for m, p in [('GET', f'/hr/setup/{kind}'), ('POST', f'/hr/setup/{kind}'), ('PUT', f'/hr/setup/{kind}/{{id}}')]:
        ctl = 'employee_access_scope_controller' if kind == 'employee-access-scopes' else 'reference_setup_controller'
        out.append(f"| {m} | `{p}` | `{ctl}` | {'hr.settings:view or hr.settings:manage' if m == 'GET' else 'hr.settings:manage'} | ✅ |")
out += ["| GET / PUT | `/hr/setup/document-settings` — expiry window (pending HR) | `document_settings_controller` | view: hr.settings:view or :manage; write: hr.settings:manage | ✅ |"]
out += ["| GET | `/hr/employee-imports/template?format=xlsx\\|csv` — import template | `employee_import_controller` | hr.employees:import | ✅ |",
        "| POST | `/hr/employee-imports/file-rows` — read a .xlsx/.csv file into rows (nothing stored) | `employee_import_controller` | hr.employees:import | ✅ |",
        "| GET | `/hr/employee-imports/{jobId}/failures.csv` — failed/skipped rows | `employee_import_controller` | hr.employees:import (own job) | ✅ |"]
out += ["| POST | `/hr/attendance/events/ingest` — devices push punches | `attendance_controller` | device API key (`X-Device-Key`) | ✅ |",
        "| GET / POST / PUT | `/hr/setup/attendance-devices[/{id}]`, POST `…/{id}/key` — devices and API keys | `attendance_admin_controller` | hr.devices:manage | ✅ |",
        "| GET / POST | `/hr/setup/attendance-period-locks` — finalized payroll periods | `attendance_admin_controller` | hr.payroll:approve (GET also hr.attendance:view) | ✅ |"]
out += ["| GET / POST / PUT | `/hr/setup/leave-types[/{id}]` — leave types (codes never change) | `leave_setup_controller` | hr.leave-policies:manage | ✅ |",
        "| GET / POST / PUT | `/hr/setup/leave-policies[/{id}]` — entitlement rules entered by HR | `leave_setup_controller` | hr.leave-policies:manage | ✅ |",
        "| GET / POST / PUT / DELETE | `/hr/setup/holidays[/{id}]` — company-wide or per work location | `leave_setup_controller` | hr.leave-policies:manage | ✅ |",
        "| POST | `/hr/setup/leave-allocations`, `/hr/setup/leave-adjustments` — balance entries with a reason | `leave_setup_controller` | hr.leave-policies:manage + organizational scope | ✅ |",
        "| GET | `/hr/setup/leave-ledger` — balance transactions (append-only) | `leave_setup_controller` | hr.leave-policies:manage + organizational scope | ✅ |",
        "| GET | `/hr/setup/notification-outbox` — notification queue status | `leave_setup_controller` | hr.leave-policies:manage or hr.integrations:manage | ✅ |",
        "| GET | `/hr/leave/requests/{rid}/attachments/{aid}/content` — attachment download | `leave_controller` | same access as the request | ✅ |",
        "| GET / PUT | `/admin/policies/leave` — G6 area `leave` (all values empty until HR sets them) | `attendance_admin_controller` | admin:policies.view / admin:policies.manage | ✅ |"]
open(HERE.parent / 'docs' / 'API_MAPPING.md', 'w', encoding='utf-8').write('\n'.join(out) + '\n')
print(dict(cnt), 'unknown permissions:', unknown, 'unknown controllers:', sum('`?_controller`' in l for l in out))
