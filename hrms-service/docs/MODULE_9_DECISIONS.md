# Module 9 (Reports): Decisions and Scope

Recorded 2026-11-05, before implementation. The owner asked for Module 9 to start. The design follows contract
**Part F** and reads the data of Modules 1–8. **No figure is invented:** every report reads stored records or the
same calculations the module screens use, such as the attendance calculation and leave balances.

## Scope: the 5 frontend endpoints

- `GET /hr/reports`: the catalogue of the reports the caller may run;
- `GET /hr/reports/{reportId}`: runs a report;
- `GET /hr/reports/{reportId}/export?format=csv|xlsx`: a file of all matching rows;
- `GET /hr/reports/dashboard`;
- `GET /hr/reports/activity?limit=`.

The 25 report ids of the contract are all built:
- **HR (7):** `employee_directory`, `headcount_by_department`, `joiners_exits`, `employment_type`, `document_completion`, `missing_documents`, `expiring_documents`;
- **Attendance (7):** `daily_attendance`, `monthly_attendance`, `department_attendance`, `late_early`, `absenteeism`, `overtime_summary`, `missing_punch`;
- **Leave (5):** `leave_utilisation_employee`, `leave_utilisation_department`, `leave_balance`, `leave_history`, `upcoming_leave`;
- **Payroll (6):** `payroll_summary`, `payroll_department_cost`, `earnings_deductions`, `lop_summary`, `processing_status`, `payslip_register`.

## Rules from the contract

- **Reports run on the server.** The server applies the filters, sorting and pagination. Totals are computed over **all** matching rows, and the export contains all of them.
- **Columns** are typed `text, code, number, percent, money, date, datetime, time, minutes, status`. Status cells carry the display label.
- **Defaults when a filter is omitted:**
  - date: today;
  - attendance range: the current month to date;
  - leave history: the current calendar year;
  - expiring documents: today to +60 days;
  - upcoming leave: today to +30 days;
  - payroll: the latest calculated period.
- **Range limits:** a range must end on or after its start. Attendance ranges are limited to 92 days (422).
- **Excel** comes from `export?format=xlsx`. Both formats are listed for every report.

**Access:**
- reports follow the organizational scope (A4);
- payroll amounts are only for `hr.payroll:view-amounts`;
- the catalogue lists only the reports the caller may run.

| Category | Needs |
|---|---|
| HR | `hr.reports:view` + `hr.employees:view` (document reports: + `hr.documents:view`) |
| Attendance | `hr.reports:view` + `hr.attendance:view` (overtime summary: + `hr.overtime:view`) |
| Leave | `hr.reports:view` + `hr.leave:view` (balance and utilisation: + `hr.leave-balances:view`) |
| Payroll | `hr.reports-payroll:view` + `hr.payroll:view-amounts`; `lop_summary` and `processing_status` need `hr.payroll:view` instead of view-amounts |

**Dashboard:** each figure is gated by its module permission. A figure the caller may not see is returned as `{value: null, unavailableReason}`.

## Definitions

These are the definitions the frontend assumes (F-Q1). They are built as stated and stay **pending HR/Finance confirmation**; see items 125–127 in `HR_CONFIRMATION_PENDING.md`.

- **Attendance rate** = present ÷ (present + absent), on completed days only. Late arrivals and missing punches count as present. Leave, weekly offs and holidays are excluded.
- **Leave utilisation** = days used ÷ (allocated + carried forward), for leave types that track a balance, in the leave year.
- **Payroll cost** = gross earnings + employer contributions of a calculated period.

**Further choices:**
- **Exit dates (F-Q2)** come from the status-change record, as attendance and payroll use them (Module 5 `exit_dates`).
- **Large exports (F-Q3)** are synchronous. No job is used until volumes require one (pending).
- **Report activity:**
  - a run of page 1 is recorded as `generated`, and every export as `exported`, in a new append-only table `report_activity`;
  - each is also written to the audit log;
  - the activity list shows the entries of the reports the caller may run.
