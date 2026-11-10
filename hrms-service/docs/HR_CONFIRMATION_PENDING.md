# Values Pending HR Confirmation

Items 1–20: Module 1 setup template. Items 21–31: Module 2 (see `MODULE_2_DECISIONS.md`).
Items 32–39: Module 3 (see `MODULE_3_DECISIONS.md`). Items 40–44: Module 4 (see `MODULE_4_DECISIONS.md`). Items 45–73: Module 5 (see `MODULE_5_DECISIONS.md`).

Nothing in this list is company policy yet. Each value was copied from the frontend's former sample
data (or its form limits) only so the system can be tried out. Every item stays configurable through
the API shown; none is fixed in code. HR confirms or replaces each item, then signs the setup file
(`hr_confirmed: true`, `hr_confirmed_by`, `hr_confirmed_on`). Until then the loader refuses to load
the file into production.

| # | Item | Current template value | Where HR changes it | Status |
|---|---|---|---|---|
| 1 | Departments (15) | PRD … SLS (sample list) | `POST/PUT /admin/departments` | Pending HR confirmation |
| 2 | Designations (11) | TRN … HOD; no department limits | `POST/PUT /admin/designations` | Pending HR confirmation |
| 3 | Employment types | PERM, CONT, APPR, TEMP | `/hr/setup/employment-types` | Pending HR confirmation |
| 4 | Work locations | PLANT1, PLANT2, HO, SITE | `/hr/setup/work-locations` | Pending HR confirmation |
| 5 | Employee statuses: which may be used when creating an employee | on_probation, active | `/hr/setup/employee-statuses` (`allowedOnCreate`) | Pending HR confirmation |
| 6 | Employee status transitions | on_probation → active / on_notice / exited; active → on_notice / suspended / exited; on_notice → active / exited; suspended → active / exited; exited → none | `/hr/setup/employee-statuses` (`transitions`) | Pending HR confirmation |
| 7 | Attendance policy names | AP-STAFF, AP-SHOP (names only; rules come with the HR Policies module) | `/hr/setup/attendance-policies` | Pending HR confirmation |
| 8 | Overtime policy names | OT-NONE, OT-SHOP (names only) | `/hr/setup/overtime-policies` | Pending HR confirmation |
| 9 | Shifts and times | GEN 09:00–17:30; A 06:00–14:00; B 14:00–22:00; C 22:00–06:00 | `POST/PUT /hr/shifts` | Pending HR confirmation |
| 10 | Shift break minutes | 30 for every shift | `PUT /hr/shifts/{id}` (`breakMinutes`) | Pending HR confirmation |
| 11 | Shift grace minutes | GEN 10; A, B, C 5 | `PUT /hr/shifts/{id}` (`graceMinutes`) | Pending HR confirmation |
| 12 | Shift working days | Monday–Saturday for every shift | `PUT /hr/shifts/{id}` (`workingDays`) | Pending HR confirmation |
| 13 | Shift-to-department links | GEN: office departments; A/B/C: PRD, WND, COR, ASM, PNT, DSP | `PUT /hr/shifts/{id}` (`departmentIds`) | Pending HR confirmation |
| 14 | Document categories | DC-ID, DC-EDU, DC-EMP, DC-BANK, DC-CO | `/hr/setup/document-categories` | Pending HR confirmation |
| 15 | Required documents | Identity proof, Address proof, Educational certificate, Offer letter, Appointment letter, Bank account proof | `/hr/setup/document-types` (`required`) | Pending HR confirmation |
| 16 | Documents needing an expiry date | Passport, Medical fitness certificate | `/hr/setup/document-types` (`expiryRequired`) | Pending HR confirmation |
| 17 | Allowed file types | PDF/JPG/JPEG/PNG, or PDF only for letters | `/hr/setup/document-types` (`allowedExtensions`) | Pending HR confirmation |
| 18 | File size limits | 2 MB (identity, bank) or 5 MB (others) | `/hr/setup/document-types` (`maxSizeBytes`) | Pending HR confirmation |
| 19 | Payroll fields on the employee form | payrollGroup, paymentMode, bankAccountNumber (sensitive), bankIfsc; all optional | `/hr/setup/payroll-fields` | Pending Finance/HR confirmation |
| 20 | Payroll field formats | account 6–18 digits; IFSC `^[A-Z]{4}0[A-Z0-9]{6}$` | `/hr/setup/payroll-fields` (`pattern`) | Pending Finance/HR confirmation |
| 21 | Which Identity roles get which organizational scope (who sees which employees) | **none assigned** — nobody sees employee records until assigned | `/hr/setup/employee-access-scopes` | Pending management + HR |
| 22 | Statuses meaning employment has ended (excluded from pickers, counts, head check) | `exited` only | `/hr/setup/employee-statuses` (`employmentEnded`) | Pending HR confirmation |
| 23 | Status changes that need a reason | none | `/hr/setup/employee-statuses` (`reasonRequired`) | Pending HR confirmation |
| 24 | Back-/future-dating limits for status changes; whether future-dated changes wait for their date | no limit beyond "not before joining date"; applied when recorded | not configurable yet (becomes an HR policy value when decided) | Pending HR |
| 25 | Confirming from probation sets the confirmation date automatically | no (HR enters it) | — | Pending HR |
| 26 | Employee email unique | yes, ignoring case (contract proposal) | database index (migration) | Pending HR confirmation |
| 27 | Attendance ID unique company-wide | yes (contract) | database index (migration) | Pending HR + IT |
| 28 | Approved employee fields: mandatory, statutory, bank | only the contract's required fields; no statutory fields | — | Pending HR + Legal |
| 29 | Employee code format or generation | entered by HR; ≤ 30, no spaces, unique | — | Pending HR |
| 30 | Company time zone for "today" | `UTC` | `COMPANY_TIME_ZONE` setting | Pending Platform owner |
| 31 | Who holds `hr.employees:view-sensitive` (sees masked bank details) | — | Identity roles | Pending management |
| 32 | Which document types are required, and for whom | required flag per type, applies to all tracked employees | `/hr/setup/document-types` (`required`) | Pending HR (D23) |
| 33 | "Expiring soon" window | 30 days (contract example) | `/hr/setup/document-settings` | Pending HR |
| 34 | A copy awaiting verification counts as completed; exited employees excluded from completion | yes / yes (contract proposal) | status setting `employmentEnded` | Pending HR (D23) |
| 35 | Verification workflow: who verifies/rejects, permission, comment on rejection, endpoint | not built; every copy stays "pending" | — | Pending HR + management (D24) |
| 36 | Document retention and deletion | no delete endpoint | — | Pending HR + Legal (R4) |
| 37 | File types and size limits per document type | template values; only .pdf .jpg .jpeg .png can be verified | `/hr/setup/document-types` | Pending HR + IT |
| 38 | Malware scanner hosting, signature updates, timeout | ClamAV `clamd`, 30 s timeout; required in production | `MALWARE_SCANNER`, `CLAMAV_*` | Pending IT |
| 39 | Custody and backup of `DOCUMENT_ENCRYPTION_KEYS` (kept apart from data backups) | — | secret store | Pending IT + management |
| 40 | Import columns; whether more fields should be importable | contract's proposed 15 columns (R5) | code change when decided | Pending HR |
| 41 | Import limits | 2,000 rows, 5 MB (contract proposal) | `IMPORT_MAX_ROWS`, `IMPORT_MAX_FILE_BYTES` | Pending HR + IT |
| 42 | Missing reporting manager on import | warning, row imported (contract example) | — | Pending HR |
| 43 | Who may see an import job | the owner only | — | Pending management |
| 44 | Accepted import date formats | YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, DD.MM.YYYY, Excel dates | — | Pending HR |
| 45 | Order of day statuses (on leave → holiday → weekly off → not started → absent → missing punch → half day → late → present) | as listed | code (`calculator.py`) | Pending HR (A1) |
| 46 | Weekly offs = days not in the assigned shift's working days | as listed | shift setup | Pending HR (A2) |
| 47 | Deduct the shift break from worked time | off (empty) | `/admin/policies/attendance` `deductBreak` | Pending HR (A3) |
| 48 | Late and early-exit minutes measured from shift start + grace / shift end; grace = the shift's own grace | as listed | shift `graceMinutes` | Pending HR (A4) |
| 49 | Half day below worked minutes | empty (not applied) | `halfDayBelowMinutes` | Pending HR (A5) |
| 50 | Absent below worked minutes | empty (not applied) | `absentBelowMinutes` | Pending HR (A6) |
| 51 | Overtime: on/off, eligibility (employees with an overtime policy assigned), minimum, rounding, daily cap | off / empty | `/admin/policies/overtime` | Pending HR (A7) |
| 52 | Missing punch on the current day is not an exception before the shift ends | as listed | — | Pending HR (E-Q1) |
| 53 | Overnight punches belong to the shift's start date (nearest-shift rule after midnight) | as listed | — | Pending HR (E-Q2) |
| 54 | Calendar/monthly counts: present = present + late + missing punch; half days counted separately; leave days 0 until the leave module | as listed | — | Pending HR (H-Q1) |
| 55 | One company-wide rule set (named attendance policies are labels only) | as listed | — | Pending HR (A11) |
| 56 | No attendance days after the effective exit date | as listed | status setting `employmentEnded` | Pending HR (A12) |
| 57 | How far back a correction may be requested | empty (no limit) | `correctionWindowDays` | Pending HR (C1) |
| 58 | Correction reason 10–500 characters (frontend form rule); requested in-time on the date, out-time on the date or next day | as listed | — | Confirm |
| 59 | Default correction workflow: reporting manager (required step); no escalation until fallback + hours are set | template | `/admin/workflows` | Pending HR |
| 60 | Workflow approvers need `hr.approvals:act`; HR with `…corrections:approve` may decide at any step and completes the request | as listed | — | Confirm (C2) |
| 61 | Back-dated shift assignments allowed, and how far back | off / empty | `/admin/policies/shifts` | Pending HR (O1) |
| 62 | New permission `hr.shifts:assign-backdated` must be added to the Identity permission catalogue and granted | — | Identity service | Pending Identity owner |
| 63 | Frontend: the shift-assign dialog has no reason field, so back-dating is API-only until the frontend adds one | — | frontend | Pending frontend team |
| 64 | Finalized payroll periods lock attendance; recorded by HR (`hr.payroll:approve`) until the payroll module creates locks | — | `/hr/setup/attendance-period-locks` | Pending HR + Finance (C5) |
| 65 | Device vendor, push or pull, connector; when a device counts as "offline" (currently only not_connected / error / online) | — | — | Pending IT (D1) |
| 66 | Mobile-app attendance (refused until approved) | off | — | Pending management + IT + Legal (D2) |
| 67 | Duplicate punch window | empty (only exact resends) | `duplicateWindowSeconds` | Pending IT + HR (D3) |
| 68 | Delayed-sync threshold | empty (never flagged) | `delayedSyncMinutes` | Pending IT + HR (D4) |
| 69 | Device clock tolerance for future timestamps | 5 minutes (technical) | code | Pending IT (D5) |
| 70 | Punches with unknown attendance IDs are stored as rejected and visible | as listed | — | Confirm (D6) |
| 71 | Summary "most serious first": missing punch → absent → half day → late | as listed | code | Pending HR (O2) |
| 72 | Retention of raw punches | kept indefinitely | — | Pending HR + Legal (O3) |
| 73 | Leave and holidays in attendance (`on_leave`, `holiday`) | produced since Module 6 (see 96) | — | Resolved by Module 6 |
| 74 | Leave categories beyond `paid` / `balanceTracked` | none (contract has none) | — | Pending HR (L1) |
| 75 | Leave types (codes, names, paid, half-day, attachment rule) | **none pre-filled** | `/hr/setup/leave-types` | Pending HR (L2) |
| 76 | Entitlement per type: accrual method and days | **none pre-filled** | `/hr/setup/leave-policies` | Pending HR (L3) |
| 77 | Carry-forward allowed and maximum per type | none | leave policy | Pending HR (L4) |
| 78 | Policy applicability criteria | employment types and/or departments; empty = everyone | leave policy | Pending HR (L5) |
| 79 | Leave year | empty = calendar year | `leaveYearStartMonth` (G6 `leave`) | Pending HR (L6) |
| 80 | Accrual timing | `annual`: once per leave year; `monthly`: once per month (worker, daily run) | leave policy | Pending HR (L7) |
| 81 | Proration for joiners and leavers | **not applied**: a joiner gets the full credit of the period | — | Pending HR (L8) |
| 82 | Carry-forward date and lapse | at the start of the new leave year; capped at `maxDays` (empty = no cap); the rest lapses | leave policy | Pending HR (L9) |
| 83 | Opening balances at go-live | entered as adjustments with a reason | `/hr/setup/leave-adjustments` | Pending HR (L10) |
| 84 | Encashment | not built (not in the frontend) | — | Pending HR + Finance (L11) |
| 85 | Applications beyond the balance | **blocked** (owner decision 3) unless HR switches on | `allowNegativeBalance` | Decided; value pending HR |
| 86 | Weekly offs and holidays inside a leave range | not charged | `countOffsWithinLeave` | Pending HR |
| 87 | Minimum notice / back-dating window | empty = not applied | `minimumNoticeDays`, `backdatedWindowDays` | Pending HR (L13) |
| 88 | Attachment file types and size | .pdf .jpg .jpeg .png, 5 MB, at most 5 files (frontend constant) | `LEAVE_ATTACHMENT_MAX_BYTES`, `LEAVE_MAX_ATTACHMENTS` | Pending HR + IT (L14) |
| 89 | `attachmentAfterDays`: block or warn | warning only | code | Pending HR (L15) |
| 90 | Default leave workflow | **none pre-filled**; without an active workflow the reporting manager decides (contract E) | `/hr/leave/approval-workflows` | Pending HR (L16) |
| 91 | Escalation delay, reminder and recipient | none; set per workflow | workflow | Pending HR (L17) |
| 92 | Company working days (for `working_days` and employees without a shift) | **empty**: `working_days` refused; weekly offs not excluded for employees without a shift (warning) | `COMPANY_WORKING_DAYS` | Pending Platform + HR (L18) |
| 93 | Cancelling or shortening started leave; partial cancellation | not allowed (409) | code | Pending HR (L21) |
| 94 | Holiday list per year | **none pre-filled** | `/hr/setup/holidays` | Pending HR (L22) |
| 95 | Optional or restricted holidays | not built | — | Pending HR (L24) |
| 96 | Half-day leave in attendance | day shows `half_day` with the leave type; no lateness for a first-half leave, no early exit for a second-half leave, no absence | code | Pending HR (L25, H-Q1) |
| 97 | A holiday on a weekly off | shown as `holiday` | code | Pending HR |
| 98 | Leave reports (contract F) | in the Reports module | — | Pending owner (L27) |
| 99 | Notification delivery and role recipients | queued until `PLATFORM_NOTIFICATIONS_URL` + token are set; roles sent as `roleCodes` | settings | Pending Platform (L28) |
| 100 | Limits on permission minutes and overtime | none beyond the frontend form rules | — | Pending HR (L30) |
| 101 | Permission request approval | HR with `hr.permission-requests:approve`, or the reporting manager with `hr.approvals:act` (contract E) | code | Pending HR (L31) |
| 102 | Overtime approval | the published G5 `overtime` workflow; otherwise contract E | `/admin/workflows` | Pending HR (L31) |
| 103 | Leave dashboard lists | empty = no low-balance or upcoming list | `lowBalanceThreshold`, `upcomingWindowDays` | Pending HR (L32) |
| 104 | Approver options for workflows | roles and users already used in HRMS configuration | — | Pending Identity API |
| 105 | Pending requests of an old leave year at year end | the year is closed with the remaining approved balance; a later approval in that year can make it negative | code | Pending HR |
| 106 | Salary components, rates, ceilings, slabs (PF, ESI, professional tax and others), structures and salaries | none: nothing is pre-filled | `/hr/setup/salary-components`, `/salary-structures`, `/employee-salaries` | Pending HR/Finance (Module 7) |
| 107 | Days in a pay period (calendar, working or fixed days) | empty: payroll cannot be calculated | `/admin/policies/payroll` | Pending HR (Module 7) |
| 108 | Fixed-days basis for a joiner or leaver | the fixed days times the share of calendar days employed | code | Pending HR (Module 7) |
| 109 | Absences and half days without leave as loss of pay | empty (off): only unpaid leave is loss of pay | `/admin/policies/payroll` | Pending HR (Module 7) |
| 110 | Rounding of pay lines | each line to 2 decimals, half up | code | Pending Finance (Module 7) |
| 111 | Large change in net pay flag | empty: never flagged | `/admin/policies/payroll` | Pending HR (Module 7) |
| 112 | Submitter may approve the payroll | empty (off): a different person must approve | `/admin/policies/payroll` | Pending HR (Module 7) |
| 113 | A salary revision inside a period | the record in force on the employee's last day in the period is used for the whole period (no split) | code | Pending HR/Finance (Module 7) |
| 114 | Which policy values apply to a period | the payroll policy in force on the day of validation and calculation | code | Pending HR (Module 7) |
| 115 | Income-tax (TDS) projection | not built: only slab components on monthly pay | — | Pending Finance (Module 7) |
| 116 | Payroll frequencies other than monthly | recorded on configurations, not calculated | — | Pending HR (Module 7) |
| 117 | Payslip layout and heading | plain one-page PDF; heading from `PAYSLIP_COMPANY_NAME` (empty: "Payslip") | `.env` | Pending HR/Platform (Module 7) |
| 118 | Who takes part in an appraisal cycle | everyone joined by the period end and not in an "employment ended" status, when the cycle leaves draft; no tenure or category rule | code | Pending HR (Module 8) |
| 119 | Who reviews | the reporting manager, refreshed when the cycle enters manager review for reviews not yet started; none when the employee has no manager | Reporting lines | Pending HR (Module 8) |
| 120 | Employee self-assessment | not built (no self-service screen, E-Q7) | — | Pending HR/Product (Module 8) |
| 121 | Review status and assessment window | follows the cycle phases; the manager assesses only during manager review | code | Pending HR (Module 8) |
| 122 | When goals may be added or updated | any time before the cycle closes | code | Pending HR (Module 8) |
| 123 | Recommendation options of a cycle | the active options when the cycle is created, kept with the cycle | `/hr/setup/performance-recommendations` | Pending HR (Module 8) |
| 124 | Rating scales, levels, competencies and recommendation options | none: nothing is pre-filled; levels fixed once a cycle uses the scale | `/hr/setup/rating-scales`, `/competencies` | Pending HR (Module 8) |
| 125 | Attendance rate definition (reports, dashboard) | present ÷ (present + absent), completed days; late and missing punch count as present (contract F-Q1) | code | Pending HR (Module 9) |
| 126 | Leave utilisation definition | used ÷ (allocated + carried forward), leave types with a balance, leave year (F-Q1) | code | Pending HR (Module 9) |
| 127 | Payroll cost definition | gross earnings + employer contributions of a calculated period (F-Q1) | code | Pending Finance (Module 9) |
| 128 | Large report exports | synchronous; no background job (F-Q3) | code | Pending IT (Module 9) |
| 129 | Which statuses count as "active" employees (workspace) | none: the metric is unavailable until set | `.env` `WORKSPACE_ACTIVE_STATUS_CODES` | Pending HR (Module 10, D20) |
| 130 | HR task rules (incomplete record, onboarding documents, probation review): items checked, windows, priorities, due dates | the contract B7 proposals, as built | code | Pending HR (Module 10, D19) |
| 131 | Events shown on the workspace | joinings and work anniversaries; no birthdays | code | Pending HR (Module 10, D20) |

