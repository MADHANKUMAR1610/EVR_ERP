# Module 6 Analysis: Leave Management

**Status: analysis only, awaiting approval. No Module 6 code has been written.**

## Sources

**Frontend contract** (`HRMS_API_CONTRACTS.md`):
- E (general request rules) and E2 (leave, permission and overtime requests);
- E3 (approval inbox) and E-Q4 (leave balances);
- H3 (leave approval workflows and escalation), H-Q3 and H-Q4;
- G6 (HR policies, `leave` area) and G8 (notification preferences, owned by Platform);
- F (leave reports);
- A4 (record scoping), A9 (files), A10 (jobs).

**Frontend code:**
- `src/features/hr/leave/api/leave.service.ts` (types) and `leave.http.ts` (27 calls);
- `src/features/hr/leave/schemas.ts` (form rules);
- `src/features/hr/approvals/api/approvals.service.ts`;
- the leave screens.

**No invented values.** No leave entitlement, accrual, carry-forward, encashment, notice period or limit is invented. Every such value is HR configuration that starts empty, and every unresolved rule is listed in section 15.

---

## 1. Leave types and categories

| Item | Contract | Proposal |
|---|---|---|
| Leave type | `LeaveType { id, code, name, paid, allowHalfDay, balanceTracked, attachmentAfterDays, active }` (E2) | Table `leave_type`, maintained by HR through `/hr/setup/leave-types` and the setup YAML (Q4 decision). The frontend has no setup screen. |
| Categories | The frontend has **no category field**: `paid` and `balanceTracked` are its only classification | No category table. `paid` (for payroll later) and `balanceTracked` (unpaid or untracked types have no allocation) cover the contract. A category list can be added if HR needs one (L1). |
| Which types exist | Configuration (E "The UI only shows what the backend returns") | The setup template lists **no** leave types by default (L2). Typical types (casual, sick, earned, maternity …) depend on company policy and law, and are not invented. HR provides the list. |
| Codes | `code` on `leaveType` refs | Unique and stable once used by requests or ledger entries, like status codes (Module 1 rule). |

## 2. Leave policy and entitlement configuration

**Contract:** `LeavePolicy` is shown read-only by `GET /hr/leave/policies` (E2). Each policy has:
- `leaveType`;
- `accrual { method: annual | monthly | none, days }`;
- `carryForward { allowed, maxDays | null }`;
- `effectiveFrom`, `effectiveTo`;
- `appliesTo` (a display text);
- `allowHalfDay`, `attachmentAfterDays`.

**Proposal:**
- **Table `leave_policy`,** effective-dated: one or more per leave type, maintained by HR through `/hr/setup/leave-policies`. **All numbers are entered by HR.** There are no defaults: a type with no policy has no entitlement, and its balance shows `allocated: null`.
- **Applicability:** the contract only displays `appliesTo` as text. Proposal: optional filters on the policy (employment types and/or departments; empty means everyone), with `appliesTo` generated as text, for example "Permanent employees · Production, Winding". Whether HR needs other criteria (designation, location, service length) is question L5.
- **Policies are not edited backwards:** a change creates a new policy version with a later `effectiveFrom`, as G6 says for policies.
- **G6 policy area `leave`** (application rules, `/admin/policies/leave`). Fields are defined by the backend and **start empty**, as in Module 5:
  - `allowNegativeBalance` (E-Q4);
  - `countOffsWithinLeave` (whether weekly offs and holidays inside a range are charged);
  - `minimumNoticeDays`;
  - `backdatedWindowDays` (how far back leave may be applied);
  - `lowBalanceThreshold` and `upcomingWindowDays` (used by the leave summary).

## 3. Leave balance calculation and tracking

**Contract:** `LeaveBalance { leaveType, allocated | null, carriedForward, used, pending, available | null }`, per year (E2).

**Proposal: an append-only ledger** (`leave_ledger_entry`), one row per change, never edited:

| Entry type | Created by | Effect |
|---|---|---|
| `allocation` | Annual accrual job, or HR (`/hr/setup/leave-allocations`) | + days for the leave year |
| `accrual` | Monthly accrual job | + days for the month |
| `carry_forward` | Year-end job, capped at `carryForward.maxDays` | + days into the new year (and a matching `lapse` out of the old one) |
| `lapse` | Year-end job | − days not carried forward |
| `usage` | Leave **approved** | − charged days |
| `usage_reversal` | Approved leave **cancelled** before it starts | + days back |
| `adjustment` | HR, with a mandatory reason | ± days (corrections, opening balances at go-live) |

