# HRMS Backend: API Endpoint Catalog

Generated on 2026-11-05 from the running application's route table (`app.main:create_app`), so it lists exactly what is
implemented. Paths include the `/api/v1` prefix. **Access** is the endpoint guard (any one of the listed permissions);
where the endpoint has no guard of its own, the rule applied in the service is shown in *italics*. Every endpoint except
the two health checks and device ingestion requires a valid Identity session token, and organizational scope applies
to every list and record of employees. **Frontend** shows whether the current frontend calls the endpoint (verified by
`tools/verify_contracts.py`, 90 of 90 calls present).

For the full frontend list (178 endpoints, including those owned by other services and those not yet built) see
`docs/API_MAPPING.md`. Interactive documentation: `/docs` (Swagger) and `/openapi.json` when `DOCS_ENABLED=true`;
a snapshot is included as `docs/openapi.json`.

## Foundation

2 endpoints.

| Method | Path | Purpose | Access | Frontend |
|---|---|---|---|---|
| GET | `/health` | Liveness: the process is running | *public (process health)* | addition |
| GET | `/health/ready` | Readiness: the database is reachable | *public (database readiness)* | addition |

## Module 1 Organization & reference data

31 endpoints.

| Method | Path | Purpose | Access | Frontend |
|---|---|---|---|---|
| GET | `/api/v1/admin/departments` | list departments | admin:organization.view or admin:organization.manage | ✅ |
| POST | `/api/v1/admin/departments` | create department | admin:organization.manage | ✅ |
| PUT | `/api/v1/admin/departments/{department_id}` | update department | admin:organization.manage | ✅ |
| GET | `/api/v1/admin/designations` | list designations | admin:organization.view or admin:organization.manage | ✅ |
| POST | `/api/v1/admin/designations` | create designation | admin:organization.manage | ✅ |
| PUT | `/api/v1/admin/designations/{designation_id}` | update designation | admin:organization.manage | ✅ |
| GET | `/api/v1/hr/attendance-policies/options` | Active attendance policies | hr.employees:create or hr.employees:edit | ✅ |
| GET | `/api/v1/hr/departments` | Departments (including inactive) | *screens that use the list (reference_access); self-service callers get only their own department* | ✅ |
| GET | `/api/v1/hr/designations` | Designations (including inactive) | hr.employees:create or hr.employees:edit or hr.employees:import or hr.employees:view | ✅ |
| GET | `/api/v1/hr/document-types` | Employee document types and upload rules | hr.documents:upload or hr.documents:view | ✅ |
| GET | `/api/v1/hr/employee-statuses` | Employee statuses (transitions only for status changers) | hr.approvals:view or hr.employees:change-status or hr.employees:create or hr.employees:edit or hr.employees:import or hr.employees:view | ✅ |
| GET | `/api/v1/hr/employees/payroll-fields` | Payroll field definitions for the employee form | hr.employees:view-sensitive | ✅ |
| GET | `/api/v1/hr/employment-types` | Employment types | hr.employees:create or hr.employees:edit or hr.employees:import or hr.employees:view | ✅ |
| GET | `/api/v1/hr/overtime-policies/options` | Active overtime policies | hr.employees:create or hr.employees:edit | ✅ |
| GET | `/api/v1/hr/setup/document-types` | list document types | hr.settings:view or hr.settings:manage | addition |
| POST | `/api/v1/hr/setup/document-types` | create document type | hr.settings:manage | addition |
| PUT | `/api/v1/hr/setup/document-types/{type_id}` | update document type | hr.settings:manage | addition |
| GET | `/api/v1/hr/setup/employee-statuses` | list statuses | hr.settings:view or hr.settings:manage | addition |
| POST | `/api/v1/hr/setup/employee-statuses` | create status | hr.settings:manage | addition |
| PUT | `/api/v1/hr/setup/employee-statuses/{status_id}` | update status | hr.settings:manage | addition |
| GET | `/api/v1/hr/setup/payroll-fields` | list payroll fields | hr.settings:view or hr.settings:manage | addition |
| POST | `/api/v1/hr/setup/payroll-fields` | create payroll field | hr.settings:manage | addition |
| PUT | `/api/v1/hr/setup/payroll-fields/{field_id}` | update payroll field | hr.settings:manage | addition |
| GET | `/api/v1/hr/setup/{kind}` | list coded | hr.settings:view or hr.settings:manage | addition |
| POST | `/api/v1/hr/setup/{kind}` | create coded | hr.settings:manage | addition |
| PUT | `/api/v1/hr/setup/{kind}/{item_id}` | update coded | hr.settings:manage | addition |
| GET | `/api/v1/hr/shifts` | list shifts | hr.shifts:view or hr.shifts:manage | ✅ |
| POST | `/api/v1/hr/shifts` | create shift | hr.shifts:manage | ✅ |
| GET | `/api/v1/hr/shifts/options` | Active shifts for the employee form | hr.employees:create or hr.employees:edit | ✅ |
| PUT | `/api/v1/hr/shifts/{shift_id}` | update shift | hr.shifts:manage | ✅ |
| GET | `/api/v1/hr/work-locations` | Work locations | hr.employees:create or hr.employees:edit or hr.employees:import | ✅ |

