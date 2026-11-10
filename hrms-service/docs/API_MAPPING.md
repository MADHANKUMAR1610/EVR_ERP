# HRMS Backend: API Endpoint Mapping

Generated from the frontend's HTTP services (`src/features/**/api/*.http.ts`) and the permissions in `HRMS_API_CONTRACTS.md`.
Paths are relative to `/api/v1`. **Owner** follows decisions Q1 and Q2 in `ANALYSIS.md`: rows owned by the other developer are not built in hrms-service.
**Status**: ✅ implemented and tested in hrms-service; blank = not yet built.
Permissions in *italics* were not listed in the contract and are taken from the frontend's page and action permissions.

| # | Method | Path | Owner | Controller | Permission | Status |
|---|---|---|---|---|---|---|
| 1 | GET | `/admin/overview` | Platform (other developer) | `admin_overview_controller` | admin:view |  |
| 2 | GET | `/admin/users` | Identity (other developer) | `user_controller` | admin:users.view |  |
| 3 | GET | `/admin/users/{uid}` | Identity (other developer) | `user_controller` | admin:users.view |  |
| 4 | GET | `/admin/users/{uid}/activity` | Identity (other developer) | `user_controller` | admin:users.view |  |
| 5 | POST | `/admin/users` | Identity (other developer) | `user_controller` | admin:users.manage |  |
| 6 | PUT | `/admin/users/{uid}` | Identity (other developer) | `user_controller` | admin:users.manage |  |
| 7 | POST | `/admin/users/{uid}/status` | Identity (other developer) | `user_controller` | admin:users.manage |  |
| 8 | POST | `/admin/users/{uid}/password` | Identity (other developer) | `user_controller` | admin:users.manage |  |
| 9 | GET | `/admin/permissions` | Identity (other developer) | `role_controller` | admin:roles.view |  |
| 10 | GET | `/admin/roles` | Identity (other developer) | `role_controller` | admin:roles.view |  |
| 11 | GET | `/admin/roles/{rid}` | Identity (other developer) | `role_controller` | admin:roles.view |  |
| 12 | GET | `/admin/roles/{rid}/users` | Identity (other developer) | `role_controller` | admin:roles.view + admin:users.view |  |
| 13 | POST | `/admin/roles` | Identity (other developer) | `role_controller` | admin:roles.manage |  |
| 14 | PUT | `/admin/roles/{rid}` | Identity (other developer) | `role_controller` | admin:roles.manage |  |
| 15 | GET | `/admin/departments` | HRMS | `department_controller` | admin:organization.view | ✅ |
| 16 | PUT | `/admin/departments/{did}` | HRMS | `department_controller` | *admin:organization.manage* | ✅ |
| 17 | POST | `/admin/departments` | HRMS | `department_controller` | *admin:organization.manage* | ✅ |
| 18 | GET | `/admin/designations` | HRMS | `designation_controller` | admin:organization.view | ✅ |
| 19 | PUT | `/admin/designations/{did}` | HRMS | `designation_controller` | *admin:organization.manage* | ✅ |
| 20 | POST | `/admin/designations` | HRMS | `designation_controller` | *admin:organization.manage* | ✅ |
| 21 | GET | `/admin/reporting-lines` | HRMS | `reporting_line_controller` | admin:organization.view + hr.employees:view | ✅ |
| 22 | POST | `/admin/reporting-lines/{eid}` | HRMS | `reporting_line_controller` | admin:organization.manage | ✅ |
| 23 | GET | `/admin/workflow-processes` | HRMS | `attendance_admin_controller` | admin:workflows.view | ✅ |
| 24 | GET | `/admin/workflows` | HRMS | `attendance_admin_controller` | *admin:workflows.view* | ✅ |
| 25 | GET | `/admin/workflows/{wid}` | HRMS | `attendance_admin_controller` | *admin:workflows.view* | ✅ |
| 26 | PUT | `/admin/workflows/{wid}` | HRMS | `attendance_admin_controller` | *admin:workflows.manage* | ✅ |
| 27 | POST | `/admin/workflows` | HRMS | `attendance_admin_controller` | *admin:workflows.manage* | ✅ |
| 28 | POST | `/admin/workflows/{wid}/publication` | HRMS | `attendance_admin_controller` | admin:workflows.publish | ✅ |
| 29 | POST | `/admin/workflows/{wid}/archive` | HRMS | `attendance_admin_controller` | admin:workflows.publish | ✅ |
| 30 | GET | `/admin/settings/company` | Platform (other developer) | `company_settings_controller` | admin:settings.view |  |
| 31 | PUT | `/admin/settings/company` | Platform (other developer) | `company_settings_controller` | admin:settings.manage |  |
| 32 | GET | `/admin/policies/{area}` | HRMS | `attendance_admin_controller` | admin:policies.view | ✅ |
| 33 | PUT | `/admin/policies/{area}` | HRMS | `attendance_admin_controller` | admin:policies.manage. For payroll and attendance: admin:policies.payroll-manage | ✅ |
| 34 | GET | `/admin/audit-events` | Platform (other developer) | `audit_event_controller` | admin:audit.view |  |
| 35 | GET | `/admin/integrations` | Platform (other developer) | `integration_controller` | admin:integrations.view |  |
| 36 | PUT | `/admin/integrations/{iid}` | Platform (other developer) | `integration_controller` | admin:integrations.manage |  |
| 37 | POST | `/admin/integrations/{iid}/test` | Platform (other developer) | `integration_controller` | admin:integrations.manage |  |
| 38 | POST | `/auth/login` | Identity (other developer) | `auth_controller` | *public (rate-limited)* |  |
| 39 | POST | `/auth/logout` | Identity (other developer) | `auth_controller` | *signed in* |  |
| 40 | GET | `/auth/session` | Identity (other developer) | `auth_controller` | *signed in (401 = signed out)* |  |
| 41 | GET | `/dashboard/summary` | Manufacturing (other developer) | — | *dashboard:view* |  |
| 42 | GET | `/hr/approvals` | HRMS | `approvals_controller` | hr.approvals:view | ✅ |
| 43 | GET | `/hr/attendance/summary` | HRMS | `attendance_controller` | hr.attendance:view | ✅ |
| 44 | GET | `/hr/attendance/daily` | HRMS | `attendance_controller` | hr.attendance:view | ✅ |
| 45 | GET | `/hr/attendance/daily/{employeeId}` | HRMS | `attendance_controller` | view, or own/team | ✅ |
| 46 | GET | `/hr/attendance/monthly` | HRMS | `attendance_controller` | hr.attendance:view | ✅ |
| 47 | GET | `/hr/attendance/monthly/{employeeId}` | HRMS | `attendance_controller` | view, or own/team | ✅ |
| 48 | GET | `/hr/attendance/monthly/export` | HRMS | `attendance_controller` | hr.attendance:view | ✅ |
| 49 | GET | `/hr/attendance/employees/{employeeId}/calendar` | HRMS | `attendance_controller` | hr.attendance:view (all employees in scope) or own record (A4) | ✅ |
| 50 | GET | `/hr/attendance/events` | HRMS | `attendance_controller` | hr.attendance:view | ✅ |
| 51 | GET | `/hr/attendance/events/{id}` | HRMS | `attendance_controller` | hr.attendance:view | ✅ |
| 52 | GET | `/hr/attendance/corrections` | HRMS | `attendance_controller` | hr.attendance-corrections:view | ✅ |
| 53 | GET | `/hr/attendance/corrections/{id}` | HRMS | `attendance_controller` | as above | ✅ |
| 54 | POST | `/hr/attendance/corrections` | HRMS | `attendance_controller` | hr.attendance-corrections:submit or own with hr.self:submit-requests | ✅ |
| 55 | POST | `/hr/attendance/corrections/{id}/decision` | HRMS | `attendance_controller` | hr.attendance-corrections:approve, or team with hr.approvals:act | ✅ |
| 56 | GET | `/hr/shifts` | HRMS | `shift_controller` | hr.shifts:view | ✅ |
| 57 | POST | `/hr/shifts` | HRMS | `shift_controller` | *hr.shifts:manage* | ✅ |
| 58 | PUT | `/hr/shifts/{id}` | HRMS | `shift_controller` | *hr.shifts:manage* | ✅ |
| 59 | POST | `/hr/shifts/{id}/assignments` | HRMS | `attendance_controller` | hr.shifts:assign | ✅ |
| 60 | GET | `/hr/attendance-devices` | HRMS | `attendance_controller` | hr.devices:view | ✅ |
| 61 | GET | `/hr/attendance-devices/{id}/sync-history` | HRMS | `attendance_controller` | hr.devices:view | ✅ |
| 62 | GET | `/hr/employees/{employeeId}/documents/{documentId}/content` | HRMS | `employee_document_controller` | *hr.documents:view + organizational scope* | ✅ |
| 63 | GET | `/hr/employees/{employeeId}/document-checklist` | HRMS | `employee_document_controller` | *hr.documents:view + organizational scope* | ✅ |
| 64 | GET | `/hr/document-compliance` | HRMS | `document_compliance_controller` | *hr.documents:view (employees in scope)* | ✅ |
| 65 | GET | `/hr/document-compliance/summary` | HRMS | `document_compliance_controller` | *hr.documents:view (employees in scope)* | ✅ |
| 66 | GET | `/hr/document-compliance/attention` | HRMS | `document_compliance_controller` | *hr.documents:view (employees in scope)* | ✅ |
| 67 | GET | `/hr/employee-imports/fields` | HRMS | `employee_import_controller` | *hr.employees:import (contact columns need view-contact)* | ✅ |
| 68 | POST | `/hr/employee-imports/validate` | HRMS | `employee_import_controller` | *hr.employees:import + organizational scope per row* | ✅ |
| 69 | POST | `/hr/employee-imports` | HRMS | `employee_import_controller` | *hr.employees:import + organizational scope per row* | ✅ |
| 70 | GET | `/hr/employee-imports/{jobId}` | HRMS | `employee_import_controller` | *hr.employees:import (own job)* | ✅ |
| 71 | GET | `/hr/employees` | HRMS | `employee_controller` | *hr.employees:view + organizational scope* | ✅ |
| 72 | POST | `/hr/employees` | HRMS | `employee_controller` | *hr.employees:create (+ view-sensitive for payroll, view-contact for contact)* | ✅ |
| 73 | GET | `/hr/employees/lookup` | HRMS | `employee_controller` | *picker screens (reference_access.EMPLOYEE_LOOKUP); results limited to organizational scope* | ✅ |
| 74 | GET | `/hr/employees/{employeeId}/history` | HRMS | `employee_controller` | *hr.employees:view + organizational scope* | ✅ |
| 75 | POST | `/hr/employees/{employeeId}/status-changes` | HRMS | `employee_controller` | *hr.employees:change-status + organizational scope* | ✅ |
| 76 | GET | `/hr/leave-types` | HRMS | `leave_controller` | authenticated | ✅ |
| 77 | GET | `/hr/leave/summary` | HRMS | `leave_controller` | hr.leave:view | ✅ |
| 78 | GET | `/hr/leave/requests` | HRMS | `leave_controller` | hr.leave:view, or mine | ✅ |
| 79 | GET | `/hr/leave/requests/{rid}` | HRMS | `leave_controller` | scoped | ✅ |
| 80 | GET | `/hr/leave/requests/estimate` | HRMS | `leave_controller` | as apply | ✅ |
| 81 | POST | `/hr/leave/requests` | HRMS | `leave_controller` | as E2 | ✅ |
| 82 | POST | `/hr/leave/requests/{rid}/decision` | HRMS | `leave_controller` | hr.leave:approve, or team | ✅ |
| 83 | POST | `/hr/leave/requests/{rid}/cancellation` | HRMS | `leave_controller` | own, or hr.leave:apply-on-behalf | ✅ |
| 84 | POST | `/hr/leave/requests/{rid}/comments` | HRMS | `leave_controller` | hr.leave:view or the current approver | ✅ |
| 85 | GET | `/hr/leave/approval-workflows` | HRMS | `leave_controller` | hr.leave-policies:view or hr.leave-workflows:manage | ✅ |
| 86 | GET | `/hr/leave/approval-workflows/options` | HRMS | `leave_controller` | as above | ✅ |
| 87 | PUT | `/hr/leave/approval-workflows/{wid}` | HRMS | `leave_controller` | hr.leave-workflows:manage | ✅ |
| 88 | POST | `/hr/leave/approval-workflows` | HRMS | `leave_controller` | hr.leave-workflows:manage | ✅ |
| 89 | GET | `/hr/leave/balances` | HRMS | `leave_controller` | hr.leave-balances:view | ✅ |
| 90 | GET | `/hr/me/leave/balances` | HRMS | `leave_controller` | hr.self:view | ✅ |
| 91 | GET | `/hr/leave/policies` | HRMS | `leave_controller` | hr.leave-policies:view | ✅ |
| 92 | GET | `/hr/holidays` | HRMS | `leave_controller` | authenticated | ✅ |
| 93 | GET | `/hr/permission-requests` | HRMS | `short_request_controller` | hr.permission-requests:view | ✅ |
| 94 | GET | `/hr/permission-requests/{rid}` | HRMS | `short_request_controller` | hr.permission-requests:view | ✅ |
| 95 | POST | `/hr/permission-requests` | HRMS | `short_request_controller` | hr.self:submit-requests | ✅ |
| 96 | POST | `/hr/permission-requests/{rid}/decision` | HRMS | `short_request_controller` | *hr.permission-requests:approve, or assigned approver* | ✅ |
| 97 | GET | `/hr/overtime-requests` | HRMS | `short_request_controller` | hr.overtime:view | ✅ |
| 98 | GET | `/hr/overtime-requests/{rid}` | HRMS | `short_request_controller` | hr.overtime:view | ✅ |
| 99 | POST | `/hr/overtime-requests` | HRMS | `short_request_controller` | hr.self:submit-requests | ✅ |
| 100 | POST | `/hr/overtime-requests/{rid}/decision` | HRMS | `short_request_controller` | *hr.overtime:approve, or assigned approver* | ✅ |
| 101 | GET | `/hr/payroll/periods` | HRMS | `payroll_period_controller` | hr.payroll:view | ✅ |
| 102 | GET | `/hr/payroll/periods/{periodId}/summary` | HRMS | `payroll_period_controller` | hr.payroll:view | ✅ |
| 103 | POST | `/hr/payroll/periods/{periodId}/validation` | HRMS | `payroll_period_controller` | *hr.payroll:process* | ✅ |
| 104 | GET | `/hr/payroll/periods/{periodId}/validation` | HRMS | `payroll_period_controller` | *hr.payroll:process* | ✅ |
| 105 | GET | `/hr/payroll/periods/{periodId}/inputs` | HRMS | `payroll_period_controller` | hr.payroll:view | ✅ |
| 106 | POST | `/hr/payroll/periods/{periodId}/calculation` | HRMS | `payroll_period_controller` | hr.payroll:process | ✅ |
| 107 | GET | `/hr/payroll/periods/{periodId}/results` | HRMS | `payroll_period_controller` | hr.payroll:view | ✅ |
| 108 | GET | `/hr/payroll/periods/{periodId}/results/{employeeId}` | HRMS | `payroll_period_controller` | hr.payroll:view | ✅ |
| 109 | POST | `/hr/payroll/periods/{periodId}/submission` | HRMS | `payroll_period_controller` | hr.payroll:process | ✅ |
| 110 | POST | `/hr/payroll/periods/{periodId}/decision` | HRMS | `payroll_period_controller` | hr.payroll:approve | ✅ |
| 111 | POST | `/hr/payroll/periods/{periodId}/payslips/publication` | HRMS | `payroll_period_controller` | hr.payroll:process | ✅ |
| 112 | GET | `/hr/payroll/salary-components` | HRMS | `salary_structure_controller` | *hr.payroll:view* | ✅ |
| 113 | GET | `/hr/payroll/salary-structures` | HRMS | `salary_structure_controller` | *hr.payroll:view* | ✅ |
| 114 | GET | `/hr/payroll/employee-salaries` | HRMS | `employee_salary_controller` | *hr.payroll:view-amounts* | ✅ |
| 115 | GET | `/hr/payroll/employee-salaries/{employeeId}` | HRMS | `employee_salary_controller` | *hr.payroll:view-amounts* | ✅ |
| 116 | GET | `/hr/me/payslips` | HRMS | `payslip_controller` | hr.self:view-payslips | ✅ |
| 117 | GET | `/hr/payroll/payslips` | HRMS | `payslip_controller` | hr.payslips:view | ✅ |
| 118 | GET | `/hr/payroll/payslips/{pid}/document` | HRMS | `payslip_controller` | as stated | ✅ |
| 119 | GET | `/hr/payroll/reports/register` | HRMS | `payroll_report_controller` | *hr.reports-payroll:view + hr.payroll:view-amounts* | ✅ |
| 120 | GET | `/hr/payroll/reports/register/export` | HRMS | `payroll_report_controller` | *hr.reports-payroll:view + hr.payroll:view-amounts* | ✅ |
| 121 | GET | `/hr/payroll/configurations` | HRMS | `payroll_configuration_controller` | hr.payroll:view | ✅ |
| 122 | GET | `/hr/payroll/configurations/options` | HRMS | `payroll_configuration_controller` | hr.payroll:view | ✅ |
| 123 | PUT | `/hr/payroll/configurations/{cid}` | HRMS | `payroll_configuration_controller` | hr.payroll-config:manage | ✅ |
| 124 | POST | `/hr/payroll/configurations` | HRMS | `payroll_configuration_controller` | hr.payroll-config:manage | ✅ |
| 125 | GET | `/hr/payroll/configuration-assignments` | HRMS | `payroll_configuration_controller` | hr.payroll:view | ✅ |
| 126 | POST | `/hr/payroll/configuration-assignments/preview` | HRMS | `payroll_configuration_controller` | hr.payroll-assignments:manage | ✅ |
| 127 | POST | `/hr/payroll/configuration-assignments` | HRMS | `payroll_configuration_controller` | hr.payroll-assignments:manage | ✅ |
| 128 | POST | `/hr/payroll/configuration-assignments/{aid}/end` | HRMS | `payroll_configuration_controller` | hr.payroll-assignments:manage | ✅ |
| 129 | GET | `/hr/payroll/employees/{employeeId}/effective-configuration` | HRMS | `payroll_configuration_controller` | hr.payroll:view | ✅ |
| 130 | GET | `/hr/payroll/configuration-assignments/history` | HRMS | `payroll_configuration_controller` | hr.payroll:view | ✅ |
| 131 | GET | `/hr/performance/summary` | HRMS | `performance_cycle_controller` | hr.performance:view | ✅ |
| 132 | GET | `/hr/performance/configuration` | HRMS | `performance_cycle_controller` | hr.performance:view | ✅ |
| 133 | GET | `/hr/performance/cycles` | HRMS | `performance_cycle_controller` | *hr.performance:view* | ✅ |
| 134 | POST | `/hr/performance/cycles` | HRMS | `performance_cycle_controller` | *hr.performance-cycles:manage* | ✅ |
| 135 | POST | `/hr/performance/cycles/{cid}/advance` | HRMS | `performance_cycle_controller` | hr.performance-cycles:manage | ✅ |
| 136 | GET | `/hr/performance/goals` | HRMS | `goal_controller` | *hr.performance:view (scoped)* | ✅ |
| 137 | GET | `/hr/performance/goals/{gid}` | HRMS | `goal_controller` | *hr.performance:view (scoped)* | ✅ |
| 138 | POST | `/hr/performance/goals` | HRMS | `goal_controller` | *hr.goals:manage* | ✅ |
| 139 | POST | `/hr/performance/goals/{gid}/progress` | HRMS | `goal_controller` | hr.goals:manage | ✅ |
| 140 | GET | `/hr/performance/reviews` | HRMS | `performance_review_controller` | hr.performance:view | ✅ |
| 141 | GET | `/hr/performance/reviews/{rid}` | HRMS | `performance_review_controller` | scoped | ✅ |
| 142 | PUT | `/hr/performance/reviews/{rid}/manager-assessment` | HRMS | `performance_review_controller` | assigned reviewer with hr.performance-reviews:assess *(new)* | ✅ |
| 143 | GET | `/hr/performance/development-plans` | HRMS | `development_plan_controller` | *hr.performance:view (scoped)* | ✅ |
| 144 | POST | `/hr/performance/development-plans` | HRMS | `development_plan_controller` | *hr.development-plans:manage* | ✅ |
| 145 | PATCH | `/hr/performance/development-plans/{pid}/actions/{aid}` | HRMS | `development_plan_controller` | *hr.development-plans:manage* | ✅ |
| 146 | GET | `/hr/departments` | HRMS | `reference_data_controller` | *any HR register or admin Users/Organization permission (see reference_access.DEPARTMENTS); self-service: own department only* | ✅ |
| 147 | GET | `/hr/designations` | HRMS | `reference_data_controller` | *hr.employees:view, :create, :edit or :import* | ✅ |
| 148 | GET | `/hr/employment-types` | HRMS | `reference_data_controller` | *hr.employees:view, :create, :edit or :import* | ✅ |
| 149 | GET | `/hr/employee-statuses` | HRMS | `reference_data_controller` | *hr.employees:view, :create, :edit or :import, hr.employees:change-status or hr.approvals:view; transitions only with change-status* | ✅ |
| 150 | GET | `/hr/work-locations` | HRMS | `reference_data_controller` | *hr.employees:create or :edit or hr.employees:import* | ✅ |
| 151 | GET | `/hr/shifts/options` | HRMS | `reference_data_controller` | *hr.employees:create or :edit* | ✅ |
| 152 | GET | `/hr/attendance-policies/options` | HRMS | `reference_data_controller` | *hr.employees:create or :edit* | ✅ |
| 153 | GET | `/hr/overtime-policies/options` | HRMS | `reference_data_controller` | *hr.employees:create or :edit* | ✅ |
| 154 | GET | `/hr/document-types` | HRMS | `reference_data_controller` | *hr.documents:view or hr.documents:upload* | ✅ |
| 155 | GET | `/hr/employees/payroll-fields` | HRMS | `reference_data_controller` | *hr.employees:view-sensitive* | ✅ |
| 156 | GET | `/hr/reports` | HRMS | `report_controller` | hr.reports:view or hr.reports-payroll:view | ✅ |
| 157 | GET | `/hr/reports/dashboard` | HRMS | `report_controller` | hr.reports:view (each figure gated by its module permission) | ✅ |
| 158 | GET | `/hr/reports/{reportId}` | HRMS | `report_controller` | per report (below) | ✅ |
| 159 | GET | `/hr/reports/{reportId}/export` | HRMS | `report_controller` | as the report | ✅ |
| 160 | GET | `/hr/reports/activity` | HRMS | `report_controller` | hr.reports:view | ✅ |
| 161 | GET | `/hr/workspace/summary` | HRMS | `hr_workspace_controller` | *hr.dashboard:view* | ✅ |
| 162 | GET | `/hr/tasks` | HRMS | `hr_workspace_controller` | *hr.approvals:view* | ✅ |
| 163 | GET | `/hr/activity` | HRMS | `hr_workspace_controller` | *hr.dashboard:view* | ✅ |
| 164 | GET | `/hr/upcoming-events` | HRMS | `hr_workspace_controller` | *hr.dashboard:view* | ✅ |
| 165 | GET | `/notifications` | Platform (other developer) | `notification_controller` | *signed in (own)* |  |
| 166 | GET | `/notifications/history` | Platform (other developer) | `notification_controller` | Authenticated |  |
| 167 | GET | `/notifications/preferences` | Platform (other developer) | `notification_controller` | Authenticated |  |
| 168 | PUT | `/notifications/preferences` | Platform (other developer) | `notification_controller` | Authenticated (own preferences only) |  |
| 169 | POST | `/notifications/{id}/read` | Platform (other developer) | `notification_controller` | *signed in (own)* |  |
| 170 | POST | `/notifications/read-all` | Platform (other developer) | `notification_controller` | *signed in (own)* |  |
| 171 | GET | `/production/work-order-stages` | Manufacturing (other developer) | — | *manufacturing:view* |  |
| 172 | GET | `/production/work-orders` | Manufacturing (other developer) | — | *manufacturing:view* |  |
| 173 | GET | `/production/work-orders/{id}` | Manufacturing (other developer) | — | *manufacturing:view* |  |
| 174 | GET | `/production/work-orders/summary` | Manufacturing (other developer) | — | *manufacturing:view* |  |
| 175 | GET | `/hr/employees/{employeeId}` | HRMS | `employee_controller` | hr.employees:view (contact and payroll fields scoped) | ✅ |
| 176 | PATCH | `/hr/employees/{employeeId}` | HRMS | `employee_controller` | hr.employees:edit | ✅ |
| 177 | GET | `/hr/employees/{employeeId}/documents` | HRMS | `employee_document_controller` | hr.documents:view + organizational scope | ✅ |
| 178 | POST | `/hr/employees/{employeeId}/documents` | HRMS | `employee_document_controller` | hr.documents:upload + organizational scope | ✅ |

