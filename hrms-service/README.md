# EVR Power ERP — HRMS Service

The human resources microservice of EVR Power ERP: employees, documents, attendance, leave,
payroll, performance and HR administration. FastAPI + PostgreSQL (SQLAlchemy 2 async, asyncpg,
Alembic). It has its own database and is deployed independently.

**Status:** Phases 1–3 complete (analysis, architecture, foundation). Business modules 1
(organization and reference data), 2 (employees), 3 (employee documents), 4 (employee import)
5 (time & attendance) and 6 (leave management, with permission and overtime requests) complete. Business modules are built one at a time; see
[`docs/MODULE_REPORTS.md`](docs/MODULE_REPORTS.md) for what each one delivered and what remains.

| Document | Contents |
|---|---|
| [`docs/ANALYSIS.md`](docs/ANALYSIS.md) | Decisions, business concepts, entities, architecture, auth and audit design, open questions |
| [`docs/API_MAPPING.md`](docs/API_MAPPING.md) | All 178 frontend endpoints with owner, controller, permission and build status |
| [`docs/MODULE_REPORTS.md`](docs/MODULE_REPORTS.md) | Completion report for each phase and module |
| [`docs/HR_CONFIRMATION_PENDING.md`](docs/HR_CONFIRMATION_PENDING.md) | Values and rules awaiting HR or management confirmation |
| [`docs/MODULE_2_DECISIONS.md`](docs/MODULE_2_DECISIONS.md) | Employees: the 12 decisions, organizational scopes, encryption |
| [`docs/MODULE_3_DECISIONS.md`](docs/MODULE_3_DECISIONS.md) | Employee documents: file checks, malware scan, private encrypted storage, access, audit |
| [`docs/MODULE_4_DECISIONS.md`](docs/MODULE_4_DECISIONS.md) | Employee import: validation, duplicates, background jobs, transaction strategy |
| [`docs/BACKGROUND_WORKER.md`](docs/BACKGROUND_WORKER.md) | Worker configuration, running it, failure handling |
| [`docs/MODULE_5_ANALYSIS.md`](docs/MODULE_5_ANALYSIS.md) | Time & Attendance: analysis |
| [`docs/MODULE_5_DECISIONS.md`](docs/MODULE_5_DECISIONS.md) | Time & Attendance: approval workflows, back-dated assignments, settings, pending rules |
| [`docs/MODULE_6_ANALYSIS.md`](docs/MODULE_6_ANALYSIS.md) | Leave Management: analysis and questions L1–L32 |
| [`docs/MODULE_6_DECISIONS.md`](docs/MODULE_6_DECISIONS.md) | Leave Management: confirmed scope (Part B included), the owner's five decisions, recommendations applied |
| [`docs/ER_DIAGRAM.md`](docs/ER_DIAGRAM.md) | Database design |
| [`docs/AUTH_INTEGRATION.md`](docs/AUTH_INTEGRATION.md) | Contract with the Identity service (owned by the other developer) |

## What the foundation provides

- **Configuration** from environment variables only (`app/core/config.py`); production refuses unsafe settings.
- **Error envelope** `{ error: { code, message, details[] } }` for every non-2xx response, including
  validation errors with camelCase field paths, and a safe 500 that never leaks internals.
- **`X-Request-Id`** on every response, reused from the proxy when present, and in every log line.
- **Structured JSON logs** to stdout, never containing passwords, tokens or request bodies.
- **Authentication:** verifies the Identity service's JWT from the session cookie or a bearer header
  (RS256 public key or JWKS, issuer and audience checks, revocation check with caching).
- **Authorization:** `require("hr.leave:approve")` with the frontend's rules (`*`, `module:*`);
  every denial is written to the audit log.
- **CSRF protection** by Origin check for cookie-authenticated writes (no frontend change needed).
- **Audit fields** `created_at/by`, `updated_at/by` on every business table, filled from the
  authenticated user on every write; writes without an actor are refused.
- **Append-only audit log** (database trigger blocks UPDATE, DELETE and TRUNCATE), with sensitive values masked.
- **Optimistic concurrency** (`version`, 409 `STALE_VERSION`) and **paging** (`page`, `pageSize`
  ∈ 10/25/50/100, `sort=field:dir` with unknown fields → 400).