**Figures:**
- `allocated` = allocation + accrual entries of the year;
- `carriedForward` = carry_forward entries;
- `used` = usage − usage_reversal;
- `pending` = days of **pending** requests (not in the ledger, computed);
- `available` = allocated + carriedForward + adjustments − used − pending.
- For a type with `balanceTracked = false`, `allocated` and `available` are null.

**Pending decisions:**
- the leave year (calendar year or another start month) (L6);
- whether accrual runs annually at year start or monthly, and on which day (L7);
- whether new joiners get a pro-rated allocation, and how (L8: **no proration is applied unless HR defines it**);
- the carry-forward date and lapse (L9);
- opening balances at go-live (L10: entered as adjustments).

**Not built: encashment.** It is not in the frontend contract, so no encashment entries are created (L11).

## 4. Employee leave application

**Contract (E2):**
- `GET /hr/leave/requests/estimate` is a **backend preview** returning `days`, `excludedDates` (weekly offs and holidays), `availableBefore`, `overlapping[]` and `warnings[]`.
- `POST /hr/leave/requests` is multipart, with `employeeId?, leaveTypeId, from, to, portion (full|first_half|second_half), reason` and the files `attachments[]`.

**Frontend form rules, repeated on the server with the same messages:**
- a leave type is required;
- the first and last day are required;
- the last day cannot be before the first day;
- the reason is 3–500 characters;
- a half day needs `from == to` and a type with `allowHalfDay`.

**Contract checks:** 422 on an overlap with pending or approved leave, an invalid range, a half day not allowed, or no working days in the range.

