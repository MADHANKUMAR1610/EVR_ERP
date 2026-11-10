"""Test harness: a real PostgreSQL test database, rebuilt from the Alembic migrations once per run.

Every test runs inside one outer transaction that is rolled back afterwards (service commits become
savepoints), so tests never see each other's data, and the append-only audit log needs no cleanup.

Never point TEST_DATABASE_URL at a real database: the schema is dropped and recreated.
"""

import json
import os
import secrets
import shutil
import tempfile
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import jwt
from cryptography.fernet import Fernet
import pytest

ROOT = Path(__file__).resolve().parents[1]
# No password in the source: set TEST_DATABASE_URL in the environment (see .env.example).
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
if not TEST_DB_URL:
    raise RuntimeError("Set TEST_DATABASE_URL in the environment, e.g. postgresql+asyncpg://hrms:<password>@localhost:5432/hrms_test.")
# Secrets and keys are generated for each test run; none is stored in the source.
DEV_SECRET = secrets.token_urlsafe(48)
TEST_STORAGE_DIR = tempfile.mkdtemp(prefix="hrms-test-storage-")
ORIGIN = "http://localhost:5173"

if not TEST_DB_URL.rsplit("/", 1)[-1].endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must point at a database whose name ends with '_test'.")

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": TEST_DB_URL,
        "ALLOWED_ORIGINS": f'["{ORIGIN}"]',
        "AUTH_DEV_MODE": "true",
        "AUTH_DEV_SECRET": DEV_SECRET,
        "AUTH_REVOCATION_URL": "",
        "LOG_LEVEL": "WARNING",
        "PAYROLL_ENCRYPTION_KEYS": json.dumps([Fernet.generate_key().decode()]),
        "DOCUMENT_ENCRYPTION_KEYS": json.dumps([Fernet.generate_key().decode()]),
        "STORAGE_DIR": TEST_STORAGE_DIR,
        "MALWARE_SCANNER": "none",
        "COMPANY_TIME_ZONE": "UTC",
    }
)

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.api.dependencies import get_audit_session_factory  # noqa: E402
from app.database.session import get_db_session  # noqa: E402
from app.main import create_app  # noqa: E402


def _alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": TEST_DB_URL}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env, check=True, capture_output=True)


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Fresh schema for every test run: downgrade to nothing, then upgrade to head. The synthetic
    files written by the document tests are removed at the end of the run."""
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    yield
    shutil.rmtree(TEST_STORAGE_DIR, ignore_errors=True)


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool)
    conn = await engine.connect()
    outer = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False, autoflush=False, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        await session.close()
        await outer.rollback()
        await conn.close()
        await engine.dispose()


@pytest.fixture
def app(db: AsyncSession):
    application = create_app()

    # Like get_db_session, a failed request must leave no flushed writes behind. Tests share one
    # connection with the denial-audit sessions, so roll back only when the request itself wrote
    # something (in production the denial is written on its own connection and always survives).
    wrote = {"flag": False}
    event.listen(db.sync_session, "after_flush", lambda *_: wrote.update(flag=True))
    event.listen(db.sync_session, "after_commit", lambda *_: wrote.update(flag=False))

    async def _session() -> AsyncIterator[AsyncSession]:
        try:
            yield db
        except Exception:
            if wrote["flag"]:
                await db.rollback()
                wrote["flag"] = False
            raise

    factory = async_sessionmaker(bind=db.bind, expire_on_commit=False, join_transaction_mode="create_savepoint")
    application.dependency_overrides[get_db_session] = _session
    application.dependency_overrides[get_audit_session_factory] = lambda: factory
    return application


@pytest.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://hrms.test") as c:
        yield c


def make_token(
    permissions: list[str],
    *,
    user_id: str = "11111111-1111-1111-1111-111111111111",
    name: str = "Test User",
    employee_id: str | None = None,
    roles: list[str] | None = None,
    expires_in: int = 3600,
    secret: str = DEV_SECRET,
    extra: dict | None = None,
) -> str:
    now = int(time.time())
    claims = {"sub": user_id, "name": name, "permissions": permissions, "roles": roles or [], "employeeId": employee_id, "sid": "s-1", "iat": now, "exp": now + expires_in, **(extra or {})}
    return jwt.encode(claims, secret, algorithm="HS256")


def auth(permissions: list[str], **kwargs) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(permissions, **kwargs)}"}
