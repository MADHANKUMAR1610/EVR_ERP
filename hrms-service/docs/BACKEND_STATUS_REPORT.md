# HRMS Backend: Technical Status and Readiness Report

**Date:** 2026-11-05. **Scope:** the separate `hrms-service` project (FastAPI + PostgreSQL), Modules 1–6 and the
foundation. **Method:** review of the source, tests, configuration, documentation and ZIP artifacts, and a fresh
verification run on the review date. No frontend or backend code was changed by this review. The only files added
are this report, `API_ENDPOINT_CATALOG.md`, `PENDING_DEPENDENCIES.md`, `DEPLOYMENT_CHECKLIST.md` and the generated
`openapi.json` snapshot.

Companion documents:
- `API_ENDPOINT_CATALOG.md`: every implemented endpoint, generated from the route table.
- `PENDING_DEPENDENCIES.md`: every open decision or dependency, by owner.
- `DEPLOYMENT_CHECKLIST.md`: what production needs, and what is still missing.

## Verification run on the review date (2026-11-05)

| Check | Result |
|---|---|
| Full test suite (`pytest`, real PostgreSQL 16) | **188 passed, 0 failed, 0 skipped** (230 s) |
| Contract check against the frontend (`tools/verify_contracts.py`) | **90 of 90** response/input shapes and **90 of 90** frontend routes match |
| Migration state | head `0008`; `alembic check`: no drift between models and migrations |
| Migration fingerprints (`0001`–`0008`) | 8 of 8 match the shipped versions |
| Source compared with `hrms-service-module6.zip` | byte-for-byte identical (no change since the Module 6 delivery) |
| Unauthenticated endpoints | only `/health`, `/health/ready` and device ingestion (device API key), as designed |

Most recent fresh-database migration cycle and worker run: 2026-11-04, during Module 6 (`MODULE_REPORTS.md`).
They were not repeated in this review because no code has changed since.

---

## 1. Module implementation status

The foundation (Phase 3) and Modules 1–6 are complete. Each followed the cycle analysis → owner approval →
decisions document → implementation → tests, migrations and contract check → ZIP → completion report.

### Foundation (Phase 3)

- **Functionality:**
  - configuration from environment variables only;
  - the error envelope and request IDs;
  - JSON logs;
  - JWT verification with session revocation;
  - permission guard with denial audit;
  - CSRF origin check;
  - audit columns filled on every write;
  - append-only audit log;
  - optimistic concurrency;
  - paging;
  - health checks.
- **Endpoints:** `GET /health`, `GET /health/ready`.
- **Tables:** `audit_log` (append-only by trigger).
- **Tests:** 22 (`test_foundation.py`).

### Module 1: Organization and reference data

- **Functionality:**
  - departments, designations and shifts, with stable codes;
  - reference lists: employment types, work locations, employee statuses and transitions, attendance and overtime policy options, document categories and types, payroll field definitions;
  - generic HR setup for reference lists;
  - the YAML setup loader, which refuses unconfirmed data in production.
- **Endpoints:** 31 (19 called by the frontend). See the catalog.
- **Tables:**
  - `department` (self-reference parent; head → `employee`);
  - `designation`, `designation_department`;
  - `shift`, `shift_department`;
  - `employment_type`, `work_location`;
  - `employee_status`, `employee_status_transition`;
  - `attendance_policy_option`, `overtime_policy_option`;
  - `document_category`, `document_type`;
  - `payroll_field_definition`.

  Codes and keys cannot change (trigger, migration `0003`).
- **Authorization:**
  - `admin:organization.*` for departments and designations, `hr.shifts:*` for shifts, `hr.settings:*` for setup;
  - each reference list is limited to the permissions of the screens that use it (`app/core/reference_access.py`), returns minimal fields, and audits refusals.
- **Tests:** 38 (organization 11, reference access 14, reference data 8, loader 5).

### Module 2: Employees

