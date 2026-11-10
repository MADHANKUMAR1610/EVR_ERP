# HRMS Backend: Deployment Checklist

**Status on 2026-11-05: not yet deployable to production.** The application refuses to start in production with
unsafe settings. The deployment artifacts (container images, proxy configuration, service units, backups) do not
exist yet. Tick an item only when it is done on the target environment.

## 1. Readiness at a glance

| Area | Ready? | Notes |
|---|---|---|
| Application code (Modules 1–6) | Yes | 188 tests pass; contract check 90/90 |
| Database migrations | Yes | `alembic upgrade head` (0001–0008); nothing is created at startup |
| Background worker | Yes (process) | `python -m app.worker`; needs supervision |
| Production settings validation | Yes | Start-up refuses unsafe values (section 3) |
| Dockerfile / compose | **No** | Only `.dockerignore` exists |
| Nginx / TLS / security headers | **No** | `deploy/nginx.conf` is referenced in `AUTH_INTEGRATION.md` but does not exist |
| Identity integration (keys, claims, revocation) | **No** | Identity service not available |
| ClamAV | **No** | Required in production |
| Secrets and key custody | **No** | Required in production |
| Backups and restore | **No** | Requirements in section 6 |
| Monitoring | **No** | Health endpoints and JSON logs exist |
| Real HR setup data and organizational scopes | **No** | Sample template only; no scopes assigned |

## 2. Processes to run

| Process | Command | Notes |
|---|---|---|
| API | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers` | Never `--reload`. Behind Nginx only |
| Worker | `python -m app.worker` | At least one instance, supervised (restart on failure). Stops gracefully on SIGTERM. Several instances are safe (row locking) |
| Migrations | `alembic upgrade head` | Once per release, **before** starting the new API and worker; take a database backup first |
| Setup data | `python -m app.scripts.load_reference_data --file setup/reference_data.yaml` | Only after HR signs the file (`hr_confirmed: true`); refused in production otherwise. Create-only: it never overwrites |
| ClamAV | `clamd` reachable at `CLAMAV_HOST:CLAMAV_PORT` | Keep signatures updated (`freshclam`) |
| PostgreSQL | 14 or newer (tested on 16) | Dedicated database and role; the role owns the schema (migrations create triggers) |

## 3. Environment variables

**Required in production.** The application refuses to start without them, or with an unsafe value:

| Variable | Requirement |
|---|---|
| `ENVIRONMENT` | `production` (enables the checks below) |
| `DATABASE_URL` | `postgresql+asyncpg://…` (required in every environment) |
| `AUTH_JWT_PUBLIC_KEY` or `AUTH_JWKS_URL` | From Identity |
| `ALLOWED_ORIGINS` | JSON list of the frontend origin(s), for example `["https://erp.example.com"]` |
| `DOCS_ENABLED` | `false` (or protect `/docs` at the proxy) |
| `PAYROLL_ENCRYPTION_KEYS` | JSON list of Fernet keys; the first encrypts |
| `DOCUMENT_ENCRYPTION_KEYS` | JSON list of Fernet keys; the first encrypts |
| `MALWARE_SCANNER` | `clamav` |
| `AUTH_DEV_MODE` | must be `false` |

**Strongly recommended.** These are not enforced, but verified when set:
- `AUTH_JWT_ISSUER`, `AUTH_JWT_AUDIENCE`;
- `AUTH_REVOCATION_URL`, with `IDENTITY_SERVICE_TOKEN`;
- `COMPANY_TIME_ZONE` (default `UTC`, pending Platform).

**Optional, with defaults:**

| Group | Variables |
|---|---|
| Service | `SERVICE_NAME`, `API_PREFIX` (`/api/v1`), `LOG_LEVEL` (`INFO`) |
| Database pool | `DATABASE_POOL_SIZE` (10), `DATABASE_MAX_OVERFLOW` (10), `DATABASE_ECHO` (false) |
| Token claims | `AUTH_COOKIE_NAME` (`evr_session`), `AUTH_JWT_ALGORITHMS` (`["RS256"]`), `AUTH_JWKS_CACHE_SECONDS` (3600), `AUTH_LEEWAY_SECONDS` (30), `AUTH_CLAIM_*` (sub, name, sid, employeeId, roles, permissions), `AUTH_REVOCATION_CACHE_SECONDS` (60), `AUTH_REVOCATION_STALE_SECONDS` (300) |
| Storage and uploads | `STORAGE_DIR` (`storage`, use an absolute path on a persistent volume), `MAX_UPLOAD_BYTES` (10 MB), `CLAMAV_HOST`, `CLAMAV_PORT` (3310), `CLAMAV_TIMEOUT_SECONDS` (30) |
| Import | `IMPORT_MAX_ROWS` (2000), `IMPORT_MAX_FILE_BYTES` (5 MB), `IMPORT_BATCH_SIZE` (50) |
| Worker | `WORKER_POLL_SECONDS` (2), `WORKER_STALE_SECONDS` (300) |
| Leave | `COMPANY_WORKING_DAYS` (empty, pending L18), `LEAVE_ATTACHMENT_MAX_BYTES` (5 MB), `LEAVE_MAX_ATTACHMENTS` (5) |
| Notifications | `PLATFORM_NOTIFICATIONS_URL`, `PLATFORM_SERVICE_TOKEN` (secret), `NOTIFICATION_MAX_ATTEMPTS` (8) |
| Development only | `AUTH_DEV_SECRET` (with `AUTH_DEV_MODE=true`; refused in production) |

