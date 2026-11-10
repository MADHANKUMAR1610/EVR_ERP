# Module 4 (Employee Import): Decisions

Recorded 2026-11-03, following the owner's Module 4 instructions:
- follow the frontend contract;
- support Excel and CSV, with a template;
- validate every row before importing, with a preview and summary;
- detect duplicates according to the real database constraints;
- give row-level reasons;
- process large imports in the background, with tracked progress;
- enforce permissions and organizational scope;
- audit the import;
- never skip rows silently or import partially without reporting it;
- use transactions, with a documented strategy for partial failures;
- invent no mandatory fields or policies.

## Following the frontend contract (B6)

In the frontend, the browser reads the `.xlsx` or `.csv` file, maps its columns and sends the rows
to the backend as JSON. All four contract endpoints are implemented exactly as specified:

| Endpoint | Behaviour |
|---|---|
| `GET /hr/employee-imports/fields` | The import columns. The frontend builds its template and column mapping from this list and never hard-codes the columns. |
| `POST /hr/employee-imports/validate` | Checks every row and returns `valid`, `warning`, `duplicate` or `error`, with messages per field. **Saves nothing**, as the contract requires: no data and no audit entry. Adds a `summary` with the totals, which the frontend ignores. |
| `POST /hr/employee-imports` | Returns 202 with a queued job. **Every row is checked again when it is imported**, because the data may have changed since the preview. |
| `GET /hr/employee-imports/{jobId}` | Status, progress, counts (`created`, `skipped`, `failed`) and per-row failures. Only the job's owner can see it; anyone else gets 404. |

**Additions for other API clients and integrations** (the frontend doesn't need them):

| Endpoint | Purpose |
|---|---|
| `GET /hr/employee-imports/template?format=xlsx\|csv` | A downloadable template built from the same column list. The `.xlsx` version has an "Instructions" sheet explaining each column. |
| `POST /hr/employee-imports/file-rows` (`multipart`, `file`) | Reads a `.xlsx` file (first worksheet) or a `.csv` file on the server into the same rows. It maps columns by label, key or alias (the frontend's rule) and stores nothing. |
| `GET /hr/employee-imports/{jobId}/failures.csv` | Failed and skipped rows with their reasons, for the owner only. Any cell that a spreadsheet would treat as a formula is neutralised. |

## Columns and required fields

- **Columns:** the 15 columns are the contract's proposed template (R5, pending HR approval).
- **Required fields — no new rules invented.** A column is required exactly when the employee form requires that field (Module 2, contract B4): Employee ID, First name, Joining date, Department, Designation, Employment type and Employment status. Every row goes through **the same validator as the Add-employee form**, so the import and the form can never disagree.
- **Matching configured values:** values for department, designation and the other configured lists match an item's code or name, ignoring case. A value that matches two items must use the code. The employment status must be one allowed for new employees.
- **Reporting manager:** must be an existing employee's code. A row without one is imported with a **warning**, as in the contract's example.
- **Contact columns (mobile, email):** offered and accepted only from users with `hr.employees:view-contact`, the same rule as the form.
- **Template examples:** taken from the company's own configuration (for example, the first configured department), never from invented values.

## Duplicate detection (matches the database constraints)

| Column | Database constraint | Checked against |
|---|---|---|
| Employee ID | unique, ignoring case (`uq_employee_code_lower`) | existing employees and earlier rows of the file |
| Email | unique when present, ignoring case (`uq_employee_contact_email_lower`) | existing employees and earlier rows |
| Attendance ID | unique when present, exact (`uq_employee_attendance_id`) | existing employees and earlier rows |

- **Status:** a row whose only errors are duplicates is `duplicate`; any other error makes it `error`. The worst status wins.
- **`skipDuplicates: true`:** duplicate rows are **skipped and listed**, each message prefixed "Skipped:".
- **`skipDuplicates: false`:** duplicate rows are counted as failed.
- **Two imports at once:** if two imports race, the database constraint decides, and only that one row fails, with an explanation.

## Background processing and the transaction strategy

- **The job:** `POST` stores the job (status `queued`) and returns at once. The worker (`python -m app.worker`) runs it.
- **Claiming jobs:** several workers can run. Each job is claimed with `FOR UPDATE SKIP LOCKED`, and the worker sends heartbeats while it works.
- **Batches:** rows are processed in file order, in batches of `IMPORT_BATCH_SIZE` (50).
- **One row at a time:** each row is inserted in **its own savepoint**. A failing row (validation or a database constraint) is rolled back alone and recorded with its reasons; it never affects the other rows.
- **Each batch** is committed in one transaction **together with** the job's progress, counts and failures. The stored counts therefore always equal what is in the database, and a database check enforces `created + skipped + failed = processed`.
- **Worker stops:** committed batches stay. Another worker takes the job over once its heartbeat is older than `WORKER_STALE_SECONDS` and **resumes after the last committed row**, so no row is imported twice.
- **Unexpected error:** the job ends as `failed`, with its counts and a plain message, for example "The import stopped unexpectedly after 2 of 5 rows. 2 employee(s) were created and are kept; the remaining 3 row(s) were not imported…". A partial import is never silent.
- **Outcome is always shown:** every finished job reports `summary` counts, including a job that failed part-way.
- **Owner's identity:** each employee is created **as the job owner**, with the owner's permissions and current organizational scope, and recorded exactly like an employee added through the form: history action `imported`, audit `employee.imported`, reporting line.
- **Personal data:** the submitted rows are cleared from the job when it finishes; the counts and failure reasons are kept.

## Permissions, scope and audit

- **Permission:** every import endpoint needs `hr.employees:import`; refusals are audited.
- **Scope:** the organizational scope (Module 2, Q12) applies to each row. A row that would place an employee outside the importer's scope is an error. A user without a scope assignment can import nothing.
- **Audit entries:**
  - `employee_import.started` (row count, skipDuplicates);
  - `employee.imported` for each employee;
  - `employee_import.completed` (counts);
  - `employee_import.failed`;
  - `employee_import.file_read`;
  - `employee_import.report_downloaded`.

## Files

- **Formats:** `.xlsx` (first worksheet only) and `.csv` (UTF-8, with or without a byte-order mark). The old `.xls` format is refused with advice to save as `.xlsx` or `.csv`, as the frontend does.
- **Size limits** (the contract's proposals, configurable): 5 MB per file (413 above it) and 2,000 rows per import.
- **`.xlsx` safety:**
  - it must be a real ZIP file;
  - the unpacked size (50 MB) and entry count (1,000) are checked before opening, which blocks zip bombs;
  - it is read in read-only mode with `defusedxml`, which blocks XML entity attacks;
  - only cell values are used, never formulas or macros.
- **Dates:** `YYYY-MM-DD`, `DD-MM-YYYY`, `DD/MM/YYYY`, `DD.MM.YYYY` and native Excel date cells. An impossible date such as 30/02 is reported, not dropped.

## Still requiring HR, management or IT confirmation

These are added to `HR_CONFIRMATION_PENDING.md` as items 40–44.

| # | Item | Who |
|---|---|---|
| 40 | The import columns (the contract's proposed template, R5), and whether more fields (e.g. probation, shift, statutory IDs) should be importable | HR |
| 41 | Limits per import: 2,000 rows and 5 MB (`IMPORT_MAX_ROWS`, `IMPORT_MAX_FILE_BYTES`) | HR + IT |
| 42 | Whether a missing reporting manager should stay a warning (contract example) or be required | HR |
| 43 | Whether other HR users (not only the owner) may see someone's import jobs (contract: "the job owner, or per policy") | Management |
| 44 | Accepted date formats (contract proposal) | HR |