- **Functionality:**
  - employee directory, detail, create, update and lookup (picker);
  - history;
  - status changes with transition rules;
  - reporting lines;
  - role-based organizational scopes;
  - encrypted bank details.
- **Endpoints:** 12 (9 called by the frontend).
- **Tables:**
  - `employee` → department, designation, employment type, status, manager (self), work location, shift, policy options;
  - `employee_contact`;
  - `employee_payroll_value`, encrypted where the field is sensitive;
  - `employee_history` (append-only);
  - `employee_reporting_line`;
  - `employee_access_scope`.
- **Authorization:**
  - `hr.employees:*`;
  - contact fields need `view-contact`, payroll and bank fields `view-sensitive` (masked);
  - the organizational scope (all, departments, headed departments, reporting tree, own record) applies to every query, and out of scope returns 404.
- **Tests:** 29.

### Module 3: Employee documents

- **Functionality:**
  - upload, list, download and checklist;
  - compliance list, summary and attention;
  - document settings (expiry window).
- **Endpoints:** 9 (7 called by the frontend).
- **Tables:** `employee_document`, `employee_document_event` (append-only), `document_settings`.
- **Security:**
  - content checked against the extension (PDF, JPEG, PNG);
  - size limits and malware scan (ClamAV, fails closed);
  - Fernet-encrypted private storage with no public URLs;
  - download headers: `no-store`, `nosniff`, sandbox CSP;
  - downloads and refused uploads are audited.
- **Tests:** 25.

### Module 4: Employee import

- **Functionality:**
  - template (XLSX or CSV) and reading files into rows;
  - validation preview with row errors and duplicate checks;
  - import jobs run by the background worker, with progress, resume and failure export.
- **Endpoints:** 7 (4 called by the frontend).
- **Tables:** `employee_import_job`.
- **Tests:** 19.

### Module 5: Time and attendance

- **Functionality:**
  - **Shifts:** dated shift assignments (back-dating off by default, needs a setting, a permission and a reason).
  - **Punches:** device registry, API keys and punch ingestion (hashed key).
  - **Calculation:** a pure calculator.
  - **Registers:** daily, monthly, export (CSV or XLSX), day and month detail, calendar.
  - **Corrections:** with configurable G5 approval workflows.
  - **Settings and locks:** G6 policies (attendance, shifts, overtime; all empty by default); payroll period locks.
  - **Worker:** generic background job queue.
- **Endpoints:** 32 (25 called by the frontend, including the G5 and G6 administration endpoints).
- **Tables (13):**
  - `policy_setting`, `workflow`, `workflow_history`;
  - `shift_assignment`, `shift_assignment_change`;
  - `attendance_device`, `device_sync_run`, `attendance_event`, `attendance_day`;
  - `attendance_correction`, `attendance_correction_event`;
  - `attendance_lock_period`, `background_job`.

  Four are append-only.
- **Tests:** 28 (12 calculator).

### Module 6: Leave management, including Part B

- **Functionality:**
  - leave types, policies, holidays (company-wide or per location), allocations, adjustments and an append-only ledger;
  - estimate and application with attachments;
  - H3 approval workflows with routing fixed at submission;
  - escalation and reminders;
  - first-valid-decision locking; cancellation with reversal; comments;
  - balances, summary and the approval inbox across 4 request types;
  - permission and overtime requests (Part B);
  - accrual and carry-forward of HR-entered policies;
  - the notification outbox;
  - the attendance overlay for leave and holidays.
- **Endpoints:** 41 (26 called by the frontend).
- **Tables (13):**
  - `leave_type`, `leave_policy`, `holiday`;
  - `leave_ledger_entry`;
  - `leave_approval_workflow`, `leave_workflow_history`;
  - `leave_request`, `leave_request_attachment`, `leave_routing_event`, `request_event`;
  - `permission_request`, `overtime_request`;
  - `notification_outbox`.

  Four are append-only, and `leave_type.code` cannot change.
- **Tests:** 27, including a real two-connection concurrency test and a 1,000-employee test.

### Validation and error handling (all modules)