## Form limits taken from the frontend (not HR policy)

The shift service re-checks the same limits as the frontend shift form
(`src/features/hr/attendance/schemas.ts`), so the two never disagree. They are input-safety bounds,
not entitlements; if HR needs different bounds, the frontend form and the service change together.

| Limit | Value |
|---|---|
| Longest shift | 16 hours |
| Break | 0–180 minutes, and shorter than the shift |
| Grace period | 0–120 minutes |
| Shift code / name | ≤ 10 letters, digits, hyphens / 2–60 characters |

## Already approved

| Decision | Approved |
|---|---|
| Employee status codes and payroll field keys cannot be renamed once created | 2026-11-03 |
| Bank account information encrypted at rest, restricted access (Module 2 decision Q2) | 2026-11-03 |
| Employee picker follows the contract, including empty search, within permissions (Q6) | 2026-11-03 |
| Employee visibility restricted by role and organizational scope (Q12) | 2026-11-03 |
| Attendance corrections use a configurable approval workflow (default: reporting manager; HR oversight; no self-approval) | 2026-11-03 |
| Back-dated shift assignments off by default; allowed only with setting + permission + reason; locked periods protected | 2026-11-03 |
| Leave requests keep their routing; workflow changes affect only new requests (Module 6 decision 1) | 2026-11-04 |
| After escalation the original approver, the recipient and HR may decide; the first valid decision wins (decision 2) | 2026-11-04 |
| Applications beyond the balance blocked unless HR enables negative balances (decision 3) | 2026-11-04 |
| Holidays company-wide or per work location (decision 4) | 2026-11-04 |
| Complete, append-only audit history for leave (decision 5) | 2026-11-04 |
