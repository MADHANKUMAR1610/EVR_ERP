# Module 2 Analysis: Employees

**Status: approved and implemented (2026-11-03).** The final answers to Q1–Q12 are in
[`MODULE_2_DECISIONS.md`](MODULE_2_DECISIONS.md); where they differ from this analysis (Q6: empty
picker search now follows the contract; Q12: role-based scopes), the decisions document wins.

Sources:
- the frontend contract `HRMS_API_CONTRACTS.md` (B4 employees, G4 reporting lines, A4 authorization, Part D open questions);
- the frontend types in `src/features/hr/employees/api/employees.service.ts` and `src/features/admin/api/admin.service.ts`;
- the screens that call these endpoints.

Every rule below is either taken from those sources (with its reference) or listed as a question.
None is invented.

## 1. Scope

**In scope:** 9 frontend endpoints.

| # | Method | Path | Frontend use |
|---|---|---|---|
| 1 | GET | `/hr/employees` | Employee Directory (paged) |
| 2 | GET | `/hr/employees/{id}` | Employee profile, edit form |
| 3 | POST | `/hr/employees` | Add employee |
| 4 | PATCH | `/hr/employees/{id}` | Edit employee |
| 5 | POST | `/hr/employees/{id}/status-changes` | Status change dialog (directory, profile, My Tasks) |
| 6 | GET | `/hr/employees/lookup` | Employee picker in 11 dialogs |
| 7 | GET | `/hr/employees/{id}/history` | Profile history tab |
| 8 | GET | `/admin/reporting-lines` | Administration → Organization → Reporting lines |
| 9 | POST | `/admin/reporting-lines/{employeeId}` | Change manager dialog |

**Module 1 items this module completes:**
- the department head (foreign key, "must be an active employee" per G4);
- `employeeCount` on departments and designations;
- the rule that a department or designation with active employees cannot be deactivated (G4);
- self-service departments returning the caller's own department.

**Out of scope here:**
- documents (module 3) and import (module 4);
- shift assignments (attendance module);
- HR workspace counts (B7);
- My Profile: the frontend marks it phase 7, and no page or endpoint exists yet;
- employee photos: `photoUrl` stays `null` until D16 is decided.

## 2. Database design (migration 0004)

Every table has the audit columns. Every editable table also has a `version` column.

| Table | Purpose | Notes |
|---|---|---|
| `employee` | One row per employee | Columns:<br>• `employee_code` (unique, case-insensitive)<br>• names, date of birth, joining date<br>• foreign keys to department, designation, employment type, work location, shift, attendance policy and overtime policy<br>• `status_code` (FK to `employee_status.code`, stable by migration 0003)<br>• `reporting_manager_id` (self-FK)<br>• probation fields, `attendance_id` |
| `employee_contact` | Mobile, email, address, emergency contact | A separate table, so contact data is read only when the caller holds `hr.employees:view-contact` and is never joined into list queries by accident |
| `employee_payroll_value` | One row per (employee, payroll field key) | Sensitive values encrypted at rest (see Q2); only the masked form ever leaves the service |
| `employee_history` | Append-only history the profile shows | `action`, `summary`, `changes` (section names only), `from_status`, `to_status`, `effective_date`, `comment`, actor id and name. A trigger blocks update and delete, like `audit_log` |
| `employee_reporting_line` | Effective-dated manager history | `employee_id`, `manager_id`, `effective_from`, `reason`. The current manager is copied to `employee.reporting_manager_id` for fast reads |
| `department.head_employee_id` | Add the foreign key to `employee` | The column already exists (module 1) |

**Indexes:**
- directory sort and filter columns;
- trigram or `lower()` indexes for code and name search;
- `attendance_id` unique when present (see Q4).

## 3. Endpoints, permissions and scoping

### 3.1 Permissions

| Endpoint | Permission | Source |
|---|---|---|
| GET `/hr/employees` | `hr.employees:view` | B4 |
| GET `/hr/employees/{id}` | `hr.employees:view` | B4 |
| POST `/hr/employees` | `hr.employees:create`, plus `hr.employees:view-sensitive` if `payroll` is sent | B4 |
| PATCH `/hr/employees/{id}` | `hr.employees:edit`. If `statusCode` changes, see Q1. Plus `hr.employees:view-sensitive` if `payroll` is sent | B4, D13, D17 |
| POST `.../status-changes` | `hr.employees:change-status` | B4 |
| GET `/hr/employees/lookup` | The permissions of the picker screens (3.3) | B4, extended (see Q6) |
| GET `.../history` | `hr.employees:view` | B4 |
| GET `/admin/reporting-lines` | `admin:organization.view` **and** `hr.employees:view` | G4 |
| POST `/admin/reporting-lines/{id}` | `admin:organization.manage` | G4 |

