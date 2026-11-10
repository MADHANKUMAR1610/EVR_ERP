"""Test harness: a real PostgreSQL test database rebuilt from the migrations once per run; every test runs in one
outer transaction that is rolled back (service commits become savepoints). Tokens are signed with an RSA key generated
for each run (standing in for the Identity service): no key or password is stored in the source.

Never point TEST_DATABASE_URL at a real database: the schema is dropped and recreated.
"""

import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from pathlib import Path

import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[1]
TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "")
if not TEST_DB_URL:
    raise RuntimeError("Set TEST_DATABASE_URL in the environment, e.g. postgresql+asyncpg://platform:<password>@localhost:5432/platform_test.")
if not TEST_DB_URL.rsplit("/", 1)[-1].endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must point at a database whose name ends with '_test'.")

ORIGIN = "http://localhost:5173"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = _KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
PUBLIC_PEM = _KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

os.environ.update({
    "ENVIRONMENT": "test", "DATABASE_URL": TEST_DB_URL, "ALLOWED_ORIGINS": f'["{ORIGIN}"]', "LOG_LEVEL": "WARNING", "AUTH_JWT_PUBLIC_KEY": PUBLIC_PEM,
    "AUTH_REVOCATION_URL": "", "IDENTITY_BASE_URL": "http://identity.test", "IDENTITY_CLIENT_ID": "platform-service", "IDENTITY_CLIENT_SECRET": secrets.token_urlsafe(16),
    "HRMS_BASE_URL": "http://hrms.test", "INTEGRATION_ENCRYPTION_KEYS": json.dumps([Fernet.generate_key().decode()]),
})


def user_token(user_id: str = "11111111-1111-1111-1111-111111111111", permissions=("admin:*",), name: str = "Test Admin", sid: str = "s-1") -> str:
    now = int(time.time())
    return jwt.encode({"iss": "evr-identity", "aud": "evr-erp", "sub": user_id, "name": name, "sid": sid, "roles": [], "permissions": list(permissions), "iat": now, "exp": now + 3600},
                      PRIVATE_PEM, algorithm="RS256")


def service_token(scopes=("platform:notifications.write",), client="hrms-service") -> str:
    now = int(time.time())
    return jwt.encode({"iss": "evr-identity", "aud": "evr-internal", "sub": client, "permissions": list(scopes), "iat": now, "exp": now + 600}, PRIVATE_PEM, algorithm="RS256")


def auth(**kw) -> dict:
    return {"Authorization": f"Bearer {user_token(**kw)}"}


from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.api.dependencies import get_audit_session_factory  # noqa: E402
from app.database.session import get_db_session  # noqa: E402
from app.main import create_app  # noqa: E402


def _alembic(*args: str) -> None:
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env={**os.environ, "DATABASE_URL": TEST_DB_URL}, check=True, capture_output=True)


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
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
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://platform.test", headers={"Origin": ORIGIN}) as c:
        yield c