- **One envelope** for every non-2xx response: `{ "error": { "code", "message", "details": [{ "field", "message" }] } }`.
- **Codes:**
  - `BAD_REQUEST` 400, `UNAUTHENTICATED` 401, `FORBIDDEN` 403, `CSRF_REJECTED` 403, `NOT_FOUND` 404;
  - `CONFLICT`, `STALE_VERSION`, `INVALID_TRANSITION`, `PERIOD_LOCKED` and `DUPLICATE`, all 409;
  - `LENGTH_REQUIRED` 411, `PAYLOAD_TOO_LARGE` 413;
  - `VALIDATION_FAILED` 422, including the more specific `WORKFLOW_CONFLICT` and `POLICY_IN_USE`;
  - `SERVICE_UNAVAILABLE` 503;
  - a safe 500 that never shows internals.
- **Field messages** repeat the frontend form messages word for word, and field paths are camelCase.
- **Database errors** are never echoed. Unique and foreign-key violations become 409 envelopes.
- **Optimistic concurrency:** every editable record carries a `version`. A stale write gets 409 `STALE_VERSION`.

### Known defects and incomplete functionality

**No open defects:** no failing or skipped tests. Bugs found during each module's verification were fixed and are
listed in the module reports.

**Not built yet, but called by the frontend (HRMS-owned):**
- 54 endpoints:
  - payroll (30);
  - performance (15);
  - reports (5);
  - the HR workspace: summary, tasks, activity, upcoming events (4).
- The G6 policy areas `payroll` and `performance` return 404 until their modules exist.

**Incomplete by design, waiting on decisions:**

| Item | Module | Waiting on |
|---|---|---|
| Document verify/reject workflow; document deletion and retention | 3 | HR + management (D24), Legal (R4) |
| `photoUrl` is always null | 2 | contract D16 |
| Platform reads HRMS audit events (`GET /hr/internal/audit-events`, proposed in `AUTH_INTEGRATION.md`) | foundation | Platform agreement; **not built** |
| Back-dated shift assignment from the UI | 5 | the frontend has no reason field |
| Overtime step approvers of type role or user see their requests in the inbox and detail, not in the overtime list | 6 | none: known limit |
| A pending leave request of a past leave year that is approved after the year end can make that year negative | 6 | HR (item 105) |
| Leave reports, encashment, optional holidays, partial cancellation, sandwich and maximum-consecutive-day rules | 6 | out of scope by decision |

**Operational gaps found in this review:**
1. **No CORS middleware.** `ALLOWED_ORIGINS` is used only for the CSRF check, although the config comment also says CORS.
   - This is correct for the intended same-origin deployment: one public URL with the proxy routing `/api/v1/hr/…` to HRMS, and the frontend's default `VITE_API_BASE_URL=/api/v1`.
   - A cross-origin setup would fail until CORS is added.
2. **No deployment files.**
   - There is no Dockerfile, docker-compose file, Nginx configuration or service unit. Only `.dockerignore` exists.
   - `AUTH_INTEGRATION.md` refers to a `deploy/nginx.conf` that does not exist.
3. **No cleanup jobs:**
   - for `background_job` rows (about 125 a day from scheduling);
   - for delivered notifications;
   - for orphaned encrypted files (Module 3 known limit).
4. **No rate limiting in HRMS.** Login is Identity's. Device ingestion is limited only by its API key and request size.
5. **No security headers from the application** (HSTS, X-Frame-Options, etc.); the reverse proxy must add them.
6. **Production does not require** `AUTH_JWT_ISSUER`, `AUTH_JWT_AUDIENCE` or `AUTH_REVOCATION_URL`. They are verified when set, so they belong on the deployment checklist.
7. **Small documentation inconsistencies:**
   - the header of `HR_CONFIRMATION_PENDING.md` lists items only up to 73;
   - item 54 still says leave days are 0, which is no longer true since Module 6.

   The tables themselves are correct.

None of these affect the tested behaviour. They are listed so that they are not assumed resolved.

