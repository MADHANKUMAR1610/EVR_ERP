# HRMS Service: Completion Reports

One section per phase or business module, newest first. Each report states what was built, how it
was verified, decisions taken, known gaps, and whether the next step is safe to begin.

---

## Module 10: HR workspace (2026-11-05)

Scope and design: `MODULE_10_DECISIONS.md`, recorded before implementation. It follows contract B7. Its task and metric rules are the contract's proposals (D19, D20) and are marked pending.

### What was built

**Frontend endpoints:** all 4 calls of `workspace.http.ts`. All are read-only, and there is no new table.

| Endpoint | Behaviour |
|---|---|
| `GET /hr/workspace/summary` | **Total:** employees in employment.<br>**Active:** the statuses named in `WORKSPACE_ACTIVE_STATUS_CODES`; unavailable while that is empty, never guessed.<br>**Present today:** from attendance.<br>**Pending approvals:** the caller's Approval Inbox total.<br>Each figure is gated and carries `unavailableReason` when missing. |
| `GET /hr/tasks` | Tasks derived on read:<br>• `employee_record_incomplete` (missing items are labels only);<br>• `onboarding_documents`;<br>• `probation_review_due`.<br>Each type is shown only to users who can do the work. Filters: type, priority and due. `counts` are unfiltered. Page size 1–100, because the dashboard asks for 1. |
| `GET /hr/activity` | Module 2 employee history, newest first, with the subject; organizational scope. |
| `GET /hr/upcoming-events` | Joinings and work anniversaries within 1–90 days; no birthdays. |

**One defect found by the new tests and fixed:** the task page was built without its `counts`.

### Verification

| Check | Result |
|---|---|
| Tests | **204 passed**: 202 earlier tests plus 2 new ones in `tests/test_workspace.py`. They cover the derived tasks and their priorities and due dates, task types by permission, counts and filters, metric gating, activity, events and scope. |
| Contract check | **141 shapes**, and **144 of 144 routes**, match the frontend. |
| Migration | no change; `alembic check` reports no drift. |
| API mapping | **144 of 144 HRMS endpoints implemented.** |

### Pending

Items 129–131 in `HR_CONFIRMATION_PENDING.md`:
- which statuses count as active;
- the task rules;
- which events are shown.

---

## Module 9: Reports (2026-11-05)

Scope and design: `MODULE_9_DECISIONS.md`, recorded before implementation. It follows contract Part F.

**Before starting:** Modules 1–8 are unchanged. Reports read their data through the existing calculations:
- attendance: `AttendanceData`;
- leave balances: `BalanceService`;
- documents: `DocumentComplianceService`;
- payroll results.

### What was built

**Frontend endpoints:** all 5 calls of `reports.http.ts`:
- the catalogue;
- run a report;
- export a report as CSV or XLSX;
- the dashboard;
- the activity list.

**All 25 report ids of the contract:**
- HR: 7;
- attendance: 7;
- leave: 5;
- payroll: 6.

**How reports run:**
- each report builds all its matching rows in the caller's organizational scope;
- the service then sorts, pages, totals and exports them, so a page, its totals and its export always agree;
- the columns are typed, and status cells carry their labels.

**Access:**
- the catalogue lists only the reports the caller may run;
- reports with payroll amounts need `hr.payroll:view-amounts`;
- each dashboard figure is gated by its module permission and carries `unavailableReason` when hidden.

**Database:** migration `0011` adds `report_activity`, an append-only table. It records runs of page 1 and every export; both are also written to the audit log.

### Verification

| Check | Result |
|---|---|
| Tests | **202 passed**: 199 earlier tests plus 3 new ones in `tests/test_reports.py`. They run all 25 reports on real employee, leave, attendance and payroll data. They also cover totals over every row, sorting, range limits, CSV and XLSX exports, activity, catalogue filtering, payroll-amount access, scope and the dashboard. |
| Contract check | **137 shapes**, and **140 of 140 routes**, match the frontend. |
| Migration | upgrade, `alembic check` with no drift, downgrade to `0010`, upgrade. |
| API mapping | 140 of 144 HRMS endpoints implemented. Left: HR workspace 4. |

### Pending

Items 125–128 in `HR_CONFIRMATION_PENDING.md`:
- the definitions of attendance rate, leave utilisation and payroll cost (F-Q1);
- whether large exports should run as background jobs (F-Q3).

---

## Module 8: Performance (2026-11-05)

Scope and design: `MODULE_8_DECISIONS.md`, recorded before implementation. It follows contract E5.

**Before starting:** Modules 1–7 are unchanged. This module adds a new migration, a model, a schema, a service, a controller and tests.

### What was built

**Frontend endpoints:** all 15 calls of `performance.http.ts`.

| Area | Endpoints | Access |
|---|---|---|
| Dashboard and configuration | summary, configuration (active scales and competencies) | `hr.performance:view` |
| Cycles | list, create (draft), advance one phase | view / `hr.performance-cycles:manage` |
| Goals | list, detail, create, record progress | view / `hr.goals:manage`, organizational scope |
| Reviews | list (`assignedToMe`), detail with `canAssess`, manager assessment (draft or submit) | view (scope, or assigned to the caller) / assigned reviewer with `hr.performance-reviews:assess` |
| Development plans | list, create, update an action | view / `hr.development-plans:manage`, organizational scope |

**Additions (no frontend screen):** HR setup endpoints, each with GET, POST and PUT, and `hr.performance-cycles:manage`:
- `/hr/setup/rating-scales`;
- `/competencies`;
- `/performance-recommendations`.

**Database:** migration `0010` adds 11 tables:
- `rating_scale`, `competency`, `performance_recommendation`;
- `appraisal_cycle`, `appraisal_cycle_event`;
- `goal`, `goal_progress_update`;
- `performance_review`, `performance_review_event`;
- `development_plan`, `development_action`.

**Triggers and constraints:**
- append-only history tables;
- recommendation codes never change;
- a completed goal must be at 100%;
- one review per cycle and employee.

### Rules enforced (contract E5)

- No score is ever computed.
- Only one cycle runs at a time (409).
- A goal's weight is refused (422) when the employee's goals in the cycle would total more than 100%; the due date must fall inside the cycle.
- Progress updates are append-only.
- Submitting an assessment requires the overall rating, every competency rating, strengths, improvements and a recommendation.
- A development plan completes when all its actions are done, and reopens if one is reopened.

### Verification

| Check | Result |
|---|---|
| Tests | **199 passed**: 195 earlier tests plus 4 new ones in `tests/test_performance.py`. They cover setup and fixed levels, phases and the one-running-cycle rule, weights and due dates, progress, segregation of the assessor, draft and submit, plans, the summary, organizational scope and permissions. |
| Contract check | **131 shapes**, and **135 of 135 routes**, match the frontend. |
| Migration | upgrade, `alembic check` with no drift, downgrade to `0009`, upgrade. |
| API mapping | 135 of 144 HRMS endpoints implemented. Left: Reports 5, HR workspace 4. |

