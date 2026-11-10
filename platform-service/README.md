# EVR Power ERP: Platform service

Company settings, notifications, integrations, the cross-service audit log and the administration overview
(contracts B2 and G7–G10). FastAPI + PostgreSQL. See `docs/DECISIONS.md` for the rules.

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # fill in DATABASE_URL, the Identity settings and INTEGRATION_ENCRYPTION_KEYS
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8002
TEST_DATABASE_URL=... .venv/bin/python -m pytest
```

Endpoints:
- `/api/v1/admin/settings/company`, `/api/v1/admin/integrations*`, `/api/v1/admin/audit-events`, `/api/v1/admin/overview`;
- `/api/v1/notifications*`;
- the service-to-service endpoint `POST /internal/notifications`, which the proxy must not expose.