---

## 2. Overall backend architecture

| Aspect | Implementation |
|---|---|
| Framework | **FastAPI 0.129.2** on **Python 3.13** (README states 3.12+), served by **uvicorn 0.32.1** (`uvicorn app.main:app --workers 2 --proxy-headers`) |
| Validation | **Pydantic 2.14** with camelCase JSON (`CamelModel`); request models refuse unknown fields |
| Database and ORM | **PostgreSQL** (tested on 16; README requires 14+), **SQLAlchemy 2.0.55 async** with **asyncpg 0.30**, migrations with **Alembic 1.14** (8 revisions, 51 tables). Nothing is created at startup |
| Code structure | Controllers per business concept (`app/api/controllers`), services (`app/services`), repositories (`app/repositories`), models and schemas |
| Authentication | Verifies the **Identity service's JWT** from the `evr_session` cookie or a Bearer header: RS256 public key or JWKS (cached), issuer, audience, expiry and leeway, then a **session revocation** check against Identity (cached; fails closed when the cache is stale). Claim names are configurable. Development mode accepts HS256 tokens signed with `AUTH_DEV_SECRET` and is refused in production |
| Permissions | The frontend's catalogue (`app/core/permissions.py`: `hr.*`, `admin:*`), matched with the same rules (`*`, `module:*`). `require(...)` guards endpoints and audits every denial. Record- and field-level rules are applied in the services: organizational scope, own record, assigned approver, sensitive and contact fields, no self-approval |
| API structure | Prefix **`/api/v1`** (the frontend's base URL). HRMS serves `/api/v1/hr/…` and the HRMS-owned `/api/v1/admin/…` paths (departments, designations, reporting lines, workflows, policies). Paging uses `page` and `pageSize` ∈ {10, 25, 50, 100} with `sort=field:dir`, returning `{ items, meta }`. Versioning is by path prefix; there is no other version scheme |
| Background jobs | `python -m app.worker`: a polling worker with `FOR UPDATE SKIP LOCKED` claims, heartbeat, take-over of stale jobs and graceful SIGTERM. Two queues: `employee_import_job`, and `background_job` with dedupe keys. Scheduled job types: `attendance.close_day`, `attendance.recalculate`, `shift.sync_current`, `workflow.escalate`, `leave.escalate`, `leave.accrue`, `notifications.deliver` |
| File storage | Private directory `STORAGE_DIR`. Files are named by random keys, written atomically with mode 0600, encrypted, and never exposed as URLs. They are only served through permission-checked endpoints, which verify a SHA-256 checksum |
| Encryption | **Fernet (AES-128-CBC + HMAC-SHA256)** through `MultiFernet`, with key rotation: `PAYROLL_ENCRYPTION_KEYS` for sensitive payroll values such as bank accounts (with a rotation script), and `DOCUMENT_ENCRYPTION_KEYS` for documents and leave attachments. No keys are kept in the source or the ZIPs |
| Notifications | **Transactional outbox** (`notification_outbox`), written in the same transaction as the change. The worker posts to Platform's `POST /internal/notifications` with retries and exponential backoff, once `PLATFORM_NOTIFICATIONS_URL` and `PLATFORM_SERVICE_TOKEN` are set. Until then notifications stay queued and their status is visible |
| Audit | Audit columns on every business table, filled by a flush listener (a write without an actor is refused). An append-only `audit_log`, enforced by trigger, with sensitive values masked. Module histories are append-only by trigger |

---

## 3. Frontend integration readiness

| Question | Answer |
|---|---|
| Consistent response format? | **Yes.** The same error envelope, camelCase fields, `{items, meta}` paging, ISO dates and UTC date-times with `Z`, for every endpoint. Verified by the contract check: 90 shapes |
| Does authentication work with the frontend? | **Compatible, but needs Identity.** HRMS reads the same session cookie the frontend sends (`credentials: 'include'`), and its CSRF check is built for the frontend, which sends no CSRF token. **Login, logout and session are Identity endpoints, which are not built here.** A real end-to-end sign-in needs Identity to issue the agreed JWT (`sub`, `name`, `sid`, `employeeId`, `roles`, `permissions`; `AUTH_INTEGRATION.md`). Until then only development-mode tokens work, and those have been tested |
| API documentation? | **Yes.** Swagger at `/docs` and `/openapi.json` when `DOCS_ENABLED=true` (off in production). Also a snapshot in `docs/openapi.json` (108 paths), `API_ENDPOINT_CATALOG.md`, `API_MAPPING.md` (all 178 frontend calls, with owner and status) and `ER_DIAGRAM.md` |
| CORS and environment ready? | **Same-origin: yes.** The frontend defaults to `/api/v1`, using the Vite dev proxy locally (`DEV_PROXY_TARGET`) and the reverse proxy in production. **Cross-origin: no.** There is no CORS middleware. `.env.example` documents every variable; production refuses unsafe settings |
| Ready to integrate now | The **90** frontend calls of Modules 1–6: organization and reference data (19), employees (9), documents (7), import (4), attendance with workflows and policies (25), leave and requests with the approval inbox (26). The list is in `API_ENDPOINT_CATALOG.md` (rows marked ✅) |
| Still needing changes or work | The **54** unbuilt HRMS endpoints (payroll, performance, reports, HR workspace). The G6 `payroll` and `performance` areas. The other services' endpoints (Identity 16, Platform 13, Manufacturing 5), which HRMS does not own. No changes to integrated endpoints are known to be needed. Two frontend-side gaps exist, which the frontend team decides: no reason field in the shift-assign dialog, and no document verify screen until D24 |

Data prerequisites before real users see anything:
- **Organizational scopes:** management must assign role scopes. With none assigned, nobody sees employee records.
- **Real setup data:** HR must replace the sample reference data, then mark the setup file as confirmed.
- **Leave setup:** HR must enter leave types, policies and holidays. None are pre-filled.

---

## 4. Security readiness

| Area | Implemented and tested | Requires production configuration or another team |
|---|---|---|
| Authentication and sessions | JWT signature, expiry, issuer and audience when configured; revocation check with cache that fails closed; cookie or bearer; development mode refused in production; secrets never logged | Identity's public key or JWKS URL (required by the production check). **Set issuer, audience and revocation URL** (not enforced by the check). Identity must issue tokens with the agreed claims |
| CSRF | Origin/Referer check on cookie-authenticated writes | `ALLOWED_ORIGINS` set to the real frontend origin (required in production) |
| Roles and permissions | Guard on every endpoint; denials audited; record-level checks; no self-approval; out-of-scope returns 404 | Identity owns roles. It must add `hr.shifts:assign-backdated` and grant permissions. **Management must assign organizational scopes** |
| Employee data privacy | Scoped queries everywhere; minimal picker fields; contact fields need `view-contact`; reference lists limited to their screens | Decide who holds `view-contact` and `view-sensitive` |
| Payroll and sensitive fields | Bank account encrypted at rest (Fernet), masked in responses, needs `view-sensitive`; key rotation script | `PAYROLL_ENCRYPTION_KEYS` (required in production), key custody and backup apart from data backups |
| Documents and attachments | Encrypted at rest, private storage with no URLs, checksum on read, content-type checks, download headers, downloads audited | `DOCUMENT_ENCRYPTION_KEYS` (required), key custody, storage volume permissions and backup |
| Malware scanning | ClamAV `clamd` INSTREAM, fails closed (a scanner error refuses the upload), refusals audited | `MALWARE_SCANNER=clamav` (required in production), a running and updated `clamd`, `CLAMAV_HOST` and `CLAMAV_PORT` |
| Input validation | Pydantic models refuse unknown fields; server-side repetition of every frontend rule; size limits checked before the body is read (`Content-Length`); import limits; XLSX parsed with `defusedxml` | Confirm the limits (items 18, 41, 88) |
| Audit logs | Append-only (trigger blocks UPDATE, DELETE, TRUNCATE); every change and denial recorded with the actor; sensitive values masked | Retention policy; a Platform read endpoint (not built); backups |
| Secrets and environment | All secrets come from environment variables; `.env` excluded from ZIPs (verified by scan); test secrets and keys generated per run; production check refuses unsafe settings | A secret store on the server. `PLATFORM_SERVICE_TOKEN` and `IDENTITY_SERVICE_TOKEN` when those integrations are configured |
| Transport and headers | Proxy headers honoured (`--proxy-headers`) | **TLS, HSTS and security headers at Nginx** (not set by the application); request size limits at the proxy |
| Rate limiting | None in HRMS | At the proxy if required (Identity owns login rate limiting) |

No database password is stored in the source. `.env.example` uses the placeholder `CHANGE_ME`, and the tests
read `TEST_DATABASE_URL` from the environment and stop when it is not set (changed 2026-11-05).

---

## 5. Outstanding dependencies

See **`PENDING_DEPENDENCIES.md`**. In summary:
- 105 recorded HR or management items (items 58, 60 and 70 need only confirmation; item 73 is resolved);
- Identity: the token claims, JWKS, revocation, one new permission code, an active roles and users list, and role scopes;
- Platform: the notification endpoint, `roleCodes`, company settings (time zone, working days) and the audit feed;
- Infrastructure: deployment files, ClamAV, secrets, TLS, backups, monitoring;
- Frontend: the shift reason field and the document verification screen.

None of these is assumed resolved.

---

## 6. Testing and deployment readiness

| Item | Status |
|---|---|
| Tests executed | 188 automated tests, all passed on 2026-11-05. Per module: foundation 22, M1 38, M2 29, M3 25, M4 19, M5 28, M6 27. They run on a real PostgreSQL database rebuilt from the migrations each run. Large-data tests cover 1,000 employees, 10,000 punches and 11,000 accrual credits |
| Tests failed | none |
| Not executed | No browser end-to-end test of the frontend against this backend. No test against a real Identity, Platform or ClamAV (ClamAV runs with `MALWARE_SCANNER=none` in tests; the client is tested with a stub). No load test beyond the large-data tests. No test on the target server or in Docker |
| Migrations | `0001`–`0008`, linear, head `0008`, no drift. A fresh `upgrade head`, full `downgrade base` and per-revision downgrade and upgrade were all verified per module. Fingerprints match |
| Background worker | Ready as a process (`python -m app.worker`): it ran every scheduled job type and stopped cleanly on SIGTERM. Production needs it **supervised** (container restart or systemd), run with the same environment as the API, and at least one instance running |
| Environment variables | Listed with defaults in `.env.example` and `DEPLOYMENT_CHECKLIST.md`. Required in production: `DATABASE_URL`, `AUTH_JWT_PUBLIC_KEY` or `AUTH_JWKS_URL`, `ALLOWED_ORIGINS`, `DOCS_ENABLED=false`, `PAYROLL_ENCRYPTION_KEYS`, `DOCUMENT_ENCRYPTION_KEYS`, `MALWARE_SCANNER=clamav` |
| Docker | **Not ready.** Only `.dockerignore` exists. Still needed: a Dockerfile (API and worker), a compose file (API, worker, PostgreSQL, ClamAV, Nginx), volumes for storage, and a migration step |
| VPS deployment | **Not ready.** Still needed: the Nginx routing configuration (missing although referenced), TLS, a secret store, supervised processes, backups and monitoring. This was planned as a later phase and has not started |
| Backup and recovery | Requirements in `DEPLOYMENT_CHECKLIST.md`: PostgreSQL (dumps or base backups with WAL), the `STORAGE_DIR` volume (encrypted files), and the encryption keys **stored separately**, since losing the keys loses the documents and bank details. Plus restore drills. Nothing is set up yet |

---

## 7. Deliverables and backup

All under `/tmp/claude-0/-home-user-EVR-ERP/b66e2bec-4f94-599a-b181-a6501d2af264/scratchpad/`. This is a
session scratch folder, not a repository: **nothing is committed or pushed**. Download and keep the ZIPs: the
folder does not survive the end of the session.

| Artifact | Contents | Files | SHA-256 (first 16) |
|---|---|---|---|
| `hrms-service/` | Current source: app, tests, migrations, tools, setup, docs | — | — |
| `hrms-service-phase3.zip` | Foundation | 71 | `8aaeab1f29a7c104` |
| `hrms-service-module1.zip` | + Module 1 | 89 | `8fdb0d85aaba57dd` |
| `hrms-service-module2.zip` | + Module 2 | 113 | `1271e22ab3f26bf2` |
| `hrms-service-module3.zip` | + Module 3 | 131 | `59a37a6edc04dc65` |
| `hrms-service-module4.zip` | + Module 4 | 143 | `9b3868eef8e18993` |
| `hrms-service-module5.zip` | + Module 5 | 170 | `f67d47cdfad4814d` |
| `hrms-service-module6.zip` | + Module 6 | 196 | `12ca5fa6b316deb2` |
| `hrms-service-consolidated-2026-11-05.zip` | Everything above, plus this review's 4 reports and `openapi.json` | see `DEPLOYMENT_CHECKLIST.md` | recorded at creation |

Each module ZIP is cumulative: it contains the whole project up to that module.

**Documentation in `docs/`:**
- `ANALYSIS.md`, `API_MAPPING.md`, `AUTH_INTEGRATION.md`, `BACKGROUND_WORKER.md`, `ER_DIAGRAM.md`;
- `HR_CONFIRMATION_PENDING.md`, `MODULE_REPORTS.md`;
- `MODULE_2_ANALYSIS.md`, `MODULE_5_ANALYSIS.md`, `MODULE_6_ANALYSIS.md`;
- `MODULE_2_DECISIONS.md` … `MODULE_6_DECISIONS.md`;
- added by this review: `BACKEND_STATUS_REPORT.md`, `API_ENDPOINT_CATALOG.md`, `PENDING_DEPENDENCIES.md`, `DEPLOYMENT_CHECKLIST.md`, `openapi.json`.

The frontend (`/home/user/EVR-ERP`) was not modified.

---

## Status summary

1. **Completed:** the foundation and Modules 1–6, covering 134 endpoints (90 frontend calls), 51 tables and 8 migrations. 188 tests pass and the contract check matches 90 of 90.
2. **Partially completed:**
   - document management (no verify/reject or delete, pending D24 and R4);
   - shift back-dating from the UI (frontend reason field);
   - G6 policies (4 of 6 areas);
   - notifications (built and queued; delivery waits for Platform);
   - deployment configuration (environment validation done; no Docker, Nginx or backups).
3. **Not implemented:**
   - payroll (30 endpoints), performance (15), reports (5), HR workspace (4);
   - G6 `payroll` and `performance` areas;
   - the Platform audit feed;
   - cleanup and retention jobs, CORS (only needed cross-origin), rate limiting.
4. **Blocked by external dependencies:**
   - **Identity:** real sign-in, token claims and revocation, the permission catalogue, active roles and users.
   - **Platform:** notification delivery, company settings, the audit feed.
   - **Management:** organizational scopes.
   - **HR:** real setup data and all 105 policy items.
   - **IT:** ClamAV, devices, secrets and infrastructure.
5. **Safe to integrate with the frontend:** **yes, for the 90 Module 1–6 calls**, against a development or staging backend with development tokens or Identity, served same-origin through the dev or reverse proxy.
6. **Not yet safe for production:** **no.** Production needs:
   - Identity integration;
   - deployment artifacts (Docker or service units, Nginx with TLS and headers);
   - production secrets and key custody, and ClamAV;
   - backups and restore drills, and monitoring;
   - organizational scopes, and HR-confirmed setup data.

   Payroll, performance and reports are also not built.