**Endpoints by owner:** Platform (other developer): 13, Identity (other developer): 16, HRMS: 144, Manufacturing (other developer): 5
**Implemented:** 144 of 144 HRMS endpoints.

## Additional HRMS endpoints (not called by the current frontend)

HR maintains the reference lists through these endpoints (decision Q4); the setup YAML loader uses the same services.

| Method | Path | Controller | Permission | Status |
|---|---|---|---|---|
| GET | `/hr/setup/{kind}` — kind: employment-types, work-locations, attendance-policies, overtime-policies, document-categories | `reference_setup_controller` | hr.settings:view or hr.settings:manage | ✅ |
| POST | `/hr/setup/{kind}` — kind: employment-types, work-locations, attendance-policies, overtime-policies, document-categories | `reference_setup_controller` | hr.settings:manage | ✅ |
| PUT | `/hr/setup/{kind}/{id}` — kind: employment-types, work-locations, attendance-policies, overtime-policies, document-categories | `reference_setup_controller` | hr.settings:manage | ✅ |
| GET | `/hr/setup/employee-statuses` | `reference_setup_controller` | hr.settings:view or hr.settings:manage | ✅ |
| POST | `/hr/setup/employee-statuses` | `reference_setup_controller` | hr.settings:manage | ✅ |
| PUT | `/hr/setup/employee-statuses/{id}` | `reference_setup_controller` | hr.settings:manage | ✅ |
| GET | `/hr/setup/document-types` | `reference_setup_controller` | hr.settings:view or hr.settings:manage | ✅ |
| POST | `/hr/setup/document-types` | `reference_setup_controller` | hr.settings:manage | ✅ |
| PUT | `/hr/setup/document-types/{id}` | `reference_setup_controller` | hr.settings:manage | ✅ |
| GET | `/hr/setup/payroll-fields` | `reference_setup_controller` | hr.settings:view or hr.settings:manage | ✅ |
| POST | `/hr/setup/payroll-fields` | `reference_setup_controller` | hr.settings:manage | ✅ |
| PUT | `/hr/setup/payroll-fields/{id}` | `reference_setup_controller` | hr.settings:manage | ✅ |
| GET | `/hr/setup/employee-access-scopes` | `employee_access_scope_controller` | hr.settings:view or hr.settings:manage | ✅ |
| POST | `/hr/setup/employee-access-scopes` | `employee_access_scope_controller` | hr.settings:manage | ✅ |
| PUT | `/hr/setup/employee-access-scopes/{id}` | `employee_access_scope_controller` | hr.settings:manage | ✅ |
| GET / PUT | `/hr/setup/document-settings` — expiry window (pending HR) | `document_settings_controller` | view: hr.settings:view or :manage; write: hr.settings:manage | ✅ |
| GET | `/hr/employee-imports/template?format=xlsx\|csv` — import template | `employee_import_controller` | hr.employees:import | ✅ |
| POST | `/hr/employee-imports/file-rows` — read a .xlsx/.csv file into rows (nothing stored) | `employee_import_controller` | hr.employees:import | ✅ |
| GET | `/hr/employee-imports/{jobId}/failures.csv` — failed/skipped rows | `employee_import_controller` | hr.employees:import (own job) | ✅ |
| POST | `/hr/attendance/events/ingest` — devices push punches | `attendance_controller` | device API key (`X-Device-Key`) | ✅ |
| GET / POST / PUT | `/hr/setup/attendance-devices[/{id}]`, POST `…/{id}/key` — devices and API keys | `attendance_admin_controller` | hr.devices:manage | ✅ |
| GET / POST | `/hr/setup/attendance-period-locks` — finalized payroll periods | `attendance_admin_controller` | hr.payroll:approve (GET also hr.attendance:view) | ✅ |
| GET / POST / PUT | `/hr/setup/leave-types[/{id}]` — leave types (codes never change) | `leave_setup_controller` | hr.leave-policies:manage | ✅ |
| GET / POST / PUT | `/hr/setup/leave-policies[/{id}]` — entitlement rules entered by HR | `leave_setup_controller` | hr.leave-policies:manage | ✅ |
| GET / POST / PUT / DELETE | `/hr/setup/holidays[/{id}]` — company-wide or per work location | `leave_setup_controller` | hr.leave-policies:manage | ✅ |
| POST | `/hr/setup/leave-allocations`, `/hr/setup/leave-adjustments` — balance entries with a reason | `leave_setup_controller` | hr.leave-policies:manage + organizational scope | ✅ |
| GET | `/hr/setup/leave-ledger` — balance transactions (append-only) | `leave_setup_controller` | hr.leave-policies:manage + organizational scope | ✅ |
| GET | `/hr/setup/notification-outbox` — notification queue status | `leave_setup_controller` | hr.leave-policies:manage or hr.integrations:manage | ✅ |
| GET | `/hr/leave/requests/{rid}/attachments/{aid}/content` — attachment download | `leave_controller` | same access as the request | ✅ |
| GET / PUT | `/admin/policies/leave` — G6 area `leave` (all values empty until HR sets them) | `attendance_admin_controller` | admin:policies.view / admin:policies.manage | ✅ |
