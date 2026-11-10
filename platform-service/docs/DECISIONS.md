# Platform service: Decisions and Scope

Recorded 2026-11-05. The owner asked for the Platform APIs and chose separate services. The design follows contracts
**B2**, **G7–G10** and hrms-service `docs/AUTH_INTEGRATION.md`.

## Scope: the 13 frontend endpoints

| Area | Endpoints | Permission |
|---|---|---|
| Company settings (G7) | `GET` / `PUT /admin/settings/company` | `admin:settings.view` / `admin:settings.manage` |
| Notifications (B2, G8) | feed, history, preferences (GET, PUT), mark one read, mark all read | signed in; only the caller's own |
| Integrations (G9) | list, save, test | `admin:integrations.view` / `admin:integrations.manage` |
| Audit (G10) | `GET /admin/audit-events` | `admin:audit.view` |
| Overview (G10) | `GET /admin/overview` | `admin:view` |

**Addition:** `POST /internal/notifications`, for other services. It needs a service token with the scope `platform:notifications.write`.

## Rules

- **Sign-in:** Platform verifies the Identity session token exactly as HRMS does: RS256 with the JWKS or public key, issuer and audience checks, and a revocation check against Identity.
- **Company settings:** nothing is pre-filled. Until an administrator saves them, the fields are empty and the numbers are null. The first save uses `version` 0.
- **Validation:**
  - time zone: an IANA name;
  - currency: an ISO 4217 code;
  - locale: a BCP 47 tag;
  - website: https only;
  - working days: each weekday at most once;
  - week start: 1–7; fiscal year start month: 1–12.
- **Notifications:**
  - only the caller's own; anyone else's is a 404;
  - links must be app-relative, and anything else is dropped;
  - recipients by `employeeIds` or `roleCodes` (Identity role ids) are resolved through Identity with a service token.
- **Channels:**
  - in-app is the only available channel;
  - email and SMS are shown as **unavailable**, because no delivery integration is built; the backend forces them off and never claims external delivery;
  - a user who switched a category's in-app delivery off does not receive it;
  - mandatory categories come from `NOTIFICATION_MANDATORY_CATEGORIES`, empty until HR/IT decide.
- **Integrations:**
  - the five known integrations are listed;
  - **secrets are write-only:** stored encrypted (Fernet keys in `INTEGRATION_ENCRYPTION_KEYS`) and never returned (`value` null, only `isSet`); an omitted secret keeps the stored value, and audit entries only say a secret changed;
  - the setting keys of each integration are a technical proposal, **pending IT**;
  - no connector is built, so the connection status stays `unknown`, and a test answers `ok: false` with the reason;
  - an integration cannot be enabled before its required settings are entered.
- **Audit screen:**
  - Platform asks Identity and HRMS **with the caller's own session**, so each applies its own permissions;
  - it merges their events with its own, newest first, and pages the result;
  - a service the caller may not read is left out.
- **Overview:** user and role counts come from Identity; departments, designations and workflows from HRMS; integrations needing attention from Platform; and the latest audit events.

## Pending

- Email and SMS delivery, and the integration connectors (IT).
- The integration setting keys (IT).
- Mandatory notification categories (HR/IT).
- Who may see the notifications page (G-Q3).
- Audit retention and export (G-Q7).
