# Module 2 (Employees): Decisions

Recorded 2026-11-03, before implementation, from the owner's instructions:

1. Use the recommendations where they follow the frontend contracts and the security requirements.
2. Bank account information is encrypted at rest, and access to it is restricted.
3. The employee picker follows the frontend contract, including an empty search, within the caller's permissions.
4. Employee visibility is restricted by role and organizational scope.
5. HR policy values and business rules needing HR confirmation stay configurable and are marked pending.

**Status key:**
- **Decided:** a technical or security decision, implemented as written.
- **Implemented, pending HR:** built as the contract proposes; HR or management must confirm it, and it can change without code changes where noted.
- **Pending HR:** not built as a rule. Only the configurable switch exists, and it is off.

## The 12 questions

| # | Question | Decision | Status |
|---|---|---|---|
| Q1 | May the edit form (PATCH) change the status? | Yes, but only when the caller holds **both** `hr.employees:edit` and `hr.employees:change-status`. Otherwise 403. The change follows the same transition rules and writes the same history entry as the dedicated endpoint. The frontend form keeps working unchanged. (Contract D13/D17) | Decided |
| Q2 | Encrypt bank account information? | **Yes.** The value of every payroll field marked `sensitive` (template: `bankAccountNumber`) is encrypted with Fernet (AES-128-CBC + HMAC-SHA256, from the existing `cryptography` package). Keys come from `PAYROLL_ENCRYPTION_KEYS`; the first key encrypts and older keys still decrypt, for rotation. The service refuses to start in production without a key. **Access:** only `hr.employees:view-sensitive`; values are always masked to the last 4 characters, even for permitted users; never logged, never in history or audit values; write-only (an omitted key keeps its value). If a field is switched to or from sensitive, its stored values are re-encrypted or decrypted in the same transaction. | Decided |
| Q3 | Is employee email unique? | Implemented as the contract proposes: unique when present, ignoring case. The rule is one database index, so it can be removed by a migration if HR says otherwise. (D14) | Implemented, pending HR |
| Q4 | Is the attendance ID unique company-wide or per device? | Implemented as unique company-wide (the contract says "unique (device mapping)"). Per-device mapping comes with the attendance device module. (D14) | Implemented, pending HR |
| Q5 | Should the picker exclude employees who have left? | Excluded, as the contract proposes. **Which statuses count as "left" is configurable**: new status setting `employmentEnded`. The template sets it only on `exited`, marked pending. The same setting drives employee counts, the department-head check and the deactivation check. (B4) | Implemented, pending HR |
| Q6 | Picker with an empty search? | **Follows the contract (owner decision 3):** an empty `q` returns the first `limit` employees, with `limit` 1–20, default 10. Results are always limited to the caller's permissions and organizational scope (Q12), and contain only `id`, `employeeCode`, `fullName`, `department`. | Decided |
| Q7 | Limits on back-dating and future-dating a status change? | Only the contract rule is enforced: not before the joining date. No other limit exists until HR sets one; any limit will be a configurable value, not code. A status change takes effect on the record when it is recorded; the effective date is stored with it. Whether future-dated changes should wait until their date is an HR question. (D18) | Pending HR |
| Q8 | Is a reason mandatory for some transitions? | Configurable per target status: new status setting `reasonRequired`, **off for every status** until HR decides. When on, the status-change endpoint requires a reason. (D18) | Pending HR |
| Q9 | Should confirming from probation set the confirmation date automatically? | No automatic change. HR enters the confirmation date in the form. (D18 "proposal") | Pending HR |
| Q10 | Mandatory fields beyond the contract? | Only the contract's required fields are required: employee code, first name, joining date, department, designation, employment type and status. No statutory fields (PAN, Aadhaar, UAN …) are built until HR and Legal approve them. Payroll fields follow their configured `required` flag. (R1, D4) | Pending HR |
| Q11 | Employee code: entered or generated? | Entered by HR, as the frontend form does. Checked as in the contract: required, ≤ 30 characters, no spaces, unique ignoring case. No format or generation rule until HR decides. (R2, D5) | Pending HR (format) |
| Q12 | Organizational scope of employee visibility | **Role-based scopes (owner decision 4):** see below. No role has a scope until HR or management assigns one, so nobody sees employee records by default. | Decided (mechanism); pending management (assignments) |

