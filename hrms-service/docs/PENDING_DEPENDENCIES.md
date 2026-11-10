# HRMS Backend: Pending Decisions and Dependencies

**Status on 2026-11-05.** Nothing here is assumed resolved. Item numbers refer to `HR_CONFIRMATION_PENDING.md`,
which holds the current value of each item and where it is changed. Every HR value is configurable through the API or
a setting. None is fixed in code, and none was invented: where no rule exists, the rule is not applied.

**Legend:**
- **Blocks:** what cannot work, or cannot go live, until the item is resolved.
- **Default now:** what the system does in the meantime.

## 1. Management

| # | Decision | Default now | Blocks |
|---|---|---|---|
| 21 | Which Identity roles get which organizational scope | **None assigned** | **Nobody sees any employee record** until scopes are assigned (`/hr/setup/employee-access-scopes`) |
| 31 | Who holds `hr.employees:view-sensitive` (bank details) | — | Bank details are visible only to holders |
| 35 | Document verification workflow (who verifies, comments, endpoint) (D24) | Not built; every copy stays "pending" | Document verification |
| 43 | Who besides the owner may see import jobs | Owner only | — |
| 66 | Mobile-app attendance in scope? (with IT and Legal) | Refused | Mobile attendance |
| 98 | Leave reports placed in the Reports module (L27) | Not built here | Leave reports |
| — | Approval of each next module (payroll, performance, reports, HR workspace) | Not started | 54 frontend endpoints |

## 2. HR (and Finance or Legal where noted)

**Organization and employees:** items 1–20 (sample setup template), 22–30 (statuses, reasons, dating limits, probation, uniqueness, mandatory and statutory fields with Legal, employee code, time zone with Platform).
- **Blocks:** go-live with real data. The setup file must be signed (`hr_confirmed: true`) before the loader accepts it in production.

**Documents:** items 32–34 (required types, 30-day expiry window, completion rules), 36 (retention and deletion, with Legal, R4: no delete endpoint), 37 (file types and sizes, with IT).

**Import:** items 40 (columns), 41 (limits, with IT), 42 (missing manager is a warning), 44 (date formats).

**Attendance:** items 45–61 and 64:
- the day status order and weekly offs;
- break deduction, half-day and absent thresholds, overtime rules — all empty, so not applied;
- the correction window;
- the default correction workflow (template);
- back-dating, off by default;
- who records payroll locks, with Finance.

Items 58, 60 and 70 need only confirmation.

**Leave (Module 6):** items 74–97, 99–103, 105. In particular:
- **No leave types, entitlements, policies, holidays or workflows exist** (items 75, 76, 90, 94). Leave cannot be used until HR enters them.
- Leave year (79), proration (81: not applied), carry-forward timing (82), opening balances (83: as adjustments).
- `allowNegativeBalance` (85: blocked by default, owner decision 3), `countOffsWithinLeave` (86), notice and back-dating windows (87).
- Attachment rules (88, 89), started-leave cancellation (93), half-day leave in attendance (96), holiday on a weekly off (97).
- Permission and overtime limits and routing (100–102), dashboard lists (103), year-end pending requests (105).
- Encashment (84, with Finance): not built.

**Payroll (with Finance), before the payroll module:**
- the payroll fields and formats (items 19–20);
- payroll period locks (64);
- all payroll rules, which do not exist yet and will be analysed in that module.

## 3. Identity service (other developer)

| Dependency | Blocks |
|---|---|
| `/auth/login`, `/auth/logout`, `/auth/session` and user/role administration (16 frontend endpoints) | **Real sign-in.** Until then only development tokens work |
| JWT with the agreed claims: `sub`, `name`, `sid`, `employeeId`, `roles`, `permissions` (`AUTH_INTEGRATION.md` §1) | Every HRMS request in production |
| RS256 public key or JWKS URL; issuer and audience values | Production configuration |
| Session revocation endpoint (§2) and the service token HRMS uses to call it | Immediate sign-out of revoked sessions (without it, tokens stay valid until they expire) |
| Add `hr.shifts:assign-backdated` to the permission catalogue (item 62) | Back-dated shift assignments |
| Grant the HR permissions to roles | Access for real users |
| A list of active roles and users (G5, H3; item 104) | Full validation of workflow approvers; the approver options list (until then, roles and users already used in HRMS) |
| Service tokens (client credentials) for HRMS to call Platform | Notification delivery by token instead of a static secret |

## 4. Platform service (other developer)

| Dependency | Blocks |
|---|---|
| `POST /internal/notifications` and a service token (item 99) | Notification delivery. Until then notifications stay queued, visible in `/hr/setup/notification-outbox` |
| Accept `roleCodes` (role recipients), or another way to address a role | Escalation notices to an HR role |
| Company settings (G7): time zone (item 30) and working days (item 92, L18) | Correct "today" outside UTC (`COMPANY_TIME_ZONE`); the `working_days` escalation unit and weekly offs for employees without a shift (`COMPANY_WORKING_DAYS`, empty) |
| Agreement on the audit feed `GET /api/v1/hr/internal/audit-events` (`AUTH_INTEGRATION.md` §4) | HR actions in the administration audit screen. **Not built in HRMS** |
| Notification inbox and preferences endpoints (13 frontend endpoints) | The frontend notification UI |

## 5. Infrastructure and IT

| Dependency | Blocks |
|---|---|
| Server (VPS), PostgreSQL 14+ (tested on 16), and the deployment method (Docker or systemd) | Any deployment. **No Dockerfile, compose file or service unit exists yet** |
| Nginx: path routing (`AUTH_INTEGRATION.md` §5), TLS, HSTS and security headers, request size limits, optional rate limits | Production. **The referenced `deploy/nginx.conf` does not exist** |
| ClamAV `clamd` with signature updates (item 38) | Uploads in production (`MALWARE_SCANNER=clamav` is required) |
| Secret store and key custody: `PAYROLL_ENCRYPTION_KEYS`, `DOCUMENT_ENCRYPTION_KEYS` (item 39), tokens | Production start (the keys are required) |
| Backups: database, storage volume, keys kept separately; restore drills | Safe operation |
| Monitoring and logs (JSON logs to stdout, `/health`, `/health/ready`) | Operations |
| Attendance devices: vendor, connector, offline rule, windows, clock tolerance (items 65, 67–69) | Live punch intake from real devices |
| Retention of raw punches (item 72, with HR and Legal) | — |

## 6. Frontend team

| Dependency | Blocks |
|---|---|
| A reason field in the shift-assign dialog (item 63) | Back-dating from the UI (possible through the API only) |
| Screens for document verification and deletion, once D24 and R4 are decided | Those functions |
| Photo upload (contract D16) | `photoUrl` stays null |
| Cross-origin deployment, if chosen instead of same-origin | Needs CORS added in HRMS first |

## 7. HRMS backend work not yet done (this project)

**Waiting for your approval:**
- payroll (30 endpoints), performance (15), reports (5), HR workspace (4);
- the G6 `payroll` and `performance` areas;
- deployment artifacts (Docker, Nginx, service units);
- cleanup and retention jobs for background jobs, delivered notifications and orphaned files;
- CORS (only if needed);
- the Platform audit feed (after Platform agrees).

**Small documentation corrections found in the review** (not yet made, because this review changes no existing file):
- the header of `HR_CONFIRMATION_PENDING.md` should mention items 74–105;
- item 54 should say leave days are counted since Module 6;
- the `ALLOWED_ORIGINS` comment in `config.py` mentions CORS, but only the CSRF check uses it.
