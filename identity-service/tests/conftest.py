"""Test harness: a real PostgreSQL test database rebuilt from the migrations once per run; every test runs in one
outer transaction that is rolled back (service commits become savepoints). The RSA signing key is generated
for each run: no key or password is stored in the source.

Never point TEST_DATABASE_URL at a real database: the schema is dropped and recreated.
"""

import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[1]
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
if not TEST_DB_URL:
    raise RuntimeError("Set TEST_DATABASE_URL in the environment, e.g. postgresql+asyncpg://identity:<password>@localhost:5432/identity_test.")
if not TEST_DB_URL.rsplit("/", 1)[-1].endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must point at a database whose name ends with '_test'.")

ORIGIN = "http://localhost:5173"
PRIVATE_PEM = rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
SERVICE_SECRET = secrets.token_urlsafe(32)

os.environ.update({
    "ENVIRONMENT": "test", "DATABASE_URL": TEST_DB_URL, "ALLOWED_ORIGINS": f'["{ORIGIN}"]', "LOG_LEVEL": "WARNING", "JWT_PRIVATE_KEY": PRIVATE_PEM,
    "AUTH_COOKIE_SECURE": "false", "HRMS_BASE_URL": "http://hrms.test",
    "SERVICE_CLIENTS": json.dumps({"hrms-service": hashlib.sha256(SERVICE_SECRET.encode()).hexdigest()}),
    "SERVICE_CLIENT_SCOPES": json.dumps({"hrms-service": ["identity:sessions.read", "identity:users.read"]}),
    "LOCKOUT_ATTEMPTS": "3", "LOCKOUT_MINUTES": "15",
})

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.api.dependencies import get_audit_session_factory  # noqa: E402
from app.database.session import get_db_session  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import auth_service  # noqa: E402


def _alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env={**os.environ, "DATABASE_URL": TEST_DB_URL}, check=True, capture_output=True)


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    yield


@pytest.fixture(autouse=True)
def fresh_ip_limiter():
    auth_service.ip_limiter.hits.clear()
    yield


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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://identity.test", headers={"Origin": ORIGIN}) as c:
        yield c
