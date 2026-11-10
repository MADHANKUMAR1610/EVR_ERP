# Module 7 (Payroll): Decisions and Scope

Recorded 2026-11-05, before implementation. The owner asked for the 30 missing payroll endpoints to be built
("please build this api's"). The design follows decision **Q3** in `ANALYSIS.md` (approved), together with the owner's
standing rules: **no invented business rules, statutory rates or entitlements; everything HR-entered and configurable;
unresolved items marked pending.**

## Scope: the 30 frontend endpoints (contract E4 and H4)

**Periods:**
- list, summary;
- validation (POST and GET), inputs, calculation;
- results, and the result of one employee;
- submission, decision, payslip publication.

**Configuration:**
- salary components, salary structures;
- employee salaries (list and detail).

**Payslips and register:**
- payslips (all, and `/hr/me/payslips`), the payslip PDF;
- the register report and its export.

**Configurations and assignments (H4):**
- list, options, create and update;
- assignment list, preview, create and end;
- the effective configuration;
- assignment history.

**Additions** (the frontend has no screen to enter them; HR setup, as in Modules 1–6):
- `/hr/setup/salary-components`, `/hr/setup/salary-structures`, `/hr/setup/employee-salaries`, `/hr/setup/payroll-periods`;
- G6 policy area `payroll` on `/admin/policies/payroll`, which needs `admin:policies.payroll-manage`.

## How pay is calculated (Q3: formula types and HR-entered values)

**Salary components** are created by HR. Each has one formula type:

| Formula type | Meaning | Values entered by HR |
|---|---|---|
| `fixed` | A monthly amount per employee | The amount on each employee's salary record |
| `percent` | A percentage of a base: gross, or a list of other components | The rate; optional cap on the base; optional maximum amount |
| `balance_of_gross` | The employee's monthly gross minus all other earnings (for example "special allowance") | The employee's monthly gross on the salary record |
| `overtime_rate` | An amount per approved overtime hour | The rate per hour, on the component or per employee |
| `slab` | An amount, or a rate, from a table chosen by the base amount (for example professional tax) | The slab table: from, to, amount or rate |

**Nothing is pre-filled:** no component, rate, ceiling, slab or structure exists until HR enters it. This covers
statutory items (PF, ESI, professional tax, TDS): they are ordinary components flagged `statutory`, and HR enters
their rates and slabs. **Income-tax (TDS) projection is not built**: a slab on monthly pay is all the engine offers,
and the real TDS method is pending Finance.

**Salary structure:** an ordered list of components.

**Employee salary record:** the structure, the effective date, the monthly gross and the per-employee amounts or
rates. Revisions are **new records**; history is kept and never edited.

**Calculation, per employee, in structure order:**
- earnings first, then deductions, then employer contributions;
- `percent` and `slab` components may use components calculated before them (dependency order is checked when a structure is saved);
- amounts are kept as decimals and rounded to 2 places, half up (pending Finance);
- **net = earnings − deductions**; employer contributions are reported, not deducted.

**Proration (paid days):**
- earnings of `fixed`, `percent` and `balance_of_gross` components are multiplied by paid days ÷ days in period, when the component is marked `prorate` (an HR choice per component);
- overtime and slab amounts are not prorated.

## Inputs from attendance and leave