## Module 2 Employees

12 endpoints.

| Method | Path | Purpose | Access | Frontend |
|---|---|---|---|---|
| GET | `/api/v1/admin/reporting-lines` | Reporting lines (scoped) | admin:organization.view or admin:organization.manage and hr.employees:view | ✅ |
| POST | `/api/v1/admin/reporting-lines/{employee_id}` | Change an employee's reporting manager | admin:organization.manage | ✅ |
| GET | `/api/v1/hr/employees` | Employee directory (scoped) | hr.employees:view | ✅ |
| POST | `/api/v1/hr/employees` | Add an employee | hr.employees:create | ✅ |
| GET | `/api/v1/hr/employees/lookup` | Employee picker search (scoped, 4 fields) | admin:organization.manage or admin:users.manage or hr.development-plans:manage or hr.documents:upload or hr.documents:view or hr.employees:create or hr.employees:edit or hr.employees:view or hr.goals:manage or hr.leave:apply-on-behalf or hr.payroll-assignments:manage or hr.shifts:assign | ✅ |
| GET | `/api/v1/hr/employees/{employee_id}` | Employee record (scoped; contact and payroll by permission) | hr.employees:view | ✅ |
| PATCH | `/api/v1/hr/employees/{employee_id}` | Update an employee | hr.employees:edit | ✅ |
| GET | `/api/v1/hr/employees/{employee_id}/history` | Employee history (section names only) | hr.employees:view | ✅ |
| POST | `/api/v1/hr/employees/{employee_id}/status-changes` | Record a status change | hr.employees:change-status | ✅ |
| GET | `/api/v1/hr/setup/employee-access-scopes` | list scopes | hr.settings:view or hr.settings:manage | addition |
| POST | `/api/v1/hr/setup/employee-access-scopes` | create scope | hr.settings:manage | addition |
| PUT | `/api/v1/hr/setup/employee-access-scopes/{scope_id}` | update scope | hr.settings:manage | addition |

## Module 3 Employee documents

9 endpoints.

| Method | Path | Purpose | Access | Frontend |
|---|---|---|---|---|
| GET | `/api/v1/hr/document-compliance` | Document completion per employee | hr.documents:view | ✅ |
| GET | `/api/v1/hr/document-compliance/attention` | Needs attention: expiring, awaiting verification, missing | hr.documents:view | ✅ |
| GET | `/api/v1/hr/document-compliance/summary` | Completion totals | hr.documents:view | ✅ |
| GET | `/api/v1/hr/employees/{employee_id}/document-checklist` | One employee's document completion | hr.documents:view | ✅ |
| GET | `/api/v1/hr/employees/{employee_id}/documents` | An employee's documents, newest first | hr.documents:view | ✅ |
| POST | `/api/v1/hr/employees/{employee_id}/documents` | Upload one document (multipart/form-data) | hr.documents:upload | ✅ |
| GET | `/api/v1/hr/employees/{employee_id}/documents/{document_id}/content` | Download or preview a document | hr.documents:view | ✅ |
| GET | `/api/v1/hr/setup/document-settings` | get settings  | hr.settings:view or hr.settings:manage | addition |
| PUT | `/api/v1/hr/setup/document-settings` | update settings | hr.settings:manage | addition |

