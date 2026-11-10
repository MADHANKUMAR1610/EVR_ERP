# Module 10 (HR workspace): Decisions and Scope

Recorded 2026-11-05, before implementation. The owner asked for the HR workspace to start. The design follows
contract **B7**. Its task and metric rules are written in the contract as *proposals* (D19, D20). They are built as
stated, and every one is listed as **pending HR confirmation**.

## Scope: the 4 frontend endpoints (read-only)

| Endpoint | Permission |
|---|---|
| `GET /hr/workspace/summary` | `hr.dashboard:view` |
| `GET /hr/tasks?page=&pageSize=&type=&priority=&due=` | any of `hr.dashboard:view`, `hr.employees:edit`, `hr.documents:upload`, `hr.employees:change-status`. Each task type is returned only to users who can do the work |
| `GET /hr/activity?limit=` | `hr.employees:view` |
| `GET /hr/upcoming-events?days=` | `hr.employees:view` |

**No new table:**
- tasks are **derived on read** from the employee data and disappear when the work is done (B7);
- activity is the Module 2 employee history.

Everything follows the caller's organizational scope.

## Summary metrics

| Metric | Built as | Pending |
|---|---|---|
| `totalEmployees` | Employees in a status not marked "employment ended" (the HR status flag of Module 2) | D20 |
| `activeEmployees` | Employees in the statuses listed in the setting `WORKSPACE_ACTIVE_STATUS_CODES` | D20. **Empty by default:** the value is null with a reason until HR names the statuses (the contract's example is `active` + `on_probation`; it is not hard-coded) |
| `presentToday` | Employees whose attendance today is present, late, half day or missing punch | Needs `hr.attendance:view`; otherwise null with a reason |
| `pendingApprovals` | The caller's Approval Inbox total: what they may decide now | Needs `hr.approvals:view`; otherwise null with a reason |

`value: null` always comes with `unavailableReason`; a missing value is never shown as 0.

## Tasks (B7 proposals, pending D19)

| Type | When | Priority and due date | Needs |
|---|---|---|---|
| `employee_record_incomplete` | Any of attendance ID, shift, attendance policy, work location or emergency contact is missing. `missingItems` lists the **labels only, never values** | **high**, due joining + 7 days, for joiners of the last 30 days; otherwise medium, no due date | `hr.employees:edit` |
| `onboarding_documents` | Joining date within ±30 days of today, and no document uploaded | medium, due on the joining date | `hr.documents:upload` |
| `probation_review_due` | Probation applies, no confirmation date recorded, and the end date within 30 days or past | high within 7 days or past; otherwise medium; due on the end date | `hr.employees:change-status` |

**Further rules:**
- Employees whose employment has ended get no tasks.
- **Sort:** earliest due date first (tasks without a due date last), then priority (high first).
- **Filters:**
  - `due=overdue` means a due date before today;
  - `next7` and `next30` mean due from today to +7 or +30 days.
- `counts` covers the caller's whole queue, ignoring filters.

## Activity and events

- **Activity:** the B4 history entries of employees in scope, newest first, with the subject. They carry field names only, never values. `limit` is 1–50.
- **Upcoming events:**
  - joinings with a joining date from today to +`days`;
  - work anniversaries in that window (completed years ≥ 1), for employees in employment;
  - sorted by date; `days` is 1–90;
  - **birthdays are not included** (personal data, D20).
