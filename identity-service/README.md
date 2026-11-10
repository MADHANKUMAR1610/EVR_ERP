# EVR Power ERP: Identity service

Sign-in, sessions, users, roles and the permission catalogue (contracts B1, G2 and G3). FastAPI + PostgreSQL.
Session tokens are RS256 JWTs in an httpOnly cookie, and HRMS and the other services verify them with the JWKS.
See `docs/DECISIONS.md` for the rules.

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # fill in DATABASE_URL and JWT_PRIVATE_KEY
.venv/bin/alembic upgrade head
.venv/bin/python -m app.scripts.bootstrap --username it.admin --display-name "IT Administrator" --email it@example.com
.venv/bin/uvicorn app.main:app --port 8001
TEST_DATABASE_URL=... .venv/bin/python -m pytest
```

Endpoints:
- `/api/v1/auth/*`;
- `/api/v1/admin/users*`, `/api/v1/admin/roles*`, `/api/v1/admin/permissions`;
- the JWKS at `/.well-known/jwks.json`;
- service-to-service endpoints under `/internal/*`, which the proxy must not expose.