- **Health checks:** `GET /health` (process) and `GET /health/ready` (database).

## Run locally

Requirements: Python 3.12+, PostgreSQL 14+.

```bash
python -m venv .venv
```
```bash
. .venv/bin/activate
```
```bash
pip install -r requirements-dev.txt
```
```bash
cp .env.example .env
```

Edit `.env`: set `DATABASE_URL`, and for local work without the Identity service set
`AUTH_DEV_MODE=true` and a long random `AUTH_DEV_SECRET`. Then:

```bash
alembic upgrade head
```
```bash
uvicorn app.main:app --reload --port 8000
```

Load the starting reference data (departments, designations, statuses, shifts, document types …).
The file is a **template pending HR confirmation** (`docs/HR_CONFIRMATION_PENDING.md`); the loader
refuses to load it into production until HR has signed it (`hr_confirmed: true`, with who and when).

```bash
python -m app.scripts.load_reference_data --file setup/reference_data.yaml --dry-run
```
```bash
python -m app.scripts.load_reference_data --file setup/reference_data.yaml
```

The loader only creates items whose code is missing; it never overwrites. Later changes go through
the `/hr/setup/*` and `/admin/*` endpoints, which keep the audit trail.

**Employee access needs two settings before anyone sees employee records:**

1. `PAYROLL_ENCRYPTION_KEYS` in `.env` (bank account numbers are encrypted at rest). Generate a key:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. Organizational scopes for the Identity roles, via `POST /api/v1/hr/setup/employee-access-scopes`
   (`hr.settings:manage`), e.g. `{"roleCode": "hr-manager", "scopeType": "all"}`. There are no defaults:
   a role without a scope sees no employees, whatever its permissions.

**Employee documents** are stored encrypted in private storage (`STORAGE_DIR`, never served by the
web server, never reachable by URL). They need `DOCUMENT_ENCRYPTION_KEYS` (a separate Fernet key). In
production uploads must be scanned: run ClamAV's `clamd` (for example the official `clamav/clamav`
container) and set `MALWARE_SCANNER=clamav`, `CLAMAV_HOST`, `CLAMAV_PORT`. Scanning fails closed: if the
scanner is down, uploads are refused. The reverse proxy must allow request bodies of at least
`MAX_UPLOAD_BYTES` plus 64 KB (Nginx `client_max_body_size`). Back up `STORAGE_DIR` together with the
database, and keep the keys apart from both.

**Background worker.** Employee imports (and later other long-running jobs) are run by a separate
process. Run at least one next to the API; several may run at once:

```bash
python -m app.worker
```

Without a worker, import jobs stay `queued`. A worker stopped mid-job is safe: another worker resumes
the job after its last committed batch (`WORKER_STALE_SECONDS`).

**Attendance devices** push punches to `POST /api/v1/hr/attendance/events/ingest` with their own API
key in `X-Device-Key` (register a device and issue its key under `/api/v1/hr/setup/attendance-devices`;
the key is shown once). Attendance thresholds (half day, overtime, correction window, back-dating …)
are HR settings under `/api/v1/admin/policies/{attendance|shifts|overtime}` and start empty: a rule is
not applied until HR sets it.

Key rotation: put the new key first in `PAYROLL_ENCRYPTION_KEYS`, restart, then run

```bash
python -m app.scripts.rotate_payroll_encryption
```

Open http://localhost:8000/docs. For an access token in development:

```bash
python -m app.scripts.dev_token --permissions "*" --roles hr-manager
```

## Tests

The tests use a real PostgreSQL database named `*_test`, rebuilt from the migrations at the start
of every run (never point it at real data):

```bash
python -m pytest
```

## Database migrations

```bash
alembic revision --autogenerate -m "describe the change"
```
```bash
alembic upgrade head
```

Tables are never created at application startup. Review every autogenerated migration before committing.

## Tools

```bash
FRONTEND_SRC=../EVR-ERP/src python tools/verify_contracts.py
```
```bash
python tools/gen_mapping.py
```

The first compares the response and input schemas and routes with the frontend TypeScript contracts;
the second regenerates `docs/API_MAPPING.md`.