### 3.2 Field-level rules (from B4 "backend MUST enforce")

**Contact fields:**
- Without `hr.employees:view-contact`, `email` and `mobile` are `null` in the directory.
- On the record, `mobile`, `email`, `address` and `emergencyContact` are `null`, and `restricted.contact = true`.
- On PATCH, omitted contact keys mean "unchanged", so a caller who cannot see contacts can never wipe them.

**Payroll values:**
- Without `hr.employees:view-sensitive`: `payroll: null` and `restricted.payroll = true`.
- Sensitive values are always masked to the last 4 characters (`••••4002`), even for permitted users.
- Sensitive values are write-only: an omitted key keeps its value, and `""` clears a non-sensitive key.

**History and audit:**
- History `changes` lists section names only ("Employment details"), never values.
- The audit log masks sensitive fields (existing `MASKED_FIELDS`, extended with contact fields).

### 3.3 Record-level rules and the employee lookup (your point 1)

The lookup is what approver pickers, admin dialogs and HR request forms use. It is **not** a directory.

**What it returns:**
- Only `{ id, employeeCode, fullName, department }`: the 4 fields in the frontend `EmployeeLookupItem`.
- Never contact details, status, manager, dates or payroll data.

**Size limits:**
- At most 20 results per call (`limit` 1–20, as the contract says).
- No paging and no total count, so the list cannot be walked page by page.

**Who may call it:** only holders of a permission whose screen contains a picker. These are the screens found in the frontend:

| Screen (picker host) | Permission |
|---|---|
| Employee form (reporting manager) | `hr.employees:create` / `:edit` |
| Employee Documents (upload for an employee) | `hr.documents:upload` |
| Leave, permission and overtime "apply on behalf" | `hr.leave:apply-on-behalf` |
| Shift assignment | `hr.shifts:assign` |
| Payroll assignment | `hr.payroll-assignments:manage` |
| Goals, development plans | `hr.goals:manage`, `hr.development-plans:manage` |
| Admin Organization (department head, change manager) | `admin:organization.manage` |
| Admin Users (link a login to an employee) | `admin:users.manage` |
| (contract) directory users | `hr.employees:view`, `hr.documents:view` |

**Record scope:**
- Exited employees are excluded (contract proposal, see Q5).
- Self-service-only users get 403.
- An empty `q` returns nothing instead of "the first 20" (see Q6), so an unfiltered list is never served.

**Not found and denied access:**
- A record the caller may not see returns 404, not 403 (A4).
- Every refusal is audited.

**Self-service departments:** a caller with only self-service permissions gets the department on their own employee record (`employeeId` claim), or `[]` if the token has none.

## 4. Business rules

### 4.1 Rules taken from the contract

These are validated on create and update.
- **`employeeCode`:** required, ≤ 30 characters, no spaces, unique regardless of case.
- **Names:** first name required, ≤ 50 characters; middle and last name optional, ≤ 50 characters.
- **Date of birth:** optional; not in the future; before the joining date.
- **Phone and email:**
  - mobile and emergency phone: `+`, digits, spaces and `-`, with 7–15 digits;
  - email must be a valid address;
  - if any part of the emergency contact is given, its name and phone are required.
- **Joining date:** required.
- **Department, designation, employment type:** required; must exist; inactive items are refused for new values.
- **Status:**
  - on create, the status must allow creation (`allowedOnCreate`);
  - on update, it must stay the same or be one of the configured transitions. Otherwise 422 `INVALID_TRANSITION` on `employment.statusCode`.
- **Reporting manager:** must exist; cannot be the employee themself or one of their reports (G4).
- **Probation:** an end date is required when probation applies, and must be after the joining date. The confirmation date must be on or after the joining date.
- **Attendance ID:** ≤ 30 characters and unique.
- **Payroll values:** each one is checked against its configured definition (required, maximum length, pattern, options). Unknown keys are refused.
- **Updates:**
  - PATCH requires `version`; a mismatch returns 409 `STALE_VERSION`;
  - each update writes history entries, and a status change gets its own entry.