**Days charged:**
- the dates from `from` to `to`, minus weekly offs (non-working days of the employee's **assigned shift** on each date, from Module 5) and holidays, unless `countOffsWithinLeave` is on;
- a half day counts as 0.5.

**Who may apply** (E2):
- the employee themself, with `hr.self:submit-requests`;
- someone on their behalf, with `hr.leave:apply-on-behalf` and the employee in the caller's organizational scope.

**Balance check:** if the request exceeds `available`, it is a warning in the estimate. Whether submission is **blocked** depends on `allowNegativeBalance` and E-Q4 (L12).

**Notice and back-dating:** `minimumNoticeDays` and `backdatedWindowDays` apply only when HR sets them (L13).

**Attachments:**
- stored like Module 3 documents: content check, size limit, malware scan, encrypted private storage;
- allowed types are those of the frontend constant `ATTACHMENT_RULES` (`.pdf .jpg .jpeg .png`, 5 MB), to be confirmed (L14);
- `attachmentAfterDays`: whether a missing attachment *blocks* the request or is only a warning (L15);
- the frontend lists attachments but has **no download call**. Proposal: add `GET …/requests/{id}/attachments/{aid}/content` for approvers and HR, under the same access rules as the request.

## 5. Manager / team-lead approval workflow (contract H3)

**Leave has its own workflow model.** H3 says "Leave is no longer offered in G5", so leave does not use the generic Module 5 builder.

**`LeaveApprovalWorkflow` (configuration):**
- `name`, `status` (`draft | active | inactive`);
- `scope` (`company` or `departments`, with departments);
- `firstApprover` (`reporting_manager | department_head`);
- `fallbackApprover` (role or user);
- `escalation { enabled, after, unit: hours | days | working_days, reminderHoursBefore, recipient }`;
- `notifications { onSubmit, beforeDeadline, onEscalation, onDecision }`;
- `effectiveFrom`, `effectiveTo`, `history[]`, `version`.

**Endpoints:** `GET`, `GET /options`, `POST`, `PUT` under `/hr/leave/approval-workflows`.

**Validation, as specified in H3:**
- the name is at least 3 characters;
- a departments workflow needs at least one department;
- the dates must be in order;
- when escalation is on: `after` between 1 and 720 hours or 1 and 30 days, a recipient required, and the reminder before the deadline;
- **conflicts are refused:** two active company defaults, or department workflows sharing a department, with overlapping periods.

**Routing at submission (H3 steps 1–3):**
1. Use the active workflow for the employee's department, else the company default. If two match, route to the fallback and raise an alert.
2. The first approver is the reporting manager (Module 2) or the department head (Module 1/2). If neither resolves, the fallback is used.
3. The deadline `escalationDueAt` is computed with the company calendar: working days, holidays and the time zone.

**Who may decide** (contract E):
- **the current approver**, with `hr.approvals:act`;
- **HR with `hr.leave:approve`**, at any time (oversight);
- **nobody** for their own request, which returns 403.

**Rules for decisions:**
- Rejecting needs a comment (422).
- A stale version returns 409, and deciding a non-pending request returns 409.
- `POST …/comments` adds a review comment without a decision.

**`LeaveRequest.approval`** reports:
- `stage` (`first_level | escalated | completed | withdrawn`);
- `currentApprover`, `escalationDueAt`, `escalatedAt`;
- `escalation` status (`not_configured | on_track | due_soon | overdue | escalated | not_applicable`);
- routing `events` (`assigned | reminder_sent | escalated`).

**No default workflow is invented.** If HR configures none, the contract E rule applies: the reporting manager (with `hr.approvals:act`) for direct reports, or HR with `hr.leave:approve`. The setup template can include a *draft* company workflow with first approver = reporting manager and escalation **off**, for HR to review and activate (L16).

## 6. Configurable escalation to HR (contract H3 step 4)

- **Who configures it:** the escalation delay (`after` plus `unit`), the reminder time and the recipient (normally an HR role) are set by HR per workflow. There is **no default delay**.
- **How it runs:**
  - a worker job (`leave.escalate`, reusing the Module 5 `background_job` queue and scheduler) sends the **reminder** at `escalationDueAt − reminderHoursBefore`;
  - at the deadline it sets `stage: escalated` and assigns the recipient;
  - every routing event is recorded and audited.
- **Escalation never approves or rejects** (H3). The browser runs no timer.
- **`working_days`** skips non-working days and holidays. Which calendar defines company working days is question L18: company settings (G7) belong to Platform, so HRMS would need them through an API or a setting.
- **H-Q3 (L19):** when a workflow changes, are pending requests re-routed? Proposal: they **keep their assignment**, as Module 5 requests keep their workflow version.
- **H-Q4 (L20):** after escalation, may the original approver still decide? Proposal: **both** the original approver and the recipient (plus HR oversight), as the frontend demo mode does.

## 7. Rejection, cancellation and withdrawal

| Action | Contract | Proposal |
|---|---|---|
| Reject | E: comment required; only pending requests | As specified; ledger unaffected (pending days are released) |
| Cancel (= "Withdrawn" in the inbox) | E2: `POST …/cancellation { version, comment? }` when **pending**, or **approved and not yet started**; by the employee or with `hr.leave:apply-on-behalf` | As specified. An approved request gets a `usage_reversal` ledger entry; `approval.stage` becomes `withdrawn`; attendance recalculated |
| Cancel leave that has started | Not allowed by the contract | Refused (409 `INVALID_TRANSITION`). Whether HR may shorten or cancel started leave is L21 |
| Partial cancellation (some days) | Not in the contract | Not built (L21) |
| Edit a request | Not in the contract | Not built: cancel and re-apply |

## 8. Holiday calendar and weekly offs

**Holidays:**
- **Contract:** `GET /hr/holidays?year=` returns `[{ date, name, type: national | festival | company }]`.
- **Proposal:** table `holiday`, maintained by HR through `/hr/setup/holidays` (and the YAML). **No holiday is pre-filled**: dates vary by year and state, and HR provides them (L22).
- **Per location** (E-Q3, L23): the contract has one company list. Proposal: an optional work location on each holiday (empty means all locations). The `GET` response stays as in the contract, filtered to the caller's or the employee's location when one is set.
- **Optional or restricted holidays:** not in the contract, so not built (L24).

**Weekly offs:**
- the non-working days of the employee's **assigned shift** on each date (Module 5 shift assignments);
- if an employee has no shift, the company working days from L18.

**Attendance integration (Module 5):**
- approved full-day leave sets the day to `on_leave`, and a holiday to `holiday`. This is the slot left in the Module 5 calculator, and the order is already defined there (A1);
- half-day leave is handled per H-Q1: a half day of leave plus worked time (L25);
- calendar and monthly counts: `approvedLeaveDays` (with 0.5 per half day), `leave`, `holidays`;
- approving or cancelling leave recalculates the affected stored days.

## 9. Half-day and other duration rules (as supported by the frontend)

- **`portion`:** `full`, `first_half` or `second_half`. A half day is only on a single day (`from == to`) and only if the type has `allowHalfDay`, either on the type or on its policy version (E2, form rules).
- **Charged days:** a half day is 0.5. A range is the working days in it (section 4).
- **Not in the frontend, so not built:** hourly leave, minimum or maximum days per request, maximum consecutive days, and "sandwich" rules (L26).
- **Short absences** are a separate request type: **permission requests** `{ date, from, to (HH:mm), minutes, reason }` (section 14, Part B).

## 10. Leave history and reporting

**History:**
- each request carries `history: WorkflowEvent[]` (`submitted | approved | rejected | cancelled | updated | commented`, `at`, `by`, `comment`), stored append-only;
- routing events (`assigned | reminder_sent | escalated`) are in `approval.events`;
- ledger entries give a full balance history.

**Registers in this module:**
- the leave requests list, with filters `scope, status, leaveTypeId, departmentId, from/to overlap, q, sort, escalated, awaitingMe`;
- balances per employee and year;
- the leave dashboard summary;
- the caller's own balances.

**Leave reports** (contract F: `leave_utilisation_employee`, `leave_utilisation_department`, `leave_balance`, `leave_history`, `upcoming_leave`) belong to the **Reports module**. They will read the tables built here. Proposal: build them in the Reports module, not here (L27).

## 11. Role-based permissions and organizational scopes

**Endpoint permissions** (catalogue codes already defined by the frontend):

| Endpoint group | Permission (contract) |
|---|---|
| Leave types, holidays | any signed-in user (E2) |
| Leave summary | `hr.leave:view` |
| Requests list | `hr.leave:view` (all, scoped), or `scope=mine` for the caller's own |
| Request detail | scoped: HR in scope, the employee themself, or the current or escalated approver |
| Estimate, apply | own: `hr.self:submit-requests`; others: `hr.leave:apply-on-behalf` |
| Decision | `hr.leave:approve`, or the current approver with `hr.approvals:act` |
| Cancellation | own, or `hr.leave:apply-on-behalf` |
| Comment | `hr.leave:view`, or the current approver |
| Balances (all) / own | `hr.leave-balances:view` / `hr.self:view` |
| Leave policies (read) | `hr.leave-policies:view` |
| Leave approval workflows | view: `hr.leave-policies:view` or `hr.leave-workflows:manage`; change: `hr.leave-workflows:manage` |
| G6 `leave` policy area | `admin:policies.view` / `admin:policies.manage` |
| Setup of types, policies, holidays, allocations and adjustments (additions) | `hr.leave-policies:manage` |
| Approval inbox | `hr.approvals:view` or `hr.leave:approve` |
| Permission / overtime requests | `hr.permission-requests:view` / `:approve`; `hr.overtime:view` / `:approve` |

**Organizational scope** (Module 2 role scopes) limits every HR list and action to employees in the caller's scope. Out of scope returns 404, as in Modules 2–5.

**Managers** see and decide only the requests where they are the current approver.

**Employees** see only their own requests and balances.

## 12. Notifications and audit history

**Notifications:**
- The Platform service owns notifications (decision Q1: in-app inbox, preferences G8).
- HRMS sends them through `POST /internal/notifications` (`AUTH_INTEGRATION.md`) using a **transactional outbox**:
  - the notification is written to `notification_outbox` in the same transaction as the request change;
  - a worker job (`notifications.deliver`) delivers it with retries;
  - nothing is lost if Platform is down.
- **Events:** submitted (to the approver), reminder before the deadline, escalated (to the recipient and the original approver), decided (to the employee), cancelled. Each follows the workflow's `notifications` flags.
- Until Platform's endpoint and service token are configured, notifications stay queued, and a status endpoint shows the backlog (L28).
- Email and SMS are out of scope (Q8, earlier decision).

**Audit log** (append-only, as in Modules 1–5): submit, estimate (no), decide, cancel, comment, escalate, reminder, workflow changes, setup changes (types, policies, holidays, allocations, adjustments with reasons), ledger jobs (accrual, carry-forward, lapse with counts), attachment upload and download.

## 13. Database models, relationships and migrations

**Migration `0008`** (additive; no change to Module 1–5 tables). All tables have audit columns; editable ones are versioned.

| Table | Purpose | Key constraints |
|---|---|---|
| `leave_type` | Types (section 1) | unique code; codes stable once referenced (trigger, as in migration 0003) |
| `leave_policy` | Effective-dated entitlement rules per type | FK `leave_type`; `effective_to ≥ effective_from`; no overlapping versions for the same applicability |
| `leave_policy_employment_type`, `leave_policy_department` | Applicability filters (proposal, L5) | FKs |
| `holiday` | Company calendar (`work_location_id` nullable, L23) | unique (date, location) |
| `leave_ledger_entry` | Balance ledger (section 3), **append-only** | FK `employee`, `leave_type`, optional `leave_request`; `leave_year`; reason required for adjustments |
| `leave_request` | Requests: employee, type, from, to, portion, days, reason, status, workflow snapshot, current approver, escalation fields, version | `from ≤ to`; portion check; a partial index on pending and approved requests helps refuse overlaps |
| `leave_request_attachment` | File metadata (the file in encrypted storage, as in Module 3) | FK `leave_request` |
| `leave_request_event` | History (`WorkflowEvent`), **append-only** | FK `leave_request` |
| `leave_routing_event` | `assigned`, `reminder_sent`, `escalated`, **append-only** | FK `leave_request` |
| `leave_approval_workflow` (+ `leave_workflow_department`, `leave_workflow_history`) | H3 configuration | conflict check in the service, plus a database exclusion constraint where possible |
| `notification_outbox` | Pending notifications for Platform | status, attempts, next attempt |
| `permission_request`, `overtime_request`, `request_event` | **Part B** (section 14), only if approved | as E2 |

**Relationships:**
- employee 1–n leave_request, leave_ledger_entry;
- leave_type 1–n leave_policy, leave_request, leave_ledger_entry;
- leave_request 1–n events, attachments, routing events;
- leave_approval_workflow n–n department;
- holiday n–1 work_location (optional).

**The attendance calculator (Module 5)** reads approved leave and holidays. No table change is needed there.

## 14. Frontend API contracts and endpoint mapping

**Part A, leave** (17 frontend endpoints + 1 approval inbox):

| # | Method | Path | Screen |
|---|---|---|---|
| 1 | GET | `/hr/leave-types` | application dialog, registers |
| 2 | GET | `/hr/leave/summary` | Leave Overview |
| 3 | GET | `/hr/leave/requests` | Leave Applications, My Leave, Leave Approval Inbox |
| 4 | GET | `/hr/leave/requests/{id}` | Request drawer |
| 5 | GET | `/hr/leave/requests/estimate` | Application dialog (preview) |
| 6 | POST | `/hr/leave/requests` (multipart) | Application dialog |
| 7 | POST | `/hr/leave/requests/{id}/decision` | Request drawer |
| 8 | POST | `/hr/leave/requests/{id}/cancellation` | Request drawer |
| 9 | POST | `/hr/leave/requests/{id}/comments` | Request drawer |
| 10 | GET | `/hr/leave/approval-workflows` | Leave Approval Workflows |
| 11 | GET | `/hr/leave/approval-workflows/options` | Workflow dialog |
| 12–13 | POST / PUT | `/hr/leave/approval-workflows[/{id}]` | Workflow dialog |
| 14 | GET | `/hr/leave/balances` | Balances & Policies |
| 15 | GET | `/hr/me/leave/balances` | My Leave |
| 16 | GET | `/hr/leave/policies` | Balances & Policies |
| 17 | GET | `/hr/holidays` | Holiday Calendar, application dialog |
| 18 | GET | `/hr/approvals` | Approval Inbox and My Tasks: leave **and** the existing attendance corrections (Module 5) |

**Part A additions** (HR setup, no frontend screen; Q4 decision):
- `/hr/setup/leave-types`, `/leave-policies`, `/holidays`, `/leave-allocations`, `/leave-adjustments`;
- the attachment content endpoint;
- G6 `/admin/policies/leave` (existing endpoint, new area);
- a notification outbox status endpoint.

**Part B, short requests** (8 frontend endpoints, same Leave & Requests screens). **Your decision** (L29): include in Module 6, or build separately.
- `GET/POST /hr/permission-requests`, `GET /{id}`, `POST /{id}/decision`;
- `GET/POST /hr/overtime-requests`, `GET /{id}`, `POST /{id}/decision`.

`OvertimeRequest.recordedMinutes` comes from Module 5 (beyond-shift minutes). Pay is never calculated here.

**Pending as above:** limits for permission and overtime requests (L30) and their approval routing (L31).

## 15. Questions requiring HR, management or IT confirmation

| # | Question | Proposal (if any) | Who |
|---|---|---|---|
| L1 | Are leave categories needed beyond `paid` / `balanceTracked`? | No (contract has none) | HR |
| L2 | Which leave types exist (names, codes, paid, half-day, attachment rule)? | HR provides; template empty | HR |
| L3 | Entitlement per type: accrual method and days | HR enters; nothing pre-filled | HR |
| L4 | Carry-forward allowed and maximum per type | HR enters | HR |
| L5 | Policy applicability criteria (employment type, department, others?) | Employment type + department filters | HR |
| L6 | Leave year: calendar year or another start | — | HR |
| L7 | Accrual timing (annual at year start / monthly on day N) | — | HR |
| L8 | Pro-rating for joiners and leavers | Not applied unless HR defines it | HR |
| L9 | Carry-forward date, lapse, expiry of carried days | — | HR |
| L10 | Opening balances at go-live | Entered by HR as adjustments | HR |
| L11 | Encashment | Out of scope (not in frontend) | HR + Finance |
| L12 | Exceeding the balance: block or warn (E-Q4) | `allowNegativeBalance` (empty = block) | HR |
| L13 | Minimum notice and back-dating windows | Settings, empty = not applied | HR |
| L14 | Attachment file types and size | Frontend constant (.pdf .jpg .jpeg .png, 5 MB) | HR + IT |
| L15 | `attachmentAfterDays`: block or warn | Warn | HR |
| L16 | Default leave workflow (template, draft) | Reporting manager, escalation off | HR |
| L17 | Escalation delay, reminder and recipient | HR sets per workflow | HR |
| L18 | Source of company working days (for `working_days` and employees without a shift) | A setting until Platform's company settings are reachable | Platform owner + HR |
| L19 | Re-route pending requests when a workflow changes (H-Q3) | No: they keep their assignment | HR |
| L20 | Original approver may decide after escalation (H-Q4) | Yes, both | HR |
| L21 | Cancelling or shortening leave that has started; partial cancellation | Not allowed | HR |
| L22 | Holiday list per year | HR provides; none pre-filled | HR |
| L23 | Holidays per location (E-Q3) | Optional location per holiday | HR |
| L24 | Optional or restricted holidays | Not built | HR |
| L25 | Half-day leave versus worked time in attendance (H-Q1) | — | HR |
| L26 | Sandwich rule, maximum consecutive days, minimum per request | Not built (not in frontend) | HR |
| L27 | Leave reports in the Reports module | Yes | Owner |
| L28 | Platform notification endpoint and service token | Outbox holds until configured | Platform owner |
| L29 | Build permission and overtime requests in Module 6 (Part B)? | Yes, same screens | Owner |
| L30 | Limits on permission minutes or overtime per day or month | None until HR sets them | HR |
| L31 | Approval routing for permission and overtime requests | G5 workflows (Module 5 engine) for overtime; permission requests follow the contract E rule | HR |
| L32 | Low-balance threshold and upcoming-leave window for the summary | Settings, empty until set | HR |

## 16. Dependencies on Modules 1–5

| Module | Used for |
|---|---|
| 1 | Departments (workflow scope, filters), employment types (policy applicability), work locations (holidays per location), the setup YAML and loader |
| 2 | Employees and joining dates; **reporting managers and department heads** (first approver); organizational scopes (every list and action); statuses marked `employmentEnded` (no new leave after exit); employee history |
| 3 | Secure file handling (content check, malware scan, encrypted private storage) reused for attachments |
| 4 | Worker job mechanics (claiming, heartbeat, resume) |
| 5 | **Shift assignments and working days** (weekly offs per date); the attendance calculator's `on_leave` and `holiday` slot, plus recalculation of stored days; period locks (approved leave cannot change a finalized payroll period); the G6 policy service (new `leave` area); the background job queue and scheduler (escalation, reminders, accrual, year-end, notifications); the approval inbox merges Module 5 attendance corrections |
| Foundation | Authentication, permissions, CSRF, audit, error envelope, paging, optimistic concurrency |
| External | **Platform service:** notification delivery, and the company working days if L18 says so. **Identity:** role and user names for approver pickers (`/approval-workflows/options`); until an Identity API exists, the options list only roles and users already used in HRMS configuration. |

## 17. Proposed implementation sequence (after approval)

1. **6.1 Configuration:** leave types, policies, holidays and the G6 `leave` area; setup endpoints and the YAML template (no values); `GET` types, policies and holidays.
2. **6.2 Ledger and balances:** allocations, adjustments, accrual, carry-forward and lapse jobs (only for rules HR has entered); `GET` balances and my balances.
3. **6.3 Requests:** estimate, apply (with attachments), list, detail, cancellation, comments, and the attendance integration.
4. **6.4 Approval workflows and escalation:** H3 configuration, routing, decisions, escalation and reminders (worker), the approval inbox (leave plus attendance corrections), and the notification outbox.
5. **6.5 Part B** (if approved): permission and overtime requests.
6. **6.6 Wrap-up:** summary, contract check, docs, completion report, `hrms-service-module6.zip`.

## 18. Test plan

| Area | Tests |
|---|---|
| Configuration | Type codes unique and stable; policy versions effective-dated with no overlap; G6 `leave` fields empty by default; holidays unique per date and location; permission checks |
| Day calculation | Weekly offs from the **assigned shift on each date** (including a shift change inside the range); holidays excluded; `countOffsWithinLeave` on and off; half days (0.5, single day only, type flag); no working days → 422; overnight shifts |
| Balances | Ledger arithmetic for every entry type; pending versus used; untracked types (null); accrual and carry-forward jobs only when HR rules exist; caps; lapse; year boundaries; adjustments need a reason; the ledger is append-only (trigger) |
| Applications | Frontend form rules and messages; overlap with pending or approved leave (422); estimate matches the charged days; negative balance blocked or allowed per setting; notice and back-dating settings; attachments (content, size, malware, encrypted storage, download access); on-behalf only in scope |
| Approval | Workflow resolution (department beats company; conflict → fallback plus alert); first approver = manager or head, else fallback; decisions by the current approver, HR oversight, **never own (403)**; reject without comment (422); stale version and non-pending (409); comments |
| Escalation | Deadline in hours, days and working days (with holidays); reminder event; escalation event and recipient; escalation never decides; both approvers after escalation (if L20); worker resume; audit |
| Cancellation | Pending; approved and not started (ledger reversal, attendance recalculated); started → 409; only own or on-behalf |
| Attendance integration | Approved leave → `on_leave`, holidays → `holiday`; half-day leave rule; cancellation restores the day; locked payroll periods refuse changes |
| Inbox and notifications | Inbox shows only what the caller may decide, oldest first, with counts per type (leave plus corrections); outbox rows created in the same transaction; delivery retries; nothing sent when the flags are off |
| Authorization and scope | Every endpoint without permission (403, audited); outside organizational scope (404); own-only access for employees; managers see only assigned requests |
| Large data | 1,000 employees × leave types: balances page and summary timings; 5,000 requests list and filters; accrual job for 1,000 employees |
| Migrations and contracts | `0008` on a fresh database, downgrade and upgrade, `alembic check`; Modules 1–5 fingerprints unchanged; `tools/verify_contracts.py` covering all leave shapes and routes; the full suite green |

## 19. Approval needed before implementation

1. Approve the scope (Part A) and decide **Part B** (L29).
2. Answer, or accept the proposals for, L1–L32. The values themselves (entitlements, delays, thresholds) do not block the build: they start empty. These decisions **change the build**:
   - L5: applicability criteria;
   - L6–L9: leave year, accrual and carry-forward timing;
   - L12: block versus warn on negative balance;
   - L18: the working-days source;
   - L19–L20: re-routing, and deciding after escalation;
   - L23: holidays per location;
   - L29: Part B.