Every secret (keys, tokens, the database password) belongs in the server's secret store, never in git, a ZIP or an
image. Generate a Fernet key with
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

## 4. Reverse proxy (Nginx)

- [ ] One public origin. Route `/api/v1/hr/…` and the HRMS-owned `/api/v1/admin/…` paths (departments, designations, reporting-lines, workflows, workflow-processes, policies) to HRMS, and the other paths to Identity, Platform and Manufacturing (`AUTH_INTEGRATION.md` §5).
- [ ] TLS, HSTS, `X-Content-Type-Options`, `X-Frame-Options` (or a CSP `frame-ancestors`), `Referrer-Policy`. The application does not set these.
- [ ] Generate and pass `X-Request-Id`; pass `X-Forwarded-For` and `X-Forwarded-Proto`.
- [ ] Request body limit at least `MAX_UPLOAD_BYTES` plus 64 KB, and 25 MB plus 64 KB for leave applications (5 × 5 MB).
- [ ] Restrict `/api/v1/hr/attendance/events/ingest` to the device network (recommended).
- [ ] Optional rate limits; HRMS has none of its own.
- [ ] `/docs` and `/openapi.json` closed in production (`DOCS_ENABLED=false`).
- [ ] CORS is **not** needed for this same-origin setup. A cross-origin frontend would need CORS added to HRMS first.

## 5. Before the first real user

- [ ] Identity issues tokens with `sub`, `name`, `sid`, `employeeId`, `roles`, `permissions`; HRMS has its public key or JWKS, issuer and audience.
- [ ] Identity's catalogue includes `hr.shifts:assign-backdated`; roles are granted their permissions.
- [ ] Management assigns organizational scopes (`/hr/setup/employee-access-scopes`). Without them nobody sees employee records.
- [ ] HR confirms and signs the setup file; real departments, designations, shifts and document types are loaded.
- [ ] HR enters leave types, policies, holidays and workflows, and the `/admin/policies/{attendance,shifts,overtime,leave}` values they want applied.
- [ ] Encryption keys generated, stored in the secret store, and backed up **separately** from data backups.
- [ ] ClamAV running and updated; a test upload passes and an EICAR test file is refused.
- [ ] Worker running and supervised; `background_job` rows show `succeeded`.
- [ ] Platform notification URL and token set (or accept that notifications stay queued).

## 6. Backup and recovery requirements

| What | How | Why |
|---|---|---|
| PostgreSQL | Daily logical dumps (`pg_dump -Fc`), or base backups with WAL archiving for point-in-time recovery; kept off-server and encrypted | All records, the audit log and the leave ledger (append-only, so the history cannot be rebuilt otherwise) |
| `STORAGE_DIR` volume | File-level backup taken at the same time as the database | Employee documents and leave attachments (already encrypted) |
| Encryption keys | Secret store with its own backup, **separate** from data backups; keep old keys until rotation has finished | Losing every key makes the documents and bank details unreadable; storing keys with the backups defeats the encryption |
| Configuration | The environment (without secrets) and the signed setup file, under change control | Rebuilding the server |
| Restore drill | Restore the database and storage into a test environment, run `alembic current` and `/health/ready`, and open a document | Proves the backups work |

Retention periods for backups, the audit log, raw punches and documents are pending HR and Legal (items 36 and 72).

## 7. Release procedure (per deployment)

1. Back up the database and storage.
2. Deploy the new code (image or release directory).
3. Run `alembic upgrade head`.
4. Restart the API and the worker.
5. Check `/health`, `/health/ready`, the logs and the worker's job results.
6. Rollback:
   - `alembic downgrade` to the previous revision, then redeploy the previous code;
   - every migration has a tested downgrade, but a downgrade drops the tables its revision added;
   - if those tables hold data, restore from the backup instead.

## 8. Deliverable

The consolidated project ZIP, `hrms-service-consolidated-2026-11-05.zip`, contains:
- the source (`app/`), migrations (`alembic/`), tests, tools and setup template;
- all documentation, including the review documents and `docs/openapi.json`.

It excludes `.env`, `.venv`, caches and stored files. It contains no secrets.
