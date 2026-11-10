# EVR Power ERP backend: four services behind one base URL

| Service | Port | Owns | Frontend calls |
|---|---|---|---|
| `hrms-service` | 8000 | HR: employees, documents, import, attendance, leave, payroll, performance, reports, HR workspace; HR-owned administration (departments, designations, reporting lines, workflows, policies) | 144 |
| `identity-service` | 8001 | Sign-in and sessions, users, roles, the permission catalogue | 16 |
| `platform-service` | 8002 | Company settings, notifications, integrations, the audit log of every service, the administration overview | 13 |
| `manufacturing-service` | 8003 | Production work orders and the company dashboard (read-only) | 5 |
| **Total** | | | **178 of 178** |

All four use FastAPI and PostgreSQL, each with its own database and database role, the same error envelope, the same paging and the same audit-log rules. `nginx.conf` publishes them under one base URL, `/api/v1`, and keeps `/internal/*` off the public side.

## How sign-in works across services

1. **Sign-in.** Identity signs an **RS256** session token. It travels in the httpOnly `evr_session` cookie, `SameSite=Lax`, Secure in production.
2. **Checking the token.** HRMS, Platform and Manufacturing:
   - verify it with Identity's JWKS (`AUTH_JWKS_URL`);
   - check the issuer and the `evr-erp` audience;
   - ask Identity whether the session is still active (`AUTH_REVOCATION_URL`).

   Signing out, deactivating a user or resetting a password therefore ends the session everywhere.
3. **Service-to-service calls without a user** use short-lived service tokens. A service gets one from Identity with client credentials (`POST /internal/service-tokens`):
   - HRMS → Platform notifications;
   - HRMS → Identity revocation checks;
   - Platform → Identity recipient lookup.
4. **Calls on behalf of a user** forward that user's own session, so each service applies its own permissions:
   - Identity reading department and employee names from HRMS;
   - Platform building the audit screen and the overview from Identity and HRMS.

## Setting up

1. **Create the databases.** Create one PostgreSQL role and database per service, with a strong password for each, kept in that service's `.env` only.
2. **Generate the signing key.** It goes into identity-service as `JWT_PRIVATE_KEY`:

   ```bash
   openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048
   ```

3. **Register the service clients in Identity.** For each client, generate a secret and put its SHA-256 hash in Identity's settings:

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   ```bash
   python -c "import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" <secret>
   ```

   - `SERVICE_CLIENTS={"hrms-service": "<hash>", "platform-service": "<hash>", "manufacturing-service": "<hash>"}`
   - `SERVICE_CLIENT_SCOPES={"hrms-service": ["identity:sessions.read", "identity:users.read", "platform:notifications.write"], "platform-service": ["identity:sessions.read", "identity:users.read"], "manufacturing-service": ["identity:sessions.read"]}`

   Each other service receives its plain secret as `IDENTITY_CLIENT_SECRET`.
4. **Configure each service.** Copy each `.env.example` to `.env` and fill it in. Then run `alembic upgrade head` in every service.
5. **Create the first administrator.** In identity-service, run `python -m app.scripts.bootstrap --username ... --display-name ... --email ...`. The password is read from `BOOTSTRAP_ADMIN_PASSWORD` or asked for interactively. The script also creates the built-in roles System Administrator and HR Manager.
6. **Start the services.** Start them with `uvicorn app.main:app --port <port> --proxy-headers`, and start the HRMS worker with `python -m app.worker`.
7. **Put nginx in front.** Use `nginx.conf`: set the host name and certificates, and add the `limit_req_zone` line to the `http` block.

## Verification (2026-11-05)

| Check | Result |
|---|---|
| Unit and integration tests | HRMS 205, Identity 6, Platform 4, Manufacturing 2: **217 passed** |
| Frontend calls → routes | **178 of 178** have a route, each in exactly one service |
| Proxy routing | All 178 calls are routed by `nginx.conf` to the service that serves them |
| Response and request shapes | HRMS 141, Identity 11, Platform 10 and Manufacturing 12 interfaces match the frontend TypeScript |
| Migrations | Each service: upgrade, `alembic check` with no drift, downgrade and upgrade |
| End to end (`e2e/`) | **17 of 17**, over real HTTP with all four services running |

The end-to-end checks cover:
- one Identity sign-in working in HRMS, Platform and Manufacturing;
- role changes taking effect;
- CSRF origin checks;
- Identity reading department names from HRMS;
- the merged audit log and the overview;
- HRMS → Platform notification delivery with a service token;
- sign-out refused by every service.

To rerun them:
1. create `e2e_<service>` databases;
2. run `python e2e/prepare.py`;
3. run `python e2e/launch.py`;
4. bootstrap `e2e.admin` with the generated password;
5. run `e2e/e2e.py` with the identity-service virtualenv.

## Decisions and pending items

Each service has its own `docs/` folder:
- HRMS: `MODULE_*_DECISIONS.md` and `HR_CONFIRMATION_PENDING.md`;
- the other three: `docs/DECISIONS.md`.

The main open items:
- the password policy and lockout values (IT);
- the forced password-change screen (G-Q5);
- email and SMS delivery, and the integration connectors;
- the production planning definitions (schedule status, KPIs, the testing stage);
- every HR, payroll and appraisal rule listed in HRMS's pending file.
