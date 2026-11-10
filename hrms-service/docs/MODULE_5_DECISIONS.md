# Module 5 (Time & Attendance): Decisions

Recorded 2026-11-03, before implementation, after the owner's review of `MODULE_5_ANALYSIS.md`.
**Status: implemented** (see the Module 5 completion report in `MODULE_REPORTS.md`).

## Name and scope (confirmed)

**Module 5: Time & Attendance** is phase 4b. Its scope is as described in `MODULE_5_ANALYSIS.md` section 1, plus the configurable approval-workflow engine required by decision 1 below:

- shift assignments;
- attendance events and device ingestion;
- the attendance calculation;
- the daily register, day detail, summary, monthly totals, monthly detail, calendar and export;
- attendance corrections with an approval workflow;
- the read-only device list and sync history;
- the HR attendance, shift and overtime settings.

**Frontend endpoints:** 15 new, listed in analysis section 2.1. Shifts were done in Module 1.

**Additions:**
- 6 workflow configuration endpoints from contract **G5**;
- **G6** policies for the `attendance`, `shifts` and `overtime` areas;
- device ingestion;
- device setup;
- attendance period locks.

**Dependencies on Modules 1–4:** analysis section 4. No Module 1–4 table or migration is changed. Migration 0007 only adds tables, plus data: shift-assignment rows copied from `employee.shift_id`.

## Decision 1: correction approval is a configurable workflow

Following the owner's instructions and contract G5:

- **Workflows are configuration, not code.** HR administration uses the G5 endpoints the frontend already calls:
  - `GET /admin/workflow-processes`;
  - `GET/POST/PUT /admin/workflows[/{id}]`;
  - `POST …/{id}/publication` and `POST …/{id}/archive`.

  Saving a published workflow creates a draft (`version + 1`). The published version stays in force until the new one is published. Publishing archives the previous one from the new `effectiveFrom`. Requests in progress keep the version they started with: the steps are copied onto the request.
- **The default workflow** (the owner's proposal) is supplied as a *template* in `setup/reference_data.yaml`, marked pending HR, and loaded like the other setup data. It is not code:
  1. the employee (or HR on their behalf) submits;
  2. the **reporting manager** reviews (a required step);
  3. **HR oversight:** users holding `hr.attendance-corrections:approve` may decide any pending correction at any step (contract E);
  4. **escalation:** a step's `fallback` (a role or a user) and `escalateAfterHours` are HR settings. They are empty in the template, so nothing escalates until HR sets them. The worker escalates overdue steps.
- **If no workflow is published:** the contract E rule applies, which is the same as the default. That is, the reporting manager (with `hr.approvals:act`) for direct reports, or HR with the approve permission.
- **Approvers** (contract E and G5):
  - a step's approver must hold `hr.approvals:act`;
  - `reporting_manager` and `department_head` resolve from the employee record (Module 2) to the caller's `employeeId` claim;
  - `role` means the caller's token has that role code;
  - `user` means the caller's user ID.
- **Steps without an approver:** an optional step with no resolvable approver is skipped (G5). A required step with none waits for HR oversight or escalation, and shows a warning.
- **Nobody may decide their own request**, not even HR (contract E): 403.
- **History:**
  - every action (submitted, approved per step, rejected, escalated, cancelled) is kept in an append-only history, with the actor, time, step and comment;
  - every decision is also in the audit log;
  - a rejection needs a comment;
  - a stale version or a non-pending request returns 409.
- **Scope of execution:** the engine executes `attendance_correction` now. The other processes listed by G5 (`overtime`, `payroll`, `performance_review`) can be configured and published now, and are executed when their modules are built.
- **Validation at publish** (G5): at least one step and one required step; role/user approvers name a value; conditions only on the process's condition fields; fallback and `escalateAfterHours` set together; `effectiveTo` on or after `effectiveFrom`.
- **One G5 rule HRMS can't fully check:** "a role or user approver must name an *active* role or user". The Identity service (other developer) owns roles and users. HRMS checks that a value is given; full checking needs Identity's API (pending, `AUTH_INTEGRATION.md`).

## Decision 2: back-dated shift assignments are off by default

Owner's instructions:

- **Off by default.** The policy area `shifts` has the setting `allowBackdatedAssignments`. It is empty, which means off. With it off, `effectiveFrom` must be today or later (company time zone).
- **When HR switches it on:** a back-dated assignment also needs the permission **`hr.shifts:assign-backdated`**. This is a new code; the Identity service must add it to the permission catalogue, so it is pending. The optional setting `maxBackdatedDays` limits how far back is allowed.
- **A reason is mandatory** for a back-dated assignment (422 on `reason`).
  - *Frontend gap:* the frontend assign dialog has no reason field, so back-dated assignments can only be made through the API until the frontend adds one. The frontend is not modified.
- **Recorded:** every assignment, back-dated or not, writes an append-only change record with:
  - employee;
  - old shift and new shift (in force on the effective date);
  - effective date and back-dated flag;
  - reason;
  - user and time;
  - **affected attendance days** (the dates from the effective date up to the next assignment or yesterday).

  The audit log records the same.
- **Payroll protection:** dates inside a locked period (`attendance_lock_period`) cannot be changed by a back-dated assignment or a correction: 409 `PERIOD_LOCKED`. The payroll module will create these locks when it finalizes a period. Until then, a setup endpoint lets HR with `hr.payroll:approve` record them.
- **Recalculation:** affected days are recalculated by the worker. Stored day records for those dates are refreshed, and the change record lists them.

## Proposals applied (pending confirmation; see `HR_CONFIRMATION_PENDING.md` items 45–70)

- **A11:** one company-wide set of attendance rules (one G6 document per area). Named attendance policies are labels only for now.
- **D2:** mobile-app attendance is out of scope. Ingested `mobile_app` events are refused, and `mobileValidation` is never invented.
- **Every threshold starts empty.** A rule stays off until HR sets it; nothing is invented:
  - half day, absent below, break deduction;
  - correction window;
  - duplicate window, delayed-sync threshold;
  - overtime minimum, rounding and cap;
  - back-dating.

  Where a missing setting matters to a day, the day carries a warning.
- **Grace period:** the shift's own `graceMinutes` (Module 1) is used. There is no separate company default.
- **Late and early-exit minutes** are measured from the end of the grace period and from the shift end. Both are pending HR (A4).
- **Overtime eligibility:** overtime is calculated only when the `overtime` policy is switched on, and only for employees with an overtime policy option assigned. Pending HR (A7).
- **Overnight punches** belong to the shift's start date (E-Q2). A missing punch on the current day is not an exception before the shift ends (E-Q1).
- **Leave and holidays:** `on_leave` and `holiday` never appear until the leave module exists. The calendar counts for them are 0.