### Pending

Items 118–124 in `HR_CONFIRMATION_PENDING.md`:
- who takes part in a cycle;
- who reviews;
- self-assessment (not built);
- the assessment window;
- when goals can change;
- recommendation options;
- scales and competencies.

---

## Module 7: Payroll (2026-11-05)

Scope and design: `MODULE_7_DECISIONS.md`. It follows ANALYSIS decision Q3 (approved) and was recorded before implementation. Implementation notes are at its end.

**Before starting:** migrations `0001`–`0008` are unchanged. Payroll is a new migration and new packages. The only Module 1–6 code touched:
- the G6 policy service, for the new `payroll` area and select fields;
- one test, which used `payroll` as its "area not yet available" example.

### What was built

**Frontend endpoints:** all 30 calls of `payroll.http.ts`.

| Area | Endpoints | Access |
|---|---|---|
| Periods | list, summary, validation (GET and POST), inputs, calculation, results, one result, submission, decision, payslip publication | view / process / approve |
| Configuration | salary components, salary structures, employee salaries (list and detail) | `hr.payroll:view`; salaries `hr.payroll:view-amounts` |
| Payslips | all (scope), own (`/hr/me/payslips`), PDF document | `hr.payslips:view` / `hr.self:view-payslips`; PDF: own payslip, or payslips:view + view-amounts |
| Register | report and CSV/XLSX export | `hr.reports-payroll:view` + `hr.payroll:view-amounts` |
| Configurations and assignments (H4) | list, options, create, update; assignments list, preview, create, end, history; effective configuration | view / `hr.payroll-config:manage` / `hr.payroll-assignments:manage` |

**Additions (no frontend screen):**
- HR setup endpoints `/hr/setup/salary-components` (GET, POST, PUT), `/salary-structures` (POST, PUT), `/employee-salaries` (POST, append-only) and `/payroll-periods` (POST);
- the G6 area `payroll` with 5 fields, all empty;
- the setting `PAYSLIP_COMPANY_NAME`.

**Database:** migration `0009` adds 10 tables:
- `salary_component`, `salary_structure`, `employee_salary`;
- `payroll_period`, `payroll_period_event`, `payroll_result`, `payslip`;
- `payroll_configuration`, `payroll_assignment`, `payroll_assignment_history`.

**Triggers:**
- append-only on salary records, the period history and the assignment history;
- stable codes on components, structures and configurations.

**Calculation:** a pure engine in `app/services/payroll/engine.py`:
- formula types `fixed`, `percent`, `balance_of_gross`, `overtime_rate` and `slab`;
- base caps, maximum amounts, proration by paid days;
- each line rounded to 2 decimals, half up.

Inputs come from attendance, leave, approved overtime, the salary record and the effective configuration.

### Verification

| Check | Result |
|---|---|
| Tests | **195 passed**: 188 earlier tests plus 7 new ones in `tests/test_payroll.py`. They cover engine formulas, caps, slabs, proration and rounding; setup validation; the full workflow; amount masking; payslips and PDF; register and export; loss of pay; configurations and assignments; permissions. |
| Contract check | `tools/verify_contracts.py`: **113 shapes**, and **120 of 120 routes**, match the frontend. |
| Migration | `alembic upgrade head`, then `alembic check`: no drift. |
| API mapping | 120 of 144 HRMS endpoints implemented. Left: Performance 15, Reports 5, HR workspace 4. |

**Defects found by the new tests and fixed before delivery:**
- the balance-of-gross allowance counted overtime as part of the monthly gross;
- under proration, percentage components worked out their full-month amount from the prorated base.

### Pending

Items 106–117 in `HR_CONFIRMATION_PENDING.md`:
- all components, rates and slabs;
- the proration basis;
- absences as loss of pay;
- rounding;
- the large-change threshold;
- self-approval;
- salary revisions inside a period;
- TDS;
- other frequencies;
- the payslip layout.

---

## Module 6: Leave Management, with permission and overtime requests (2026-11-04)

Scope and decisions: `MODULE_6_ANALYSIS.md` (approved) and `MODULE_6_DECISIONS.md`, both recorded
**before** implementation. **Part B (permission and overtime requests) is included.**

**Before starting:** Modules 1–5 were verified as preserved. Only documentation had changed since `hrms-service-module5.zip`, and the fingerprints of migrations `0001`–`0007` match. No Module 1–5 migration or table was changed.

### What was built

**Frontend endpoints:** all 26 calls of `leave.http.ts` and `approvals.http.ts`.

