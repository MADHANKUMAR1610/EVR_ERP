# EVR Power ERP: Manufacturing service

Read-only production work orders, the shop-floor route and the company dashboard. FastAPI + PostgreSQL.
See `docs/DECISIONS.md` for the definitions and what is pending.

```bash
python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # fill in DATABASE_URL and the Identity settings
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --port 8003
TEST_DATABASE_URL=... .venv/bin/python -m pytest
```
