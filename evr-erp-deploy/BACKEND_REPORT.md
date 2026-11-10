# EVR Power ERP: Backend Report

**Date:** 2026-11-05
**Status:** every API the frontend calls is implemented, tested and verified end to end. Nothing is committed to Git or deployed.

## 1. Summary

| Item | Result |
|---|---|
| Frontend API calls | **178 of 178** have a backend endpoint, each in exactly one service |
| Services | 4: HRMS, Identity, Platform, Manufacturing (FastAPI + PostgreSQL) |
| Automated tests | **217 passed**, 0 failed |
| End-to-end run (four services live over HTTP) | **17 of 17** checks passed |
| Frontend contract (field names) | All checked interfaces match: HRMS 141, Identity 11, Platform 10, Manufacturing 12 |
| Database migrations | All upgrade and downgrade cleanly; no drift between models and database |
| Secrets in the package | None: no passwords, keys, `.env` or virtual environments |

## 2. Architecture

The frontend uses one base URL, `/api/v1`. Nginx (`nginx.conf`) sends each path to its service; it blocks the service-to-service paths (`/internal/*`) from outside.

| Service | Port | Responsibility | Frontend APIs | Tables | Migrations |
|---|---|---|---|---|---|
| hrms-service | 8000 | Employees, documents, import, attendance, leave, payroll, performance, reports, HR workspace, HR administration | 144 | 73 | 11 |
| identity-service | 8001 | Sign-in, sessions, users, roles, permission catalogue | 16 | 6 | 1 |
| platform-service | 8002 | Company settings, notifications, integrations, audit log of all services, administration overview | 13 | 5 | 1 |
| manufacturing-service | 8003 | Production work orders, the shop-floor route, the company dashboard (read-only) | 5 | 7 | 1 |

**How the services trust each other:**
- **Sign-in.** Identity signs an RS256 session token. It is sent in the httpOnly `evr_session` cookie.
- **Checking a token.** Every other service checks the signature with Identity's public key (JWKS). It also asks Identity whether the session is still active, so sign-out, deactivation and password resets end the session everywhere.
- **Calls with no user behind them** use short-lived service tokens from Identity (client credentials, scoped):
  - HRMS sending notifications to Platform;
  - checking whether a session is still active;
  - looking up the users who should receive a notification.
- **Calls made for a user** forward that user's session, so each service applies its own permissions. For example, Platform's audit screen reads HRMS's audit log as the signed-in user.

## 3. API coverage by frontend area

| Frontend area | Calls | Service |
|---|---|---|
| Administration (users, roles, organization, workflows, policies, settings, audit, integrations, overview) | 37 | Identity, HRMS, Platform |
| Payroll | 30 | HRMS |
| Leave, permission and overtime requests | 25 | HRMS |
| Attendance and shifts | 19 | HRMS |
| Performance | 15 | HRMS |
| Reference data | 10 | HRMS |
| Employees | 7 | HRMS |
| Employee documents | 7 | HRMS |
| Notifications | 6 | Platform |
| Reports (25 reports) | 5 | HRMS |
| HR workspace | 4 | HRMS |
| Employee import | 4 | HRMS |
| Production work orders | 4 | Manufacturing |
| Sign-in | 3 | Identity |
| Company dashboard | 1 | Manufacturing |
| Approval inbox | 1 | HRMS |
| **Total** | **178** | |

## 4. Security

- **Authorization:**
  - every request is authorized on the server; the frontend's hidden buttons are not relied on;
  - a denied request returns 403 and is written to the audit log;
  - employee data follows the caller's organizational scope (all, departments, reporting tree, own record).
- **Passwords:**
  - stored only as Argon2id hashes, and never returned, logged or audited;
  - policy and lockout are configurable: 12 characters minimum, a letter and a number, not the username; 5 failures lock the account for 15 minutes;
  - every sign-in failure gets the same generic message;
  - sign-in is rate-limited per IP.
- **Sessions:**
  - httpOnly, `SameSite=Lax`, Secure in production;
  - unsafe requests are refused when their Origin is not allowed (CSRF);
  - sessions are revocable everywhere.
- **Sensitive data:**
  - bank account numbers, employee documents and integration secrets are encrypted at rest (Fernet keys from the environment);
  - payroll amounts are withheld from users without `hr.payroll:view-amounts`;
  - integration secrets are write-only.
