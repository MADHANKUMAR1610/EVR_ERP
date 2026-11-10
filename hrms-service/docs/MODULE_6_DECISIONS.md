# Module 6 (Leave Management): Decisions and Scope

Recorded 2026-11-04, before implementation.
**Status: implemented** (see the Module 6 completion report in `MODULE_REPORTS.md`). The owner approved `MODULE_6_ANALYSIS.md` with:

- the recommendations accepted;
- **Part B included**;
- the five decisions below.

## Part B is included: the complete Module 6 scope

**Part A, leave:** 17 frontend endpoints plus the approval inbox.
- **Lookups:** `GET /hr/leave-types`, `GET /hr/holidays`, `GET /hr/leave/policies`.
- **Dashboard:** `GET /hr/leave/summary`.
- **Requests:**
  - `GET /hr/leave/requests` (filters, `scope`, `escalated`, `awaitingMe`);
  - `GET /hr/leave/requests/{id}`;
  - `GET /hr/leave/requests/estimate`;
  - `POST /hr/leave/requests` (multipart, attachments);
  - `POST /hr/leave/requests/{id}/decision`, `/cancellation` and `/comments`.
- **Approval workflows (H3):** `GET /hr/leave/approval-workflows`, `GET …/options`, `POST`, `PUT …/{id}`.
- **Balances:** `GET /hr/leave/balances`, `GET /hr/me/leave/balances`.
- **Approval inbox (E3):** `GET /hr/approvals`, covering leave, permission, overtime and attendance-correction requests.

**Part B, short requests:** 8 frontend endpoints.
- **Permission requests:** `GET/POST /hr/permission-requests`, `GET /{id}`, `POST /{id}/decision`.
- **Overtime requests:** `GET/POST /hr/overtime-requests`, `GET /{id}`, `POST /{id}/decision`.

**Additions** (no frontend screen; the Q4 decision):
- **HR setup** (`hr.leave-policies:manage`):
  - `/hr/setup/leave-types`;
  - `/hr/setup/leave-policies`;
  - `/hr/setup/holidays`;
  - `/hr/setup/leave-allocations`;
  - `/hr/setup/leave-adjustments`;
  - `/hr/setup/leave-ledger`, the transaction history.
- **Attachment download:** `GET /hr/leave/requests/{id}/attachments/{aid}/content`.
- **Leave settings:** the G6 area `leave` on `/admin/policies/leave`.
- **Notification queue status:** `GET /hr/setup/notification-outbox`.

**Integrations:**
- **Attendance (Module 5):** approved leave sets `on_leave` (and half days); holidays set `holiday`; affected stored days are recalculated; locked payroll periods refuse changes.
- **Worker jobs:**
  - `leave.escalate`, for reminders and escalation;
  - `leave.accrue`, which applies only the rules HR has entered;
  - `notifications.deliver`, the queue to Platform.

**Not in scope:**
- leave reports (contract F), which come in the Reports module;
- encashment (not in the frontend);
- optional holidays;
- partial cancellation;
- sandwich and maximum-consecutive-day rules.

## The owner's decisions

1. **No re-routing.** A request keeps the workflow, approver and escalation settings it was given at submission. Changing or deactivating a workflow affects only new requests (H-Q3).
2. **After escalation, both act; the first valid decision wins.**
   - The original approver, the escalation recipient, and HR (with `hr.leave:approve`, in scope) may all decide.
   - A decision takes a row lock on the request and checks that it is still `pending` and that the `version` matches. The first decision commits.
   - Any later or concurrent decision gets 409: `STALE_VERSION` if the version moved, `INVALID_TRANSITION` if the request is no longer pending.
   - No request can be approved twice, or approved and rejected.
3. **Exceeding the balance is blocked by default** (422 on `leaveTypeId`, with the available balance). The request is accepted only when HR switches on `allowNegativeBalance` in the G6 `leave` policy. The estimate always shows the shortfall as a warning.
4. **Holidays are company-wide or location-specific.**
   - `work_location_id` is optional: empty means every location.
   - An employee gets the company-wide holidays plus those of their own work location.
   - `GET /hr/holidays` returns the caller's applicable holidays, or all of them for HR.
5. **Complete audit history.** Every event is recorded twice: in the request's own append-only history, and in the append-only audit log. That covers:
   - leave applications, decisions (approvals and rejections), escalations, reminders, cancellations and comments;
   - workflow and policy changes;
   - setup changes;
   - every balance transaction.

   The ledger is append-only: balances are never edited, only corrected by new entries with a reason.

## Recommendations applied (pending HR confirmation)

These are the analysis proposals, recorded as items 74–105 in `HR_CONFIRMATION_PENDING.md`.

- **No leave types, policies, entitlements, holidays or workflows are pre-filled.** Every number is entered by HR.
- **Policy applicability:** employment types and/or departments; empty means everyone (L5).
- **Leave year:** the setting `leaveYearStartMonth` (G6 `leave`). Empty means the calendar year, because the frontend asks for balances by `year` (L6).
- **Accrual:** only for policies HR has entered.
  - `annual`: the policy's days are credited once per leave year.
  - `monthly`: the days are credited once per month.
  - Credits apply to employees employed in that period. There is no proration (L7, L8).
- **Carry-forward:** only where a policy allows it, capped at `maxDays`. It is recorded as a ledger entry in the new year. Unused leave of a past year is not counted in the new year (L9).
- **Encashment:** not built (L11).
- **Attachments:** `attachmentAfterDays` is a warning, not a block (L15). File rules follow the frontend constant: `.pdf .jpg .jpeg .png`, 5 MB (L14).
- **Company working days** come from the setting `COMPANY_WORKING_DAYS`, until Platform's company settings are reachable (L18). This is used for the `working_days` escalation unit and for employees without a shift. If it is empty, `working_days` cannot be chosen, and leave for an employee without a shift gets a warning instead of weekly offs being guessed.
- **Started leave:** cannot be cancelled. Partial cancellation is not built (L21).
- **Half-day leave in attendance:** the day shows `half_day` with the leave type (L25, H-Q1).
- **Overtime approval:** uses the Module 5 G5 workflow engine (process `overtime`). Without a published workflow, the contract E rule applies.
- **Permission requests:** follow the contract E rule: HR with `…:approve`, or the reporting manager with `hr.approvals:act`. Never one's own request (L31).
- **Limits:** no limit on permission minutes or overtime is applied (L30).
- **Summary settings:** `lowBalanceThreshold` and `upcomingWindowDays` are settings; empty means no list is shown (L32).
- **Notifications:** queued in `notification_outbox` and delivered to Platform once `PLATFORM_NOTIFICATIONS_URL` and its token are set (L28). The contract has no way to address a role, so role recipients are sent as `roleCodes`, pending Platform's agreement.
- **Approver lists:** the options endpoint lists the roles and users already used in HRMS configuration, until an Identity API exists.