| Input | Source | Rule |
|---|---|---|
| Days in period | The **G6 `payroll` setting `prorationBasis`**: `calendar_days`, `working_days` (the employee's shift, minus holidays) or `fixed_days` (with `fixedDaysPerMonth`) | **Empty: calculation is blocked** by a validation check; the basis is never guessed |
| Loss of pay | Approved leave of types with `paid = false` (their charged dates); plus attendance `absent` days (1) and `half_day` days without leave (0.5), **only when** the G6 setting `absenceIsLossOfPay` is on | Empty setting: absences are not loss of pay |
| Paid days | Days in period for the dates employed (joiners and leavers) − loss of pay | — |
| Leave days | Approved paid leave days in the period | — |
| Overtime | **Approved** overtime requests in the period (minutes) | Paid only through an `overtime_rate` component, and only when the effective configuration allows overtime (or, without one, when the employee has an overtime policy assigned) |

## Period workflow (contract E4)

```
open → validated → calculated → submitted → approved → payslips_published
                          ↑            │
                          └─ rejected ←┘   (rejected returns to validation)
```

- **Periods are created by HR** with their month and **currency**, through `/hr/setup/payroll-periods`. There is no default currency.
- **Only monthly periods are calculated** (H-Q5). Configurations may record other frequencies, but those are not calculated yet (pending).
- **Validation**:
  - runs the checks below; `canCalculate` is false when any check is blocking;
  - moves the period to `validated` and discards earlier results.
- **Calculation** is synchronous (E-Q6) and stores the results.
- **Approval**:
  - the approver must differ from the submitter unless HR switches on the G6 setting `allowSelfApproval` (E-Q5, pending);
  - rejection needs a reason.
- **On approval:**
  - attendance for the period is stored and **locked** (the Module 5 `attendance_lock_period`);
  - the period can no longer change, and is never recalculated.
- **Publication** creates the payslips that employees see.
- Every step goes into the period history and the audit log; a stale version returns 409.

**Validation checks:**

| Check | When it is blocking or a warning |
|---|---|
| `payroll_policy` | Blocking when the proration basis is not set |
| `components` | Blocking when a component used by any salary is incompletely configured: a `percent` without a rate or base, a `slab` without slabs, an `overtime_rate` without a rate |
| `configuration_conflict` | Blocking: two assignments at the same level (H4: the backend must not choose) |
| `missing_salary` | Warning: those employees are listed with exception `missing_salary` and no amounts |
| `missing_configuration` | Warning: the employee's salary structure is used as is |
| `attendance_exceptions` | Warning: missing punches or absences in the period |
| `pending_requests` | Warning: leave, permission, overtime or correction requests in the period still pending |
| `working_calendar` | Warning: `working_days` basis, but an employee has no shift and company working days are not set |

**Result exceptions:**
- `missing_salary`, `attendance_exceptions`, `pending_requests`;
- `prorated`: joined or left mid-period;
- `large_change`: net differs from the previous period by more than the G6 `largeChangePercent`; empty means never flagged.

## Access

| Permission | Allows |
|---|---|
| `hr.payroll:view` | Periods, summary, inputs, results, components, structures, configurations, assignments |
| `hr.payroll:view-amounts` | **Amounts are null without it.** Employee salaries also need it |
| `hr.payroll:process` | Validate, calculate, submit, publish; create periods |
| `hr.payroll:approve` | Decide |
| `hr.payroll-config:manage` | Configurations, components and structures |
| `hr.payroll-assignments:manage` | Assignments |
| `hr.payroll-config:manage` + `hr.payroll:view-amounts` | Employee salary records (setup) |
| `hr.payslips:view` | All payslips, in scope |
| `hr.self:view-payslips` | Own payslips |

The payslip PDF is for payslip viewers, or the payslip's own employee. The register needs `hr.reports-payroll:view`
and view-amounts. Employee rows follow the organizational scope (Module 2).

## Configurations and assignments (H4), as specified

- No formulas or amounts are stored on configurations.
- Code: 2–12 characters, unique.
- At least one earning; overtime eligible requires a policy.
- A configuration with current or future assignments cannot be deactivated.
- Assignments are never edited, only ended; every create and end is written to the history and the audit log.
- Overlaps for the same target are refused.
- Changes reaching into an approved or published period are refused.
- A change inside a period in progress needs `confirmPeriodInProgress`.
- Effective configuration: employee, then department, then company; two at the same level is a conflict.

**How the calculation uses the configuration:**
- the configuration's components limit which of the structure's components are calculated;
- its overtime flag decides whether overtime is paid.

## Pending (added to `HR_CONFIRMATION_PENDING.md`)

- Every component, rate, ceiling, slab, structure and salary.
- The proration basis and fixed days.
- Whether absences are loss of pay.
- Rounding.
- The large-change threshold.
- Self-approval.
- The currency per period.
- Non-monthly frequencies.
- TDS method.
- Payslip layout. The PDF is a plain layout with the employee, period, days and component lines; it has no company name or logo, because those belong to Platform's company settings.
- Bank transfer files (not built; disbursement is outside the system, E4).

## Implementation notes (2026-11-05, recorded while building)

Choices made where the approved design was silent. Each is listed in `HR_CONFIRMATION_PENDING.md` (items 106–117) where it affects pay.

- **Policy values in force:** the G6 payroll policy in force on the day of validation and calculation is used. Policy changes take effect from today or later, so the policy as it was at a past period's end could otherwise be empty. Approved periods are never recalculated.
- **Salary revisions inside a period:** the salary record in force on the employee's last day in the period applies to the whole period. A revision is not split by date (pending).
- **Fixed-days basis for joiners and leavers:** the fixed days times the share of calendar days employed (pending).
- **Inactive components** are not calculated. When a configuration applies and lists components, only the structure components it lists are calculated.
- **Balance of gross** never counts overtime. Overtime is paid on top of the monthly gross.
- **Full-month amounts:** percentage and slab components work out their full-month amount from the full-month base. Example: HRA is a percentage of the unprorated basic pay when the balance of gross is computed. The paid amount uses the period amounts.
- **Scope:**
  - calculation covers every employee in the period;
  - lists, the summary, payslips and the register show only the caller's organizational scope.
- **Validation:**
  - a period with a blocking check stays `open`;
  - a successful validation moves it to `validated`;
  - recalculating a `calculated` period is allowed.
- **Calculation** re-runs the checks; a blocking check gives 422 with one detail per check.
- **Approval:**
  - attendance is first stored (`store_days`), then locked with an `attendance_lock_period` for the whole period;
  - a lock that already covers the period is reused;
  - approving needs a period that has ended (409 otherwise).
- **Payslips:**
  - publishing creates one payslip per result with a salary;
  - the PDF is for the payslip's own employee (`hr.self:view-payslips`), or for `hr.payslips:view` in scope together with `hr.payroll:view-amounts`;
  - other employees' downloads are audited.
- **Register export:** CSV by default; `format=xlsx` gives Excel. It has one row per employee with one column per component, and every export is audited.
- **Employee salary lists** need `hr.payroll:view-amounts` (contract E4).