## Q12 in detail: who sees which employees

Two checks apply to every employee endpoint:

1. **Permission.** The caller must hold the endpoint's permission (for example `hr.employees:view`).
2. **Organizational scope.** The records the caller can reach depend on the scopes assigned to their roles.
   - The `roles` claim of the Identity token is matched against scope assignments in HRMS.
   - Assignments are maintained through `/hr/setup/employee-access-scopes` (`hr.settings:manage`) and are audited.
   - A caller with several roles gets the union of their scopes.

| Scope type | Employees visible |
|---|---|
| `all` | Every employee |
| `departments` | Employees in the listed departments (the department IDs are part of the assignment) |
| `headed_departments` | Employees in the departments the caller heads (`department.head`) |
| `reporting_tree` | The caller's direct and indirect reports |
| `own_record` | The caller's own employee record |

- **No assignment:** a role with no assignment adds no access. There are no built-in defaults, and the `*` permission does not bypass scope.
- **Outside scope:** a record outside the caller's scope returns **404**, as if it did not exist (A4).
- **Applies to:**
  - the directory, the record, history and the picker;
  - edits and status changes;
  - reporting lines.
- **No moving records out of scope:** a create or edit may not place a record outside the caller's scope. For example, a department-scoped HR user cannot add someone to another department.
- **Caller's own record:** the token's `employeeId` claim links the caller to their record. It is used for `headed_departments`, `reporting_tree`, `own_record` and the self-service department list.

**Pending management:** which role gets which scope. The template sets none.

## Other rules confirmed from the contract

| Rule | Source |
|---|---|
| Contact fields (`mobile`, `email`, `address`, `emergencyContact`) are null without `hr.employees:view-contact`, with `restricted.contact = true`; omitted on PATCH means unchanged | B4 |
| `payroll` is null without `hr.employees:view-sensitive`, with `restricted.payroll = true` | B4 |
| History lists section names only, never values | B4 |
| A manager cannot be the employee or one of their reports (`managerId` / `employment.reportingManagerId`) | G4 |
| A department head must be an active employee, meaning a status not marked `employmentEnded` | G4 |
| A department or designation with active employees cannot be deactivated (field `active`) | G4 |
| No delete endpoint; leaving is a status change | B4 |
| Validation rules and messages are the frontend form's (`employees/schemas.ts`); the server re-checks them | B4 |

## Still requiring HR or management confirmation

These are added to `HR_CONFIRMATION_PENDING.md`.

| # | Item | Who |
|---|---|---|
| 21 | Which roles get which organizational scope (Q12) | Management + HR |
| 22 | Which statuses mean employment has ended (`employmentEnded`; template: `exited`) (Q5) | HR |
| 23 | Which status changes need a reason (`reasonRequired`; all off) (Q8) | HR |
| 24 | Back-dating and future-dating limits for status changes; whether future-dated changes wait until their date (Q7) | HR |
| 25 | Whether confirming from probation sets the confirmation date automatically (Q9) | HR |
| 26 | Employee email unique (implemented) (Q3) | HR |
| 27 | Attendance ID unique company-wide (implemented) (Q4) | HR + IT |
| 28 | Approved employee fields: mandatory, statutory, bank (Q10, R1) | HR + Legal |
| 29 | Employee code format or generation (Q11, R2) | HR |
| 30 | Company time zone used for "today" (the date of birth check, and the default effective date of a manager change made by the form). The `COMPANY_TIME_ZONE` setting must match Platform's company settings. | Platform owner |
| 31 | Who holds `hr.employees:view-sensitive` and therefore sees masked bank details | Management |