## Module 4 Employee import

7 endpoints.

| Method | Path | Purpose | Access | Frontend |
|---|---|---|---|---|
| POST | `/api/v1/hr/employee-imports` | Start an import job (rows are re-checked when imported) | hr.employees:import | ✅ |
| GET | `/api/v1/hr/employee-imports/fields` | Import columns (the template is generated from these) | hr.employees:import | ✅ |
| POST | `/api/v1/hr/employee-imports/file-rows` | Read a .xlsx/.csv file into import rows (nothing is stored) | hr.employees:import | addition |
| GET | `/api/v1/hr/employee-imports/template` | Download the import template (.xlsx or .csv) | hr.employees:import | addition |
| POST | `/api/v1/hr/employee-imports/validate` | Check every row without saving anything (preview) | hr.employees:import | ✅ |
| GET | `/api/v1/hr/employee-imports/{job_id}` | Import job status (job owner only) | hr.employees:import | ✅ |
| GET | `/api/v1/hr/employee-imports/{job_id}/failures.csv` | Failed and skipped rows as CSV (job owner only) | hr.employees:import | addition |

## Module 5 Time & attendance

32 endpoints.

| Method | Path | Purpose | Access | Frontend |
|---|---|---|---|---|
| GET | `/api/v1/admin/policies/{area}` | get policy | admin:policies.view or admin:policies.manage or admin:policies.payroll-manage | ✅ |
| PUT | `/api/v1/admin/policies/{area}` | save policy | admin:policies.manage or admin:policies.payroll-manage | ✅ |
| GET | `/api/v1/admin/workflow-processes` | processes | admin:workflows.view or admin:workflows.manage | ✅ |
| GET | `/api/v1/admin/workflows` | workflows | admin:workflows.view or admin:workflows.manage | ✅ |
| POST | `/api/v1/admin/workflows` | create workflow | admin:workflows.manage | ✅ |
| GET | `/api/v1/admin/workflows/{workflow_id}` | workflow | admin:workflows.view or admin:workflows.manage | ✅ |
| PUT | `/api/v1/admin/workflows/{workflow_id}` | update workflow | admin:workflows.manage | ✅ |
| POST | `/api/v1/admin/workflows/{workflow_id}/archive` | archive workflow | admin:workflows.publish | ✅ |
| POST | `/api/v1/admin/workflows/{workflow_id}/publication` | publish workflow | admin:workflows.publish | ✅ |
| GET | `/api/v1/hr/attendance-devices` | Attendance devices (read-only) | hr.devices:view | ✅ |
| GET | `/api/v1/hr/attendance-devices/{device_id}/sync-history` | Recent synchronization runs | hr.devices:view | ✅ |
| GET | `/api/v1/hr/attendance/corrections` | Correction requests (scoped) | hr.attendance-corrections:view | ✅ |
| POST | `/api/v1/hr/attendance/corrections` | Request a correction | hr.attendance-corrections:submit or hr.self:submit-requests | ✅ |
| GET | `/api/v1/hr/attendance/corrections/{correction_id}` | One correction request and its history | *corrections view in scope, own, current step approver, or manager* | ✅ |
| POST | `/api/v1/hr/attendance/corrections/{correction_id}/decision` | Approve or reject (workflow step approver, or HR oversight) | hr.attendance-corrections:approve or hr.approvals:act | ✅ |
| GET | `/api/v1/hr/attendance/daily` | Daily register | hr.attendance:view | ✅ |
| GET | `/api/v1/hr/attendance/daily/{employee_id}` | One employee's day (attendance view in scope, own record, or direct report) | *hr.attendance:view in scope, own record (hr.self:view), or direct report (hr.approvals:act); else 404* | ✅ |
| GET | `/api/v1/hr/attendance/employees/{employee_id}/calendar` | One employee's attendance calendar (H1) | *as the day detail; 403 outside scope (contract H1)* | ✅ |
| GET | `/api/v1/hr/attendance/events` | Raw punches received for a date | hr.attendance:view | ✅ |
| POST | `/api/v1/hr/attendance/events/ingest` | Devices push punches (X-Device-Key; not for user tokens) | *device API key (X-Device-Key, hashed); no user token* | addition |
| GET | `/api/v1/hr/attendance/events/{event_id}` | One punch and its day record | hr.attendance:view | ✅ |
| GET | `/api/v1/hr/attendance/monthly` | Monthly register | hr.attendance:view | ✅ |
| GET | `/api/v1/hr/attendance/monthly/export` | Monthly register as CSV (default) or XLSX | hr.attendance:view | ✅ |
| GET | `/api/v1/hr/attendance/monthly/{employee_id}` | One employee's month | *as the day detail* | ✅ |
| GET | `/api/v1/hr/attendance/summary` | Attendance overview for a day | hr.attendance:view | ✅ |
| GET | `/api/v1/hr/setup/attendance-devices` | setup devices | hr.devices:manage | addition |
| POST | `/api/v1/hr/setup/attendance-devices` | create device | hr.devices:manage | addition |
| PUT | `/api/v1/hr/setup/attendance-devices/{device_id}` | update device | hr.devices:manage | addition |
| POST | `/api/v1/hr/setup/attendance-devices/{device_id}/key` | Issue a new device API key (shown once) | hr.devices:manage | addition |
| GET | `/api/v1/hr/setup/attendance-period-locks` | locks | hr.payroll:approve or hr.attendance:view | addition |
| POST | `/api/v1/hr/setup/attendance-period-locks` | Lock finished dates (finalized payroll) | hr.payroll:approve | addition |
| POST | `/api/v1/hr/shifts/{shift_id}/assignments` | Assign a shift from a date (dated history) | hr.shifts:assign | ✅ |