- **No delete endpoint:** leaving the company is a status change.
- **Status-change endpoint:**
  - `toStatus` must be one of the configured transitions;
  - `effectiveDate` must not be before the joining date;
  - `reason` is optional, ≤ 500 characters, and is stored as the history `comment`;
  - `version` is required.
- **Reporting line change:** a reason and effective date are required; the change is recorded in history with its effective date.

### 4.2 Rules waiting on a decision

None of these will be built until you answer.

| # | Question | Contract ref. | My recommendation |
|---|---|---|---|
| Q1 | May PATCH change the status (needing `edit` + `change-status`), or only the dedicated status-change endpoint? | D13, D17 | PATCH accepts a status change only with **both** permissions. It is recorded exactly like the dedicated endpoint. The frontend form keeps working. |
| Q2 | Encrypt sensitive payroll values (bank account) at rest? Needs a key in the environment (`PAYROLL_ENCRYPTION_KEY`), and a rotation procedure. | A4, R1 | Yes. Only the masked form is ever returned. |
| Q3 | Is employee email unique across employees? | D14 ("proposal") | Unique when present, case-insensitive. |
| Q4 | Is the attendance ID unique company-wide, or per device? | D14 | Company-wide. Device mapping arrives with the attendance module. |
| Q5 | Should the lookup exclude exited employees? | B4 ("proposal") | Yes, except the "include current value" case the picker never needs. |
| Q6 | Should an empty lookup `q` return results? The contract says "first `limit`". | B4, your point 1 | Return nothing for an empty `q`, and require at least 2 characters. **This differs from the contract**: an empty picker would show nothing until the user types. |
| Q7 | Status-change effective date: limits on back-dating and future-dating? | D18 | No limit beyond "not before joining date" until HR sets one. If HR wants limits, they become fields in HR policy, not code. |
| Q8 | Is a reason mandatory for some transitions (e.g. exited, suspended)? | D18 | Optional for all until HR decides. Can become a per-status setting (`reasonRequired`) in `/hr/setup/employee-statuses`. |
| Q9 | Should confirming from probation (`on_probation → active`) set `confirmationDate` automatically? | D18 ("proposal") | No automatic change. HR enters it in the form. |
| Q10 | Which employee fields are mandatory beyond the contract's list (statutory IDs, bank details)? Is last name required? | R1, D4 | Only the contract's required fields. Statutory fields are left out until HR and Legal approve them. |
| Q11 | Employee code: entered by HR (as the frontend form does) or generated? | R2, D5 | HR enters it; the backend checks it is unique. |
| Q12 | Directory record scope: does `hr.employees:view` see all employees, or only some departments, or only reports for managers? | A4 | All employees for `hr.employees:view`. Department or manager scoping can be added later as a separate permission. |

## 5. Tests planned

- **Field scoping:** for each of the 9 endpoints, the matrix of permission × contact/payroll fields, including that masked values never reveal more than the last 4 characters.
- **Lookup:** only 4 fields; at most 20 results; exited employees excluded; 403 for self-service-only users; every denial audited.
- **Validation:** every 422 rule in 4.1, with the contract's field paths.
- **Status transitions:** allowed and refused moves, `INVALID_TRANSITION`, and history entries.
- **Optimistic concurrency** on PATCH, status changes and reporting lines.
- **Reporting-line cycles:** a manager cannot be the employee or one of their reports. Plus effective-dated history.
- **Module 1 rules this module completes:**
  - department head;
  - `employeeCount`;
  - no deactivation while active employees remain;
  - self-service departments.
- **History:** append-only trigger, and no values in `changes`.
- **Migration 0004:** upgrade and downgrade, plus `alembic check`.
- **Contract check:** the script compares the schemas with `employees.service.ts` field for field.

## 6. Estimate and order of work

1. Migration 0004, models, repositories.
2. Read endpoints (directory, record, lookup, history) with the scoping rules.
3. Create and update with validation and history.
4. Status changes, reporting lines.
5. Module 1 completions, tests, docs, completion report, ZIP.

**Safe to begin once you approve:** Q1–Q12 (or tell me to use the recommendations), and the lookup design in 3.3.