| Area | Endpoints | Access |
|---|---|---|
| Lookups | leave types, holidays, leave policies | types and holidays: any signed-in user (holidays filtered to the caller's location; all for HR); policies: `hr.leave-policies:view` |
| Dashboard | `GET /hr/leave/summary` | `hr.leave:view`, organizational scope |
| Requests | list (filters, `scope`, `escalated`, `awaitingMe`), detail, estimate, apply (multipart), decision, cancellation, comments | HR in scope, the employee, or the assigned/escalated approver; see the rules below |
| Workflows (H3) | list, options, create, update | view: `hr.leave-policies:view` or `hr.leave-workflows:manage`; change: `hr.leave-workflows:manage` |
| Balances | all employees (scope), own | `hr.leave-balances:view` / `hr.self:view` |
| Approval inbox (E3) | `GET /hr/approvals`: leave, permission, overtime, attendance corrections | what the caller may decide now; never their own |
| Part B | permission requests and overtime requests: list, detail, submit, decision | `…:view` / `…:approve`, or the reporting manager with `hr.approvals:act`; overtime also through a G5 workflow |

**Additions (no frontend screen):**
- HR setup under `/hr/setup` (`hr.leave-policies:manage`): leave types, leave policies, holidays (create, change, delete), allocations, adjustments, the ledger, and the notification queue status;
- attachment download `GET /hr/leave/requests/{id}/attachments/{aid}/content`, with the same access as the request;
- the G6 area `leave` on `/admin/policies/leave`, with 7 fields, all empty.

**Database:** migration `0008` adds 13 tables:
- `leave_type`, `leave_policy`, `holiday`;
- `leave_ledger_entry`;
- `leave_approval_workflow`, `leave_workflow_history`;
- `leave_request`, `leave_request_attachment`, `leave_routing_event`, `request_event`;
- `permission_request`, `overtime_request`;
- `notification_outbox`.

Four tables are append-only (enforced by trigger, reusing `hrms_append_only()` from `0007`): the ledger, request history, routing events and workflow history. `leave_type.code` can never change (the `0003` trigger).

**The owner's decisions:**

1. **No re-routing.** The workflow, approver, escalation deadline and recipient are copied onto each request at submission. A test changes and deactivates the workflow; the existing request keeps its routing, and only new requests follow the change.
2. **After escalation, both act; the first valid decision wins.**
   - The original approver, the escalation recipient and HR (`hr.leave:approve`, in scope) may decide.
   - A decision locks the request row, then checks that it is pending (409 `INVALID_TRANSITION`) and that the version matches (409 `STALE_VERSION`).
   - Usage ledger entries carry a per-request key, so a request can never be charged twice.
   - **Tested with real concurrency:** two connections decide at the same moment, one approving and one rejecting. Exactly one commits and the other gets 409.
3. **Balance blocked by default:** 422 on `leaveTypeId`, for example "This request needs 3 days but only 2 are available." The request is accepted only when HR turns on `allowNegativeBalance`. The estimate always shows the shortfall, and pending days reduce the available balance.
4. **Holidays:** an optional work location; empty means company-wide. An employee gets the company-wide holidays plus their own location's. HR sees all of them.
5. **Complete history:** every event is recorded in the request's append-only history and in the audit log. That covers:
   - submitted, approved, rejected, cancelled and commented;
   - reminder and escalation (as routing events);
   - workflow created, updated, activated and deactivated;
   - setup changes;
   - every balance transaction, attachment downloads and refused uploads.

**Day counting:** the dates from first to last day, less weekly offs and holidays:
- weekly offs come from the employee's assigned shift on each date (Module 5); without a shift, from `COMPANY_WORKING_DAYS`;
- if that setting is empty, nothing is guessed and a warning is shown;
- the HR setting `countOffsWithinLeave` charges weekly offs and holidays too;
- a half day counts 0.5;
- the charged dates are stored on the request, and attendance shows exactly those.

**Balances** are sums of the ledger: allocation, accrual, carry-forward, lapse, usage, usage reversal, adjustment.
- The worker job `leave.accrue` applies only the policies HR entered (`annual` or `monthly`, with no proration), plus carry-forward capped at `maxDays`, with the old year closed by a `lapse` entry.
- It is idempotent through period keys and inserts in batches.

**Escalation (`leave.escalate`, every 15 minutes):**
- a reminder is sent before the deadline;
- at the deadline the request moves to stage `escalated` and the recipient is assigned;
- escalation never decides a request;
- deadlines in `hours`, `days`, or `working_days`; `working_days` skips non-working company days and holidays, and is refused while the company working days are not configured.

**Notifications:**
- written to `notification_outbox` in the same transaction as the change, following the workflow's flags (submit, before the deadline, escalation, decision);
- `notifications.deliver` posts them to Platform with retries and backoff, once the URL and token are set.

**Attendance integration (Module 5):**
- **Leave:** approved full-day leave shows `on_leave`. Half-day leave shows `half_day` with the leave type: no lateness for a first-half leave, no early exit for a second-half leave, and no absence.
- **Holidays:** a holiday shows `holiday`, also on a weekly off.
- **Counts:** the calendar's `approvedLeaveDays` and `holidays`, and the monthly `leave` and `holiday` counts, are now filled.
- **Recalculation:** approving leave, and changing a holiday on a past date, queue a recalculation.
- **Locked periods:** a locked payroll period refuses the approval or the holiday change (409 `PERIOD_LOCKED`). Locked days keep their stored status.

**Part B:**
- **Permission requests:** times as `HH:mm`, minutes calculated, overlaps refused, contract E approval.
- **Overtime:** 1–960 minutes, no future dates, one pending request per date. `recordedMinutes` is attendance's time beyond the shift. Approval uses the published G5 `overtime` workflow (steps copied, HR oversight, escalation through `workflow.escalate`); without one, contract E applies.
- **No limits** beyond the frontend form rules (L30).

**Attachments:**
- `.pdf .jpg .jpeg .png`, up to 5 MB each and at most 5 files;
- the content must match the extension, and every file is scanned for malware;
- stored in encrypted private storage, as Module 3 documents;
- a missing attachment is a warning only (L15).

### Verification

| Check | Result |
|---|---|
| `python -m pytest` | **188 passed**: 161 earlier plus 27 new (5 setup, 8 applications and decisions, 5 workflows and escalation, 7 integrations, 1 concurrency, 1 large data) |
| Setup | Nothing pre-filled (types, holidays, policies, workflows, all 7 `leave` settings empty). Code format and stability enforced, including by database trigger. Policy overlaps refused. Holidays per location. Allocations and adjustments need a reason and an employee in scope. The ledger refuses UPDATE in the database. |
| Applications | Every frontend form message repeated exactly. Overlap (half days of the same date allowed). No working days. Notice and back-dating only when set. Inactive type. Applying for another employee needs `apply-on-behalf` and scope. |
| Decisions | No self-decision (403). Outsider gets 404. Rejection needs a comment. A comment moves the version (409). Late approve or reject gets 409 `INVALID_TRANSITION`. Ledger charged once. HR oversight in scope only. |
| Cancellation | Pending: the employee or HR. Approved and not started: reversal entry, balance restored. Started: 409. |
| Workflows | Every frontend validation message. Conflicts (company and departments). History: created and deactivated. Stale version 409. Department routing before the company default. Fallback approver. Reminder, then escalation, run idempotently. Recipient can act only after escalation. Both may act; the first wins. |
| Integrations | `on_leave`, `half_day` and `holiday` in day detail and calendar. Stored day refreshed by the worker. Locked periods refuse approval and holiday changes. Accrual and carry-forward correct and idempotent. Leave year setting. Summary lists only when their settings are set. Inbox counts, order and paging. |
| Concurrency | Real two-connection test, repeated 3 times: one commits, one gets 409. Cleanup verified (no rows left). |
| Large data | 1,000 employees: **11,000 accrual credits in 3.2 s**. Balances page 0.03 s, requests page 0.17 s, summary 0.04 s, inbox with 1,000 pending 0.04 s. |
| Migrations | Fresh database: `downgrade base`, `upgrade head`. `alembic check` shows no drift. `0008` down and up. The 5 row triggers are present. Module 1–5 fingerprints unchanged (7 of 7). |
| Contract check | `tools/verify_contracts.py`: **90 shapes** and **90 of 90 routes** match the frontend. The 26 Module 6 calls are all present. |
| Worker | It ran `attendance.close_day`, `shift.sync_current`, `workflow.escalate`, `leave.escalate` and `leave.accrue`, then stopped cleanly on SIGTERM. |
| Frontend | unchanged |

### Bugs found and fixed during verification

- The approval inbox `counts` key `attendance_correction` was camelCased. It now follows `Record<ApprovalType, number>`.
- A late decision by the escalation recipient returned 404 instead of 409. Authority now uses the permanent `escalated_at`.
- Accrual for more than about 2,000 credits exceeded PostgreSQL's parameter limit. It now inserts in batches of 1,000.
- A reminder was also sent for an already overdue request. Overdue requests are now only escalated.

### Changes to earlier modules (code only, no tables)

- The Module 5 calculator and data loader overlay approved leave and holidays. All 161 earlier tests still pass.
- The G6 policy service has the `leave` area. One Module 5 test now uses `payroll` as its "not yet available" area.
- `workflow.escalate` also escalates overtime requests.

### Pending (see `HR_CONFIRMATION_PENDING.md`, items 74–105)

- **HR:**
  - leave types, entitlements and holidays (none pre-filled);
  - leave year, proration, carry-forward timing;
  - notice and back-dating windows, the half-day rules in attendance;
  - permission and overtime limits and routing.
- **Platform:**
  - `COMPANY_WORKING_DAYS` source (L18);
  - the notification endpoint and token;
  - accepting `roleCodes` for role recipients.
- **Identity:** a list of active roles and users for the approver options.
- **Not built (out of scope):**
  - leave reports (Reports module);
  - encashment;
  - optional holidays;
  - partial cancellation;
  - sandwich and maximum-consecutive-day rules.

### Known limitations

- Overtime step approvers of type role or user see their requests through the inbox and the detail, not in the overtime list.
- A pending request of an old leave year that is approved after the year-end can make that year negative (item 105).

### Next step

Module 7 is **not** started; it waits for the owner's approval.

---

## Module 5: Time & Attendance (2026-11-03)

Scope and decisions: `MODULE_5_ANALYSIS.md` (reviewed) and `MODULE_5_DECISIONS.md`, both recorded
**before** implementation.

**Before starting:** Modules 1–4 were verified as preserved. Only documentation had changed since `hrms-service-module4.zip`, and the fingerprints of migrations `0001`–`0006` match. No Module 1–4 migration was changed.

### What was built

**Frontend endpoints:** all 15 new ones from the analysis, plus the 3 shift endpoints from Module 1.

| Area | Endpoints | Access |
|---|---|---|
| Registers | summary, daily register, monthly register, monthly export (CSV/XLSX) | `hr.attendance:view`, within organizational scope |
| One employee | day detail, month detail, calendar | attendance view (in scope), the caller's **own** record (`hr.self:view`), or a **direct report** (`hr.approvals:act`). The calendar returns 403 outside scope (H1); the others return 404. |
| Events | list (date, department, employee, source, sync status, exceptions), detail with the day record | `hr.attendance:view`, in scope |
| Corrections | list, detail, submit, decision | see the workflow below |
| Shift assignments | `POST /hr/shifts/{id}/assignments` | `hr.shifts:assign` (+ `hr.shifts:assign-backdated` for back-dating) |
| Devices | list, sync history | `hr.devices:view` |

**Configuration endpoints:**
- the 6 G5 workflow endpoints (processes, list, detail, save, publish, archive);
- G6 `/admin/policies/{attendance|shifts|overtime}`. Attendance changes need `admin:policies.payroll-manage`, as G6 says. Every value starts empty.

**Additions:**
- `POST /hr/attendance/events/ingest`, authenticated per device with a hashed API key, and checked **before** the body is read;
- device setup and key issue;
- attendance period locks.

**Database:** migration `0007` adds 13 tables:
- `policy_setting`, `workflow`, `workflow_history`;
- `shift_assignment`, `shift_assignment_change`;
- `attendance_device`, `device_sync_run`, `attendance_event`, `attendance_day`;
- `attendance_correction`, `attendance_correction_event`;
- `attendance_lock_period`, `background_job`.

Four tables are append-only (enforced by trigger): events, correction history, assignment changes and workflow history. A data step copies each employee's current shift into the assignment history.

**The calculation:** `app/services/attendance/calculator.py` holds pure functions, tested without a database. Screens always calculate from current data, so every screen agrees. Locked dates are the exception: they show their stored, frozen record.

**Decision 1, approval workflows (configurable):**
- HR administration configures, publishes and archives workflows through G5. Publishing archives the previous workflow from the new start date. Requests in progress keep the steps they started with.
- The default (reporting manager review) is setup data, not code: the loader publishes it from the template.
- **HR oversight:** `…corrections:approve` may decide at any step.
- **Escalation:** after `escalateAfterHours`, the step's fallback (a role or user) may decide; the worker marks overdue steps.
- **No self-approval:** returns 403, even for HR.
- **History:** a rejection needs a comment; a stale version returns 409; an already-decided request returns 409. Complete history is kept in the request and in the audit log.

**Decision 2, back-dated shift assignments:**
- off by default;
- when switched on: `allowBackdatedAssignments`, the permission `hr.shifts:assign-backdated`, a mandatory reason, and `maxBackdatedDays` if set;
- each assignment's change record holds the old and new shift, effective date, user, time, reason and **affected attendance days**;
- the affected days are recalculated by the worker;
- a locked (finalized payroll) period returns 409 `PERIOD_LOCKED`.

**Worker:** generic `background_job` queue with four job types:
- `attendance.close_day`, nightly;
- `attendance.recalculate`;
- `shift.sync_current`, daily;
- `workflow.escalate`, hourly.

Scheduled jobs are queued once each, using dedupe keys.

**Module 2 integration:** the employee form's shift is recorded in the assignment history: from the joining date when an employee is added, and from today when it changes.

### Verification

| Check | Result |
|---|---|
| `python -m pytest` | **161 passed**: 133 earlier plus 28 new (12 calculation, 5 punch intake and registers, 10 corrections, workflows, assignments, locks and jobs, 1 large data) |
| Calculation | Every status. Break deduction on and off. Lateness after grace. Early exit. Half-day and absent thresholds, set and unset. Overtime eligibility, minimum, rounding and cap. Overnight shift punches. Missing punch today versus after the shift. Weekly offs. Corrections replacing punches. |
| Punch intake | Accepted, unknown attendance ID (rejected and visible), future timestamp, before joining, resend recognised and stored once, duplicate and delayed rules only when HR sets them, a missing time-zone offset (422), a wrong key (401 whatever the body), user tokens refused. |
| Workflows | Default single step; a two-step workflow with a step condition; escalation to a fallback user; HR oversight; no self-approval; a broken workflow refused at publication (422); saving a published workflow makes a draft; the processes list |
| Back-dating | Refused by default; refused without the permission (403); reason required; `maxBackdatedDays`; recorded with old and new shift, reason, user and affected days (10); audit entry; recalculation job queued |
| Locks | Correction 409, back-dated assignment 409, late punch rejected, frozen record shown, only `hr.payroll:approve` can lock |
| Large data | 1,000 employees and **10,000 punches ingested in 15.8 s** (10 pushes of 1,000). Monthly register 0.8–0.9 s, monthly export 0.8–1.0 s, daily register 0.1 s. |
| Migrations | `0007` on a **fresh database**, with a pre-existing employee whose shift was copied into history; downgrade and upgrade; `alembic check` shows no drift; Module 1–4 fingerprints unchanged; full `downgrade base` works |
| Contract check | `tools/verify_contracts.py`: **71 shapes** and **64 of 64 routes** match the frontend. One documented addition: `ShiftAssignmentResult.affectedAttendanceDays` and `.backdated`. |
| Worker | It queued and ran `close_day`, `shift.sync_current` and `workflow.escalate`, then stopped cleanly on SIGTERM. |
| Frontend | unchanged |

### Pending HR, management, IT or the frontend team

These are items 45–73 in `HR_CONFIRMATION_PENDING.md`. Every threshold is configurable and empty until set. The items that need someone outside HR:

- **Identity:** add the permission `hr.shifts:assign-backdated` to its catalogue (item 62).
- **Frontend team:** add a reason field to the shift-assign dialog, which back-dating needs (item 63).
- **IT:** choose the device vendor and connector and an offline threshold (item 65), the duplicate and delay windows (items 67–68), and the clock tolerance (item 69).
- **Management, IT and Legal:** decide whether mobile-app attendance is in scope (item 66).

### Known limits (by design)

| Item | Note |
|---|---|
| Leave and holidays | `on_leave` and `holiday` appear with Module 6. The calendar's leave and holiday counts are 0 until then. |
| Workflow role/user check | Checking that a configured role or user is *active* needs an Identity API (G5); HRMS checks only that a value is given. |
| Device "offline" | Not reported until IT defines how often a device should push. |
| Clearing an employee's shift | The form can change the shift, but removing it doesn't end the assignment history. Use a new assignment instead. |

### Is the next module safe to begin?

**Yes:** there are no open defects; tests, migrations (fresh database), contracts and the worker are verified.
**Module 6 (Leave)** should come next: it fills the `on_leave` and `holiday` days that attendance already
has a place for. It will not be started until you approve.

---

## Module 4: Employee Import (2026-11-03)

Decisions are recorded in `MODULE_4_DECISIONS.md`.

**Before starting:** Modules 1–3 were verified as preserved. The source matched `hrms-service-module3.zip` byte for byte, migrations `0001`–`0005` match their SHA-256 fingerprints, and 114 of 114 tests passed.

### What was built

**Endpoints:** the 4 contract endpoints, plus 3 additions for API clients.

| Endpoint | Notes |
|---|---|
| `GET /hr/employee-imports/fields` | 15 columns, the contract's proposed template. A column is required exactly when the employee form requires the field. Contact columns appear only with `view-contact`. Examples come from the company's configuration. |
| `POST /hr/employee-imports/validate` | The preview: per-row `valid`, `warning`, `duplicate` or `error`, with messages per field, plus a totals `summary`. Saves nothing. |
| `POST /hr/employee-imports` | Returns 202 with a queued job. Rows are checked again at import time. |
| `GET /hr/employee-imports/{jobId}` | Status, progress, `summary` (shown for every finished job) and `failures` with reasons. Owner only. |
| `GET /hr/employee-imports/template?format=xlsx\|csv` | The template, generated from the same column list; the `.xlsx` version has an Instructions sheet. |
| `POST /hr/employee-imports/file-rows` | Reads `.xlsx` (first sheet) or `.csv` into rows on the server, with automatic column mapping. Stores nothing. |
| `GET /hr/employee-imports/{jobId}/failures.csv` | Row-level error report, safe from formula injection. |

**Checks on each row:**
- every row is converted to the same request the "Add employee" form sends and checked by **the same validator as Module 2**: formats, configured values, statuses allowed for new employees, unique values against existing employees, and organizational scope;
- import-specific checks on top:
  - reference values matched by code or name;
  - reporting manager matched by employee code;
  - unknown columns;
  - date formats;
  - unique values against earlier rows of the same file.

**Background processing:**
- the job table `employee_import_job` (migration `0006`);
- the worker `python -m app.worker`, which claims jobs with `FOR UPDATE SKIP LOCKED`, sends heartbeats, takes over stale jobs and shuts down gracefully on SIGTERM.

**Transactions:**
- one savepoint per row;
- one commit per batch of 50, together with the job's progress and counts, protected by the database check `created + skipped + failed = processed`;
- a job is resumed after its last committed batch;
- an unexpected stop gives `failed`, with the counts and a plain explanation of what was and wasn't created.

**Shared with Module 2:** `EmployeeService.insert_planned()` holds the one "save a new employee" step used by both the form and the import. Imported employees get history action `imported` and audit action `employee.imported`.

**Audit entries:** `employee_import.started`, `employee.imported` (each employee), `employee_import.completed`, `employee_import.failed`, `employee_import.file_read`, `employee_import.report_downloaded`, and every refused request.

**Dependencies added (pinned):** `openpyxl` 3.1.5, `et-xmlfile` 2.0.0, `defusedxml` 0.7.1.

### Verification

| Check | Result |
|---|---|
| `python -m pytest` | **133 passed**: 114 earlier plus 19 new (14 import and jobs, 5 files, template and large import). |
| Duplicate records | Each of these is reported as `duplicate`: an existing Employee ID (ignoring case); an existing email (ignoring case); an existing attendance ID; the same Employee ID as an earlier row. With `skipDuplicates` such rows are skipped *and listed*; without it they fail. A duplicate created after the preview is caught at import time. A row that loses a race at the database constraint fails alone with an explanation. |
| Invalid records | An impossible date (30/02); a bad phone or email; an unknown department; a status not allowed for new employees; an unknown manager code; an unknown column; required values missing; an over-long value; contact columns without permission. All return `error` with a reason per field, and none is skipped silently. |
| Large import | 2,000 rows (the contract's limit), including one duplicate and one invalid row. **Preview took 4.6 s; the background job took 17.4 s** (local PostgreSQL). Result: 1,998 created, 1 skipped, 1 failed; the failures list names rows 12 and 22. |
| Partial failure | A crash on the 4th row with batch size 2: the first batch (2 employees) is kept and reported, the interrupted batch is rolled back, and the job is `failed` with a plain message. A stale job is resumed by another worker without creating any row twice. |
| Authorization | 401 without a token. 403 without `hr.employees:import` on all 6 endpoints tested, with the denial audited. Jobs are visible to their owner only (404 for others). Rows outside the importer's organizational scope are errors, and an importer without a scope assignment can import nothing. |
| Files | `.xlsx` with Excel date cells and blank rows; `.csv` with a byte-order mark; automatic column mapping by alias; missing required columns reported. Refused: `.xls`, a fake `.xlsx`, a corrupt `.xlsx`, a non-UTF-8 CSV, an empty file, a header-only file, a zip bomb, too many rows, too large (413). |
| Saves nothing on preview | Employee and audit-log counts are unchanged after validation. |
| Worker process | Starts, polls, and exits cleanly on SIGTERM. |
| Migrations | `0006` upgrade, downgrade to `0005`, upgrade; `alembic check` shows no drift; Modules 1–3 migrations unchanged (fingerprints). |
| Contract check | `tools/verify_contracts.py`: 50 shapes and 39 of 39 routes match the frontend. `ImportValidationResult` gains one extra field, `summary`, which the frontend ignores. |
| Frontend | unchanged |

### Pending HR, management or IT (items 40–44 in `HR_CONFIRMATION_PENDING.md`)

- the import columns;
- the 2,000-row and 5 MB limits (configurable);
- whether a missing reporting manager stays a warning;
- who besides the owner may see import jobs;
- the accepted date formats.

### Known limits (by design)

| Item | Note |
|---|---|
| Import creates only | There is no update-existing mode: the contract defines import as creating employees. |
| No payroll or document columns | Not in the contract's template. |
| A worker must run | Without one, jobs stay `queued`. Deployment (later phase) adds a worker container. |
| Cancel | `cancelled` exists as a status (A10), but the contract defines no cancel endpoint. |

### Is the next module safe to begin?

**Yes:** there are no open defects; tests, migrations, contracts and authorization are verified.
**Before real use:** run the worker. The earlier prerequisites still apply: scope assignments (item 21),
encryption keys and the malware scanner.

---

## Module 3: Employee Documents (2026-11-03)

Decisions are recorded in `MODULE_3_DECISIONS.md`.

**Before starting:**
- Modules 1 and 2 were verified as preserved: the source was identical to `hrms-service-module2.zip` (a byte-level comparison), and migrations `0001`–`0004` match their SHA-256 fingerprints.
- The employee and document-type models were reviewed, along with the frontend contract B5 and `documents.service.ts` / `documents.http.ts`.

### What was built

**Endpoints:** all 7 frontend endpoints, plus 1 setup endpoint.

| Endpoint | Access | Notes |
|---|---|---|
| `GET /hr/employees/{id}/documents` | `hr.documents:view`, plus the employee in scope | Newest first; audited |
| `POST /hr/employees/{id}/documents` | `hr.documents:upload`, plus scope | Multipart with `file`, `documentTypeId`, `remarks`, `documentDate`, `expiryDate`. Checks run in this order: type, metadata, extension, size (413), real content, malware scan. The file is then encrypted and stored, and the upload is audited and added to history. |
| `GET /hr/employees/{id}/documents/{docId}/content` | `hr.documents:view`, plus scope, plus the document belonging to that employee | Returns the binary with `attachment`, `nosniff`, `no-store` and a sandbox CSP. The integrity hash is checked. Audited. |
| `GET /hr/employees/{id}/document-checklist` | `hr.documents:view`, plus scope | One item per active document type. The latest copy decides its state. Audited. |
| `GET /hr/document-compliance` | `hr.documents:view` | Paged; sorted by the contract's 5 fields; filtered by q, department, category, verification and status. Only employees in scope, excluding statuses marked "employment ended". |
| `GET /hr/document-compliance/summary`, `/attention?limit=` | `hr.documents:view` | Within scope. `limit` is 1–20, default 5. |
| `GET/PUT /hr/setup/document-settings` | `hr.settings:view` / `:manage` | Expiry window, 1–366 days; versioned and audited |

**Database:** migration `0005`, 3 tables, all with audit columns:
- `employee_document`: metadata only, plus a random storage key and a SHA-256;
- `employee_document_event`: the verification history, append-only by trigger;
- `document_settings`: a single row, with the expiry window set to 30 days (the contract's example, pending HR).

**Security code:**
- `app/core/file_inspection.py`: identifies the format from the content and cleans file names.
- `app/core/malware_scan.py`: a ClamAV `clamd` client that fails closed.
- `app/core/storage.py`: private storage that encrypts each file. Folders are 0700, files 0600, and stored names are random.
- `app/core/crypto.py`: gained separate document keys.
- Settings `DOCUMENT_ENCRYPTION_KEYS`, `MALWARE_SCANNER` and `CLAMAV_*`. Production refuses to start without document keys or with the scanner off.

**Module 1 change (tightening):**
- A document type may allow only formats the service can verify (`.pdf .jpg .jpeg .png`).
- A type's size limit may not exceed `MAX_UPLOAD_BYTES`.

**No secrets in source:**
- The test suite now generates its token secret and encryption keys on every run; the fixed test key from Module 2 is gone.
- Synthetic test files are deleted after each run.
- Development keys exist only in `.env`, which is not included in the ZIP.

### Verification

| Check | Result |
|---|---|
| `python -m pytest` | **114 passed**: 89 earlier plus 25 new. Of the new ones, 20 cover upload, download and access; 5 cover the checklist, compliance and settings. |
| Unauthorized access | 401 without a token. 403 without `hr.documents:view` or `:upload` on all 7 endpoints, with the denial audited. 404 for an employee outside the caller's scope (list, upload, download), for another employee's document, and for missing or invalid IDs. A cookie-authenticated upload without an allowed Origin is refused (CSRF). |
| Invalid files | An `.exe`; a PDF named `.jpg`; HTML named `.pdf`; an executable named `.pdf`; a PNG named `.jpg`; a truncated PDF; an empty file; a file without an extension. All return 422 on `file`, and nothing is stored. |
| Oversized files | Over the type's limit: 413 with the limit in the message. Over `MAX_UPLOAD_BYTES`: 413 before the body is read. No `Content-Length`: 411. |
| Malware | Using a local `clamd` stand-in: a clean file is accepted; an infected file gets 422 and an audit entry and is not stored; a scanner that is down gives 503 and nothing is stored. |
| Storage | The stored file is encrypted (no `%PDF` in it) and owner-only. A tampered or missing file returns 503 and nothing is served. No response contains a storage key, hash or URL. |
| Metadata | Expiry date required when the type says so; expiry after the document date; date format; remarks ≤ 200 characters; unknown or inactive types refused. |
| Migrations | `0005` upgrade, downgrade to `0004`, upgrade; full rebuild on every test run; `alembic check` shows no drift; 24 tables, all with audit columns. |
| Contract check | `tools/verify_contracts.py`: 45 shapes match the frontend TypeScript field for field, and 35 of 35 routes exist with the right method. |
| Live server | Starts; summary and settings answer; an unknown employee returns 404; nothing was written to storage. |
| Frontend | unchanged |

### Pending HR, management or IT (items 32–39 in `HR_CONFIRMATION_PENDING.md`)

- Which document types are required, and for whom.
- The expiring-soon window (30 days).
- Whether a copy awaiting verification counts as completed, and whether exited employees are excluded.
- **The verification workflow:** there is no verify/reject endpoint (D24), so every copy stays "pending".
- **The retention policy:** there is no delete endpoint (R4).
- File types and size limits per document type.
- Malware scanner hosting.
- Custody of the document encryption keys.

### Known limits (by design)

| Item | Note |
|---|---|
| Verify/reject | Not built until D24 is decided. Statuses other than "pending" can only come from a future verification endpoint. |
| Formats | Only PDF, JPEG and PNG can be verified by content. Adding a format means adding a content check. |
| Compliance at large scale | Computed per request over the employees in scope. Fine for a company of this size; a stored summary would be the next step if it ever becomes slow. |
| Orphaned files | If the process dies between storing a file and saving its record, an unreferenced encrypted file may remain. It is unreadable without a record and harmless, but a cleanup job belongs in the background worker (Module 4). |

### Is the next module safe to begin?

**Yes:** there are no open defects, and tests, migrations and contracts are verified. Module 4
(employee import) depends on employee records (Module 2) and introduces the background worker.
**Before real use:** set `DOCUMENT_ENCRYPTION_KEYS` and run ClamAV with `MALWARE_SCANNER=clamav`,
and management must assign organizational scopes (item 21).

---

## Module 2: Employees (2026-11-03)

Built after the owner's decisions of 2026-11-03, recorded first in `MODULE_2_DECISIONS.md`
(all 12 questions answered, with their status). Module 1 source and migrations were preserved:
migrations `0001`–`0003` are byte-for-byte unchanged (checked by SHA-256). The Module 1 ZIP is
kept as `hrms-service-module1.zip`.

### What was built

**Database (migration `0004`, 6 new tables, all with audit columns):**
- `employee`, `employee_contact`, `employee_payroll_value`, `employee_history`,
  `employee_reporting_line` and `employee_access_scope`;
- the department-head foreign key;
- two status settings, `employment_ended` and `reason_required`, both off by default;
- an append-only trigger on employee history;
- unique employee code (ignoring case), attendance ID and email.

**Endpoints (9 from the frontend + 3 setup):**

| Endpoint | Access |
|---|---|
| `GET /hr/employees` (paged, sort, q, 4 filters) | `hr.employees:view`, plus organizational scope |
| `GET /hr/employees/{id}` | `hr.employees:view`, plus scope. Contact fields need `view-contact`; payroll needs `view-sensitive` and is always masked |
| `POST /hr/employees` | `hr.employees:create`, plus scope. Contact and payroll sections need their permissions |
| `PATCH /hr/employees/{id}` | `hr.employees:edit`, plus scope. A status change also needs `change-status` (Q1). Omitted contact keys and blank sensitive keys keep their values |
| `POST /hr/employees/{id}/status-changes` | `hr.employees:change-status`, plus scope |
| `GET /hr/employees/lookup` | The picker screens' permissions. Results stay within scope, contain 4 fields, at most 20 per call, and exclude statuses marked ended. An empty `q` returns the first `limit` (Q6) |
| `GET /hr/employees/{id}/history` | `hr.employees:view`, plus scope. Section names only, never values |
| `GET /admin/reporting-lines` | `admin:organization.view` **and** `hr.employees:view`, plus scope |
| `POST /admin/reporting-lines/{id}` | `admin:organization.manage`, plus scope |
| `GET/POST/PUT /hr/setup/employee-access-scopes` | `hr.settings:view` / `:manage` |

**Security:**
- **Bank account encryption:** bank account numbers, and every payroll field marked sensitive, are encrypted at rest with Fernet.
  - Keys come from `PAYROLL_ENCRYPTION_KEYS`; production refuses to start without one.
  - Keys can be rotated with `rotate_payroll_encryption`.
  - If a field is switched to or from sensitive, its stored values are re-encrypted or decrypted.
  - Values are always masked to the last 4 characters, and never appear in logs, history or audit entries.
- **Organizational scope:** assigned to Identity roles. There are no defaults, and `*` does not bypass it. Records outside scope return 404, and writes cannot move a record out of the caller's scope.
- **Audited refusals:** every refusal is audited, including ones that depend on the request body (payroll or contact sections, a status change through PATCH).

**Module 1 completions:**
- department head (must be an active employee);
- `employeeCount` on departments and designations;
- `assignedEmployees` on shifts (employees whose current shift it is);
- no deactivating a department or designation that still has active employees;
- the self-service department list now returns the caller's own department.

**Supporting changes:**
- `dev_token --roles`;
- a failed request now always rolls back;
- `tools/verify_contracts.py` and `tools/gen_mapping.py` are bundled.

### Verification

| Check | Result |
|---|---|
| `python -m pytest` | **89 passed**: 60 from Modules 1 and foundation, plus 29 new (11 records, 5 status, 7 scope and picker, 6 reporting lines / organization / encryption) |
| Migrations | `0004` upgrade, downgrade to `0003`, upgrade; full `downgrade base` → `upgrade head` on every test run; `alembic check` no drift; 21 tables, all with audit columns |
| Contract check | `tools/verify_contracts.py`: 26 shapes match the frontend TypeScript field for field; 28 of 28 routes present with the right method |
| Placeholders | none |
| Live server | starts with the encryption key from `.env`; a token without a scope assignment sees no employees |
| Frontend | unchanged |

### Still pending HR or management (items 21–31 in `HR_CONFIRMATION_PENDING.md`)

- Role → organizational scope assignments: none exist yet, so nobody sees employee records until management assigns them.
- Which statuses mean employment has ended (template: `exited`).
- Which status changes need a reason (none).
- Back- and future-dating limits for status changes.
- Automatic probation confirmation (not done).
- Email and attendance ID uniqueness (implemented as the contract proposes).
- Approved mandatory and statutory fields.
- Employee code format.
- Company time zone (`UTC` until set).
- Who holds `hr.employees:view-sensitive`.

### Known limits (by design)

| Item | Where it is handled |
|---|---|
| `photoUrl` is always null | Contract D16 is undecided |
| Employee documents, import, shift assignment history | Modules 3–4 and the attendance module |
| A future-dated status change takes effect when it is recorded | Pending HR (item 24) |
| The development database loaded before Module 2 has `employmentEnded` off on `exited`, because the loader never overwrites | Set it through `/hr/setup/employee-statuses`, or reload a fresh database |

### Is the next module safe to begin?

**Yes, technically:** no open defects; tests, migrations and contracts are verified. Module 3
(employee documents) depends only on employee records, document types and storage.
**Before real use**, management must assign organizational scopes (item 21) and production needs
`PAYROLL_ENCRYPTION_KEYS`.

---

## Module 1: Organization and reference data (2026-11-03)

### Review of the previous phase (Phase 3, foundation)

| Check | Result |
|---|---|
| Tests | 22 / 22 passed before module 1 started |
| Migrations | `alembic check`: no drift between models and migration 0001 |
| Placeholders / TODOs | none found |
| Error contract vs frontend | `{error:{code,message,details[{field,message}]}}` and `x-request-id` match `src/api` parsing |
| Audit fields | present on every business table (enforced by a test) |
| Gap found and fixed | the frontend shows "updated by &lt;name&gt;", so `created_by_name` / `updated_by_name` were added to the audit columns |
| Gap found and fixed | database unique / foreign-key violations now return 409 `DUPLICATE` / `CONFLICT` in the error envelope instead of a 500 |
| Gap found and fixed | two malformed rows in `API_MAPPING.md` (`/admin/users/{uid}/status`, `/admin/reporting-lines/{eid}`) and the wrong permission for `/hr/employees/payroll-fields` |

### What was built

**Database:** migration `0002`, 14 tables, all with audit columns; versioned where editable:
`department`, `designation`, `designation_department`, `shift`, `shift_department`, `employment_type`,
`work_location`, `attendance_policy_option`, `overtime_policy_option`, `employee_status`,
`employee_status_transition`, `document_category`, `document_type`, `payroll_field_definition`.
Database checks back up the service rules (code formats, overnight = end before start, working days 1–7,
positive file size limits, unique codes; shift codes unique regardless of case). Migration `0003`
makes employee status codes and payroll field keys impossible to rename, even with direct SQL.

**Endpoints:** 19 of the frontend's endpoints plus 18 HR setup endpoints. See `API_MAPPING.md` (✅ rows).

| Endpoint(s) | Permission |
|---|---|
| `GET/POST /admin/departments`, `PUT /admin/departments/{id}` | view: `admin:organization.view` or `.manage`; write: `admin:organization.manage` |
| `GET/POST /admin/designations`, `PUT /admin/designations/{id}` | same as departments |
| `GET/POST /hr/shifts`, `PUT /hr/shifts/{id}` | view: `hr.shifts:view` or `:manage`; write: `hr.shifts:manage` |
| `GET /hr/departments` | any HR register or admin Users / Organization permission; self-service callers get only their own department (none until module 2) |
| `GET /hr/designations`, `/hr/employment-types` | `hr.employees:view`, `:create`, `:edit` or `:import` |
| `GET /hr/employee-statuses` | the above, `hr.employees:change-status` or `hr.approvals:view`; `transitions` only with `change-status` |
| `GET /hr/work-locations` | `hr.employees:create`, `:edit` or `:import` |
| `GET /hr/shifts/options`, `/attendance-policies/options`, `/overtime-policies/options` | `hr.employees:create` or `:edit` (employee form) |
| `GET /hr/document-types` | `hr.documents:view` or `:upload` |
| `GET /hr/employees/payroll-fields` | `hr.employees:view-sensitive` (as the contract says) |
| `GET/POST/PUT /hr/setup/*` (8 lists) | view: `hr.settings:view` or `:manage`; write: `hr.settings:manage` |

**Code (Repository-Service-Controller):**
models `department_model`, `designation_model`, `shift_model`, `reference_data_model`;
schemas `department_schema`, `designation_schema`, `shift_schema`, `reference_data_schema`;
repositories `department_`, `designation_`, `shift_`, `reference_data_repository`;
services `department_`, `designation_`, `shift_`, `reference_data_service`;
controllers `department_`, `designation_`, `shift_`, `reference_data_`, `reference_setup_controller`;
helpers `app/utils/ids.py` (path IDs → 404), `app/utils/validation.py` (all field errors in one 422, version check).

**Setup data:** `setup/reference_data.yaml` (template copied from the frontend's former sample lists,
marked for HR review) and `app/scripts/load_reference_data.py` (dry run, create-only, runs as the
system actor through the same services, every item audited).

### Business rules applied (all taken from the frontend; none invented)

- Department / designation code: trimmed, upper-cased, `^[A-Z0-9-]{1,10}$`; unique; name at least 2 characters.
- Department parent must exist and must not create a cycle.
- Shift rules and messages are the frontend form's (`features/hr/attendance/schemas.ts`): code ≤ 10
  letters/digits/hyphens, unique regardless of case; name 2–60; end ≠ start; overnight exactly when the
  end is earlier than the start; at most 16 hours; break 0–180 and shorter than the shift; grace 0–120;
  at least one working day.
- Every update accepts the `version` the client edited; a stale one returns 409 `STALE_VERSION`.
- Every create and update writes an audit-log entry with the changed fields.

### Verification

| Check | Result |
|---|---|
| `python -m pytest` | **60 passed** (22 foundation, 11 organization, 8 reference data / setup, 5 loader, 14 reference access) |
| `alembic downgrade base` → `upgrade head` | runs at the start of every test run; `downgrade 0002` → `upgrade head` also checked |
| `alembic check` | no drift |
| Contract check (script) | the 8 response types and 3 input types match the frontend TypeScript interfaces field for field; all 19 frontend calls exist with the same method |
| Live server smoke test | `/hr/shifts/options` and `/admin/departments` return the frontend shapes after loading the template |
| Loader | dry run, load, and a second run (all skipped) on the development database |

### Decisions (reviewed 2026-11-03)

1. **Reference list access: applied.** No list is open to every signed-in user any more. Each list is
   limited to the permissions of the frontend screens that use it (`app/core/reference_access.py`,
   derived from `pages.ts`, `navigation.ts` and the components that load each list), returns only the
   fields those screens need (no audit columns, versions, sort orders, heads or counts), and every
   refusal is written to the audit log. Field level: status `transitions` are returned only to
   `hr.employees:change-status`. Record level: self-service callers (My Leave, My Payslips, whose
   shared registers request the department list without showing it) get only their own department.
   No module 1 endpoint returns employee data; the approver and employee pickers use
   `/hr/employees/lookup`, which is designed in the module 2 analysis with minimal fields and scoping.
2. **Stable codes: approved and enforced** in the service (field error) and in the database (migration `0003`).
3. **Template values: recorded as pending HR confirmation** in `docs/HR_CONFIRMATION_PENDING.md`
   (20 items). All stay configurable through the API. The setup file carries `hr_confirmed: false`;
   the loader warns outside production and refuses to load an unconfirmed file into production.

### Known gaps (by design, filled by later modules)

| Gap | Filled by |
|---|---|
| Department `head` is always null; a non-null `headEmployeeId` is refused with a field error | Module 2 (Employees): foreign key to employees and head validation |
| `employeeCount` (departments, designations) and `assignedEmployees` (shifts) are 0 | Module 2 and the attendance module |
| Deactivating a department or shift that still has employees is not yet blocked | Module 2 / attendance (needs employee data) |
| `POST /hr/shifts/{id}/assignments` | Attendance module |

### Is the next module safe to begin?

**Yes.** Module 2 (Employees) depends on departments, designations, employment types, work locations,
statuses, shifts, policy options and payroll field definitions, all of which now exist, are tested and
have a stable API. No open defects.

---

## Phases 1–3: Analysis, architecture, foundation

Delivered `docs/ANALYSIS.md`, `docs/API_MAPPING.md`, `docs/ER_DIAGRAM.md`, `docs/AUTH_INTEGRATION.md`
and the service foundation (configuration, error envelope, request IDs, logs, authentication,
permissions, CSRF, audit fields and append-only audit log, optimistic concurrency, paging, health
checks), with 22 tests. Migration `0001` (audit log).