## Module 6 Leave management

33 endpoints.

| Method | Path | Purpose | Access | Frontend |
|---|---|---|---|---|
| GET | `/api/v1/hr/approvals` | Pending requests the caller may decide now, oldest first | hr.approvals:view or hr.approvals:act or hr.leave:approve or hr.permission-requests:approve or hr.overtime:approve or hr.attendance-corrections:approve | ✅ |
| GET | `/api/v1/hr/holidays` | Holidays of a year: the caller's applicable holidays, or all for HR | *any signed-in user (own location; all for HR)* | ✅ |
| GET | `/api/v1/hr/leave-types` | Leave types (any signed-in user) | *any signed-in user* | ✅ |
| GET | `/api/v1/hr/leave/approval-workflows` | Leave approval workflows | hr.leave-policies:view or hr.leave-workflows:manage | ✅ |
| POST | `/api/v1/hr/leave/approval-workflows` | create workflow | hr.leave-workflows:manage | ✅ |
| GET | `/api/v1/hr/leave/approval-workflows/options` | Approver options and company working days | hr.leave-policies:view or hr.leave-workflows:manage | ✅ |
| PUT | `/api/v1/hr/leave/approval-workflows/{workflow_id}` | update workflow | hr.leave-workflows:manage | ✅ |
| GET | `/api/v1/hr/leave/balances` | Balances per employee (organizational scope) | hr.leave-balances:view | ✅ |
| GET | `/api/v1/hr/leave/policies` | Leave policies (read-only) | hr.leave-policies:view or hr.leave-policies:manage | ✅ |
| GET | `/api/v1/hr/leave/requests` | Leave requests (HR in scope, own, or assigned to the caller) | *scope=mine: own; else hr.leave:view / :approve / hr.approvals:view / :act (rows: scope, own, assigned)* | ✅ |
| POST | `/api/v1/hr/leave/requests` | Apply for leave (multipart/form-data, attachments optional) | hr.self:submit-requests or hr.leave:apply-on-behalf | ✅ |
| GET | `/api/v1/hr/leave/requests/estimate` | Preview of an application | hr.self:submit-requests or hr.leave:apply-on-behalf | ✅ |
| GET | `/api/v1/hr/leave/requests/{request_id}` | One leave request | *HR in scope, the employee, or assigned/escalated approver; else 404* | ✅ |
| GET | `/api/v1/hr/leave/requests/{request_id}/attachments/{attachment_id}/content` | Download an attachment (same access as the request) | *same access as the request* | addition |
| POST | `/api/v1/hr/leave/requests/{request_id}/cancellation` | Cancel (pending, or approved and not started) | *the employee, or hr.leave:apply-on-behalf in scope* | ✅ |
| POST | `/api/v1/hr/leave/requests/{request_id}/comments` | Review comment without a decision | *hr.leave:view/approve in scope, or assigned/escalated approver* | ✅ |
| POST | `/api/v1/hr/leave/requests/{request_id}/decision` | Approve or reject | hr.leave:approve or hr.approvals:act | ✅ |
| GET | `/api/v1/hr/leave/summary` | Leave dashboard | hr.leave:view | ✅ |
| GET | `/api/v1/hr/me/leave/balances` | The signed-in employee's balances | *hr.self:view (own record)* | ✅ |
| GET | `/api/v1/hr/setup/holidays` | holidays | hr.leave-policies:manage | addition |
| POST | `/api/v1/hr/setup/holidays` | create holiday | hr.leave-policies:manage | addition |
| DELETE | `/api/v1/hr/setup/holidays/{holiday_id}` | delete holiday | hr.leave-policies:manage | addition |
| PUT | `/api/v1/hr/setup/holidays/{holiday_id}` | update holiday | hr.leave-policies:manage | addition |
| POST | `/api/v1/hr/setup/leave-adjustments` | Correct a balance (+/- days, with a reason) | hr.leave-policies:manage | addition |
| POST | `/api/v1/hr/setup/leave-allocations` | Credit days to an employee's balance (with a reason) | hr.leave-policies:manage | addition |
| GET | `/api/v1/hr/setup/leave-ledger` | Balance transactions (append-only), newest first | hr.leave-policies:manage | addition |
| GET | `/api/v1/hr/setup/leave-policies` | leave policies | hr.leave-policies:manage | addition |
| POST | `/api/v1/hr/setup/leave-policies` | create leave policy | hr.leave-policies:manage | addition |
| PUT | `/api/v1/hr/setup/leave-policies/{policy_id}` | update leave policy | hr.leave-policies:manage | addition |
| GET | `/api/v1/hr/setup/leave-types` | leave types | hr.leave-policies:manage | addition |
| POST | `/api/v1/hr/setup/leave-types` | create leave type | hr.leave-policies:manage | addition |
| PUT | `/api/v1/hr/setup/leave-types/{type_id}` | update leave type | hr.leave-policies:manage | addition |
| GET | `/api/v1/hr/setup/notification-outbox` | Notification queue status | hr.leave-policies:manage or hr.integrations:manage | addition |

