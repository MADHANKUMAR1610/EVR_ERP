# Identity service: Decisions and Scope

Recorded 2026-11-05. The owner asked for the Identity APIs and chose:
- **separate services**;
- a **configurable password policy with secure defaults** (pending IT).

The design follows the contracts **B1**, **G1–G3** and hrms-service `docs/AUTH_INTEGRATION.md`, which defines the tokens HRMS accepts.

## Scope: the 16 frontend endpoints

| Area | Endpoints | Permission |
|---|---|---|
| Sign-in (B1) | `POST /auth/login`, `GET /auth/session`, `POST /auth/logout` | public / signed in |
| Users (G2) | list, detail, activity, create, update, status, password reset | `admin:users.view` / `admin:users.manage` |
| Roles (G3) | permission catalogue, roles list and detail, role users, create, update | `admin:roles.view` / `admin:roles.manage` (role users: + `admin:users.view`) |

**Additions:**
- `POST /auth/password`: change your own password. It is required after an HR-set password, and its screen is pending (G-Q5).
- `GET /.well-known/jwks.json`: the public signing key.
- Internal endpoints for other services, outside `/api/v1`, which the proxy never exposes:
  - `POST /internal/service-tokens`;
  - `GET /internal/sessions/{sid}`;
  - `GET /internal/users`;
  - `GET /internal/roles`.
- `python -m app.scripts.bootstrap`: creates the built-in roles and the first administrator.

## Sessions and tokens

- **Transport:** an httpOnly, `SameSite=Lax` cookie `evr_session` (Secure in production), as HRMS expects.
- **Token:**
  - a JWT signed **RS256** with the key from `JWT_PRIVATE_KEY`;
  - claims `sub`, `name`, `sid`, `employeeId`, `roles` (role ids), `permissions`, `mustChangePassword`, `iss`, `aud=evr-erp` and `exp`;
  - HRMS verifies it with the JWKS.
- **Lifetime:** `SESSION_HOURS`, 8 by default.
- **Sessions are stored.** Signing out, deactivation and a password reset revoke them. HRMS checks revocation through `/internal/sessions/{sid}`.
- **Permissions:**
  - the token carries the effective permissions: the union of the user's **active** roles;
  - `GET /auth/session` re-reads them and re-issues the cookie, so role changes apply at the next page load (G-Q1).
- **Login CSRF:** a sign-in from a foreign `Origin` is refused. Other unsafe requests use the same Origin check as HRMS.

## Passwords

- **Storage:** Argon2id hashes only. No password or hash appears in a response, log, audit entry or account history.
- **Policy (pending IT; configurable):**
  - at least `PASSWORD_MIN_LENGTH` characters (default **12**);
  - at least one letter and one number;
  - must not contain the username.
- **Lockout (pending IT; configurable):**
  - `LOCKOUT_ATTEMPTS` consecutive failures (default **5**) lock the account for `LOCKOUT_MINUTES` (default **15**);
  - it unlocks by itself after that, or when HR resets the password.
- **Rate limit:** `LOGIN_RATE_PER_IP_PER_MINUTE` per client IP (default 30), returning 429. The limiter is in memory, per process; behind several workers, also limit at the proxy.
- **Failed sign-ins:** every one returns the same 401 `INVALID_CREDENTIALS`. This holds for unknown users, wrong passwords, inactive and locked accounts, with the same hashing work.
- **mustChangePassword:** the user can sign in, but the session carries **no permissions** until the password is changed with `POST /auth/password`. The frontend has no screen for this yet (G-Q5), so HR should leave the flag off until it exists.

## Users and roles

- Usernames and emails are unique, case-insensitive.
- An employee is linked to at most one account.
- The employee, department and reporting manager are read from **HRMS with the caller's own session**, and their names are kept as a snapshot when the account is saved.
- **409 safeguards:**
  - you cannot deactivate your own account;
  - no change may leave zero active users with `admin:roles.manage` through an active role.
- **Role changes:**
  - deactivation ends the account's sessions;
  - wildcards and unknown codes are stored as given;
  - built-in roles cannot be renamed;
  - there is no delete (deactivate instead).
- **Built-in roles (G1, decided):**
  - **System Administrator:** `admin:*`;
  - **HR Manager:** the administration codes of the frontend's `HR_MANAGER_ADMIN` list.

  HR module permissions are not pre-assigned: HR adds them through the role screen.
- **The permission catalogue** contains every code HRMS checks, the administration codes and the ERP module view codes. Each module is one row; the eight actions are columns (`manage` shows as configure; approve and reject share a code); other codes are listed as extras.

## Pending

- The password policy and lockout values (IT).
- The forced password-change screen (G-Q5).
- Multi-factor authentication and self-service password reset: not requested.
- Several workers: move the IP limiter to the proxy or a shared store.