- **Audit:**
  - every write is recorded with before and after values, sensitive values masked;
  - audit logs and histories are append-only, enforced by database triggers;
  - optimistic concurrency stops lost updates (409 on a stale version).
- **Secrets:** none in the source or the package. Each service has its own database role, and production refuses to start with development settings.

## 5. Verification

| Check | Result |
|---|---|
| HRMS tests | 205 passed |
| Identity tests | 6 passed |
| Platform tests | 4 passed |
| Manufacturing tests | 2 passed |
| Route coverage (`tools/route_coverage.py`) | 178 of 178 calls routed to the service that serves them; none missing or duplicated |
| Contract shapes (`tools/shape_check.py`, HRMS `tools/verify_contracts.py`) | All checked interfaces match |
| Migrations | Upgrade, `alembic check`, downgrade and upgrade on every service |
| End to end (`e2e/`) | 17 of 17 |
| Package secret scan | Clean |

The end-to-end run covered:
- one sign-in working in all four services;
- a role change taking effect;
- HRMS writes passing the CSRF origin check;
- Identity reading department names from HRMS;
- Platform merging the audit logs and building the overview;
- HRMS delivering a notification through Platform to the user's bell;
- every service refusing a signed-out session.

## 6. Defects found by the tests and fixed before delivery

| Area | Defect |
|---|---|
| Payroll | Overtime was subtracted from the "balance of gross" allowance |
| Payroll | Under proration, the full-month amount of percentage components used the prorated base |
| Reports | The employee directory read the wrong field for the status label |
| HR workspace | The task list was built without its counts |
| Identity | The first-administrator script saved nothing |
| Identity | After a lock expired, one wrong password re-locked the account at once |
| Identity | The last-administrator safeguard crashed instead of refusing the change |
| Platform | A refused integration save left a half-created record behind |
| Manufacturing | The monthly output query failed |

## 7. Decisions still needed

Nothing was invented. Where a rule was not given, the value is configurable, empty, or built as the contract proposed, and listed for confirmation.

- **HR, payroll and appraisal:** 131 items in `hrms-service/docs/HR_CONFIRMATION_PENDING.md`. They include:
  - salary components, rates and slabs;
  - the proration basis;
  - loss of pay;
  - the TDS method;
  - who takes part in appraisals;
  - the HR task rules;
  - the report definitions.
- **IT:**
  - the password policy and lockout values;
  - the email and SMS delivery and integration connectors (not built; shown as unavailable);
  - the integration setting keys;
  - large report exports (they currently run immediately).
- **Frontend:** a screen for the forced password change (G-Q5). Until it exists, **HR should not tick "must change password"**: such a user can sign in but has no permissions.
- **Production planning:**
  - how schedule status and variance are calculated;
  - the dashboard KPI definitions;
  - the testing stage code;
  - how work orders get into the system (there are no write APIs).
- **Company settings:**
  - the time zone, currency and working days must be entered by an administrator;
  - HRMS still reads its own `COMPANY_TIME_ZONE` and `COMPANY_WORKING_DAYS` settings.

## 8. Known limitations

- **Manufacturing** is read-only. Its tables are empty until another system or a later module fills them.
- **No self-assessment** in appraisals, and no employee self-service goals: the frontend has no screens for them.
- **Single-process limits:** the sign-in rate limiter is in memory, per process, so also rate-limit at nginx (included in `nginx.conf`).
- **Payroll** calculates monthly periods only.

## 9. Package contents

`EVR_ERP_BACKEND_COMPLETE.zip` contains:

| Folder | Contents |
|---|---|
| `hrms-service/`, `identity-service/`, `platform-service/`, `manufacturing-service/` | Source, migrations, tests, `.env.example`, `README.md`, `docs/` (decisions, OpenAPI) |
| `evr-erp-deploy/` | `README.md` (setup steps), `nginx.conf`, this report, `tools/` (coverage and shape checks), `e2e/` (end-to-end scripts) |

No `.env`, virtual environment, database dump or secret is included.

**Start here:**
1. `evr-erp-deploy/README.md`;
2. each service's `README.md`;
3. each service's `docs/`.