## Module 6 Leave management (Part B)

8 endpoints.

| Method | Path | Purpose | Access | Frontend |
|---|---|---|---|---|
| GET | `/api/v1/hr/overtime-requests` | Overtime requests (HR in scope, own, or direct reports) | *scope=mine: own; else hr.overtime:view/approve or hr.approvals:act* | ✅ |
| POST | `/api/v1/hr/overtime-requests` | submit overtime | hr.self:submit-requests or hr.leave:apply-on-behalf | ✅ |
| GET | `/api/v1/hr/overtime-requests/{request_id}` | get overtime | *HR in scope, own, manager, or current workflow step approver* | ✅ |
| POST | `/api/v1/hr/overtime-requests/{request_id}/decision` | decide overtime | hr.overtime:approve or hr.approvals:act | ✅ |
| GET | `/api/v1/hr/permission-requests` | Permission requests (HR in scope, own, or direct reports) | *scope=mine: own; else …permission-requests:view/approve or hr.approvals:act* | ✅ |
| POST | `/api/v1/hr/permission-requests` | submit permission | hr.self:submit-requests or hr.leave:apply-on-behalf | ✅ |
| GET | `/api/v1/hr/permission-requests/{request_id}` | get permission | *HR in scope, own, or reporting manager* | ✅ |
| POST | `/api/v1/hr/permission-requests/{request_id}/decision` | decide permission | hr.permission-requests:approve or hr.approvals:act | ✅ |

## Totals

- Implemented endpoints: **134** (including 2 health checks).
- Called by the current frontend: **90**.
- Additions not called by the frontend: HR setup, device ingestion and setup, period locks, leave setup, attachment download, notification queue, import helpers.
- Not yet built (HRMS-owned, called by the frontend): 54 endpoints for payroll (30), performance (15), reports (5) and the HR workspace (4). See `PENDING_DEPENDENCIES.md` and `API_MAPPING.md`.
