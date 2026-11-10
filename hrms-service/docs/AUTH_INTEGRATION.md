# HRMS ↔ Identity & Platform Service: Integration Contract

**Audience:** the developer who owns sign-in, users, roles, permissions and the shared platform
features. **Status (2026-11-05): implemented** by `identity-service` and `platform-service`, and verified end to end
(`evr-erp-deploy/e2e/`). It was first proposed by the HRMS side. Everything here is configurable in HRMS through
environment variables, so details can change without code changes. Please confirm or amend.

HRMS never reads the Identity database and never stores passwords. It trusts only signed tokens.

---

## 1. The session token HRMS accepts

The frontend sends cookies on every request (`credentials: 'include'`) and keeps no token after a
page reload, so the session must travel as a **cookie**.

| Item | Proposal | HRMS setting |
|---|---|---|
| Transport | httpOnly, `Secure`, `SameSite=Lax` cookie on the shared domain, path `/` | `AUTH_COOKIE_NAME` (default `evr_session`) |
| Also accepted | `Authorization: Bearer <token>` (same token), for tools and service calls | always on |
| Format | JWT | — |
| Signature | **RS256** (Identity holds the private key; services get the public key) | `AUTH_JWT_ALGORITHMS` (default `RS256`) |
| Public key | PEM in an environment variable, **or** a JWKS URL that HRMS caches | `AUTH_JWT_PUBLIC_KEY` or `AUTH_JWKS_URL` |
| Issuer / audience | `iss` = Identity's URL, `aud` = `evr-erp` | `AUTH_JWT_ISSUER`, `AUTH_JWT_AUDIENCE` |
| Lifetime | Equal to the session (`exp`), e.g. 8 hours; the frontend ends the session at `expiresAt` | — |

**Claims HRMS reads**

| Claim | Type | Meaning | HRMS setting for the claim name |
|---|---|---|---|
| `sub` | string | User ID (opaque). Written to `created_by` / `updated_by` and the audit log | `AUTH_CLAIM_USER_ID` |
| `name` | string | Display name, for audit entries and "reviewed by" | `AUTH_CLAIM_NAME` |
| `sid` | string | Session ID, for revocation checks | `AUTH_CLAIM_SESSION_ID` |
| `employeeId` | string \| null | The user's HRMS employee ID; drives self-service (`/hr/me/*`) and "awaiting my decision" | `AUTH_CLAIM_EMPLOYEE_ID` |
| `roles` | string[] | Role IDs, for approval workflows that route to a role | `AUTH_CLAIM_ROLES` |
| `permissions` | string[] | Effective permission codes (`hr.leave:approve`, `module:*`, `*`), the same catalogue as the frontend | `AUTH_CLAIM_PERMISSIONS` |

HRMS rejects a token that is missing, expired, wrongly signed, has the wrong issuer or audience,
or lacks `sub` and `permissions`. Every rejection is a 401 with the standard error envelope.

**Linking users to employees.** HR creates employees in HRMS and logins in Identity. The Identity
user record stores the HRMS `employeeId` (an opaque string, no foreign key) and puts it in the token.

## 2. Session revocation

When a user signs out, is deactivated, or has their password reset, existing tokens must stop working.

| Item | Proposal |
|---|---|
| Endpoint on Identity | `GET /internal/sessions/{sid}` → `200 { "active": true }` or `{ "active": false }` |
| Auth | Service token (section 4) |
| HRMS behaviour | Caches the answer per `sid` for `AUTH_REVOCATION_CACHE_SECONDS` (default 60). If Identity is unreachable, HRMS keeps the last known answer for up to 5 minutes, then refuses with 503 |
| Switch | `AUTH_REVOCATION_URL` empty = no revocation check (development only) |

## 3. CSRF protection

HRMS checks the `Origin` header (or `Referer`) on POST, PUT, PATCH and DELETE against
`ALLOWED_ORIGINS`. Together with `SameSite=Lax`, this blocks cross-site requests **without any
frontend change**. Identity should do the same.

## 4. Service-to-service calls

| From → To | Call | Why |
|---|---|---|
| HRMS → Identity | `GET /internal/users?ids=…` and `GET /internal/users?q=…&limit=…` → `[{ id, name, employeeId, active, roleIds }]` | Approver pickers (leave workflow "users"), names on records |
| HRMS → Identity | `GET /internal/roles` → `[{ id, name }]` | Role approvers in workflows |
| HRMS → Platform | `POST /internal/notifications` with `{ userIds?, employeeIds?, category, title, message, link }` | Leave, approval, payroll and document notifications |
| Platform → HRMS | `GET /api/v1/hr/internal/audit-events?…` (same filters as the audit screen) | The administration audit screen shows HR actions too |
| Identity → HRMS | `GET /api/v1/hr/employees/lookup?q=` (normal endpoint) | Linking a login to an employee |

**Service tokens:** JWTs signed by Identity with `sub` = service name, `aud` = target service, and
`permissions` = the internal scopes the caller needs. HRMS obtains its own with the client
credentials in `IDENTITY_CLIENT_ID` and `IDENTITY_CLIENT_SECRET`.

**Delivery guarantee for notifications:** HRMS writes each notification to an outbox table in the
same transaction as the business change. The HRMS worker delivers it and retries on failure.

## 5. Routing (one public base URL)

The frontend uses a single base URL (`/api/v1`). Nginx routes by path:

| Path prefix | Service |
|---|---|
| `/api/v1/auth/`, `/api/v1/admin/users`, `/api/v1/admin/roles`, `/api/v1/admin/permissions`, `/api/v1/admin/settings`, `/api/v1/admin/integrations`, `/api/v1/admin/audit-events`, `/api/v1/admin/overview`, `/api/v1/notifications` | Identity & Platform |
| `/api/v1/dashboard`, `/api/v1/production/` | Manufacturing |
| `/api/v1/hr/`, `/api/v1/admin/departments`, `/api/v1/admin/designations`, `/api/v1/admin/reporting-lines`, `/api/v1/admin/workflows`, `/api/v1/admin/workflow-processes`, `/api/v1/admin/policies` | **HRMS** |

A sample Nginx configuration is in `deploy/nginx.conf`.

## 6. Shared conventions

Both services use the same error envelope, `X-Request-Id` (Nginx generates one if missing and
passes it on), camelCase JSON, ISO dates and UTC date-times, and the paging format in
`HRMS_API_CONTRACTS.md` Part A.

## 7. Local development without Identity

`AUTH_DEV_MODE=true` (refused when `ENVIRONMENT=production`) lets HRMS accept HS256 tokens signed
with `AUTH_DEV_SECRET`. `app/scripts/dev_token.py` prints one for a given user and permission
list, for Swagger and integration tests.


## Claims HRMS uses for employee access (Module 2)

- `roles`: Identity role codes. HRMS maps them to organizational scopes configured in
  `/hr/setup/employee-access-scopes` (decision Q12). Role codes must be stable; renaming a role in
  Identity requires updating its scope assignment in HRMS.
- `employeeId`: the caller's HRMS employee ID (the UUID returned by `/hr/employees`), set when HR
  links a login to an employee. Used for the `headed_departments`, `reporting_tree` and
  `own_record` scopes and the self-service department list. A missing or unknown value simply
  grants nothing for those scopes.


## Module 5 additions

- **New permission code** `hr.shifts:assign-backdated` (owner decision: back-dated shift assignments
  need a dedicated permission). The Identity service must add it to its permission catalogue and HR
  must grant it explicitly; it is not part of any role by default.
- **Workflow approvers** of type `role` match the token's `roles` claim; type `user` matches `sub`.
  HRMS cannot yet confirm that a configured role or user is active (G5 asks for it); that needs an
  Identity endpoint listing active roles and users.
- **Attendance devices** do not use user tokens: each device authenticates with its own API key
  (`X-Device-Key`), issued by HRMS (only a SHA-256 hash is stored). The reverse proxy should route
  `/api/v1/hr/attendance/events/ingest` to HRMS like the other HR paths; restricting it to the device
  network is recommended.

## Module 6 additions

- **Notifications** go to Platform's `POST /internal/notifications` from the `notification_outbox`
  table (written in the same transaction as the change; delivered by the worker with retries).
  HRMS sends `Authorization: Bearer <PLATFORM_SERVICE_TOKEN>` until Identity issues service tokens.
  **Pending Platform:** the contract addresses `userIds` and `employeeIds` only. An escalation to an
  HR *role* is sent with an extra field `roleCodes`; Platform must accept it (or provide another way
  to address a role).
- **Leave approvers** of type `role` match the token's `roles` claim, type `user` matches `sub`,
  and `reporting_manager` / `department_head` match the `employeeId` claim (Module 2 records).
- **Approver options** (`GET /hr/leave/approval-workflows/options`) list only the roles and users
  already used in HRMS configuration until Identity offers a list of active roles and users.
- **Company working days** (`COMPANY_WORKING_DAYS`) stand in for Platform's company settings (G7)
  until those are reachable (pending, L18).


## Implemented 2026-11-05 (identity-service, platform-service, manufacturing-service)

**Identity:**
- signs RS256 session tokens with exactly the claims in section 1;
- publishes the key at `/.well-known/jwks.json`;
- answers `GET /internal/sessions/{sid}`.

**Service tokens (section 4):**
- `POST /internal/service-tokens` with `{clientId, clientSecret}` returns a short-lived token: `aud` = `evr-internal`, `permissions` = the client's scopes.
- HRMS uses it when `IDENTITY_BASE_URL`, `IDENTITY_CLIENT_ID` and `IDENTITY_CLIENT_SECRET` are set, both for the revocation check and for notifications to Platform. The static `IDENTITY_SERVICE_TOKEN` and `PLATFORM_SERVICE_TOKEN` remain as a fallback.
- Scopes:
  - `identity:sessions.read` (revocation);
  - `identity:users.read` (user lists);
  - `platform:notifications.write` (HRMS → Platform).

**Notification recipients:** Platform resolves `employeeIds` and `roleCodes` (Identity role ids) through Identity's `GET /internal/users?employeeIds=&roleIds=&activeOnly=`.

**Platform's administration screens.** Platform calls these with the caller's own session, so HRMS applies the caller's permissions:
- `GET /api/v1/hr/internal/audit-events` (`admin:audit.view`) returns `{items, total, facets}`;
- `GET /api/v1/hr/internal/admin-counts` (`admin:view`).

This replaces the earlier proposal of Platform calling HRMS with a service token.

**Routing:** see `evr-erp-deploy/nginx.conf`. It sends all 178 frontend calls to the right service (checked against the routes) and blocks `/internal/*` from outside.
