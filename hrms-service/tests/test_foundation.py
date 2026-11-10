"""Phase 3 foundation: errors, request IDs, authentication, permissions, CSRF, paging, audit."""

import secrets
import time
import uuid
from datetime import date
from typing import Annotated

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Depends
from sqlalchemy import String, column, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.exc import StaleDataError

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.config import Settings
from app.core.context import SYSTEM_PRINCIPAL, Principal, principal_var
from app.core.errors import UnauthenticatedError
from app.core.permissions import catalogue, has_any, has_permission
from app.core.security import TokenVerifier
from app.database.audit_listener import MissingActorError, acting_as
from app.database.base import AUDIT_FIELD_EXCEPTIONS, AuditMixin, Base, UUIDPrimaryKeyMixin, VersionMixin
from app.models.audit_log_model import AuditLog
from app.repositories.base_repository import parse_sort
from app.schemas.common import CamelModel, PageParams, page_params
from app.services.audit_service import AuditService, diff
from tests.conftest import DEV_SECRET, ORIGIN, auth, make_token

# --- Test-only routes ---------------------------------------------------------------------------


class _Personal(CamelModel):
    first_name: str
    email_address: str


class _Body(CamelModel):
    employee_code: str
    joining_date: date
    personal: _Personal


@pytest.fixture
def probe(app):
    router = APIRouter(prefix="/api/v1/_probe")

    @router.get("/secure")
    async def secure(principal: Annotated[Principal, Depends(require("hr.employees:view"))]) -> dict:
        return {"user": principal.user_id, "employee": principal.employee_id}

    @router.get("/me")
    async def me(principal: CurrentPrincipal) -> dict:
        return {"user": principal.user_id}

    @router.post("/body")
    async def body(payload: _Body, _: CurrentPrincipal) -> dict:
        return payload.model_dump(by_alias=True, mode="json")

    @router.get("/crash")
    async def crash() -> None:
        raise RuntimeError("database password is hunter2")  # must never reach the client

    @router.get("/stale")
    async def stale() -> None:
        raise StaleDataError("concurrent update")

    @router.get("/page")
    async def page(params: Annotated[PageParams, Depends(page_params)]) -> dict:
        parse_sort(params.sort, {"fullName": column("full_name"), "joiningDate": column("joining_date")}, "fullName:asc")
        return params.model_dump(by_alias=True)

    @router.post("/audit")
    async def write_audit(_: CurrentPrincipal, session: DbSession) -> dict:
        AuditService(session).record(module="Employees", action="updated", summary="Probe", entity_type="Employee", entity_id="E-1", changes=diff({"name": "A", "bankAccount": "123"}, {"name": "B", "bankAccount": "456"}))
        await session.commit()
        return {"ok": True}

    app.include_router(router)
    return app


# --- Health and request IDs -----------------------------------------------------------------------


async def test_health_and_request_id(client):
    r = await client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert len(r.headers["x-request-id"]) >= 8
    r = await client.get("/health/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready"}


async def test_request_id_is_reused_when_safe_and_replaced_when_not(client):
    r = await client.get("/health", headers={"X-Request-Id": "abc-12345-req"})
    assert r.headers["x-request-id"] == "abc-12345-req"
    r = await client.get("/health", headers={"X-Request-Id": "bad id <script>"})
    assert r.headers["x-request-id"] != "bad id <script>"


# --- Error envelope -------------------------------------------------------------------------------


async def test_unknown_route_uses_error_envelope(client):
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"error": {"code": "NOT_FOUND", "message": "The requested resource was not found.", "details": []}}
    assert r.headers["x-request-id"]


async def test_validation_errors_use_camel_case_dot_paths(probe, client):
    r = await client.post("/api/v1/_probe/body", json={"employeeCode": "E1", "joiningDate": "not-a-date", "personal": {"firstName": "A"}}, headers=auth([]))
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "VALIDATION_FAILED"
    fields = {d["field"]: d["message"] for d in body["details"]}
    assert fields["joiningDate"] == "Enter a valid date (YYYY-MM-DD)."
    assert fields["personal.emailAddress"] == "This field is required."


async def test_unknown_request_fields_are_rejected(probe, client):
    r = await client.post("/api/v1/_probe/body", json={"employeeCode": "E1", "joiningDate": "2026-01-01", "personal": {"firstName": "A", "emailAddress": "a@b.c"}, "createdBy": "attacker"}, headers=auth([]))
    assert r.status_code == 422
    assert any(d["field"] == "createdBy" for d in r.json()["error"]["details"])


async def test_crash_returns_safe_500_with_request_id(probe, client):
    r = await client.get("/api/v1/_probe/crash")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "INTERNAL"
    assert "hunter2" not in r.text
    assert r.headers["x-request-id"]


async def test_stale_data_becomes_409_stale_version(probe, client):
    r = await client.get("/api/v1/_probe/stale")
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_VERSION"


# --- Authentication ---------------------------------------------------------------------------------


async def test_missing_expired_and_tampered_tokens_are_401(probe, client):
    assert (await client.get("/api/v1/_probe/me")).status_code == 401
    expired = make_token([], expires_in=-120)
    r = await client.get("/api/v1/_probe/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
    forged = make_token(["*"], secret=secrets.token_urlsafe(48))  # signed with a different secret
    assert (await client.get("/api/v1/_probe/me", headers={"Authorization": f"Bearer {forged}"})).status_code == 401
    no_perms = jwt.encode({"sub": "u1", "exp": int(time.time()) + 60}, DEV_SECRET, algorithm="HS256")  # valid signature, no permissions claim
    assert (await client.get("/api/v1/_probe/me", headers={"Authorization": f"Bearer {no_perms}"})).status_code == 401


async def test_session_cookie_is_accepted(probe, client):
    client.cookies.set("evr_session", make_token(["hr.employees:view"], employee_id="E-7"))
    r = await client.get("/api/v1/_probe/secure")
    assert r.status_code == 200 and r.json()["employee"] == "E-7"


def _rsa_pair() -> tuple[str, rsa.RSAPrivateKey]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return public, key


def test_rs256_tokens_from_identity_are_verified_with_issuer_and_audience():
    public, private = _rsa_pair()
    s = Settings(database_url="postgresql+asyncpg://x/y_test", auth_jwt_public_key=public, auth_jwt_issuer="https://identity.evr", auth_jwt_audience="evr-erp")
    verifier = TokenVerifier(s)
    claims = {"sub": "u-9", "name": "Priya", "permissions": ["hr.leave:approve"], "employeeId": "E-9", "roles": ["R-MGR"], "sid": "S9", "iss": "https://identity.evr", "aud": "evr-erp", "exp": int(time.time()) + 600}
    principal = verifier.decode(jwt.encode(claims, private, algorithm="RS256"))
    assert principal.user_id == "u-9" and principal.employee_id == "E-9" and "hr.leave:approve" in principal.permissions and principal.roles == {"R-MGR"}
    with pytest.raises(UnauthenticatedError):
        verifier.decode(jwt.encode({**claims, "aud": "other-app"}, private, algorithm="RS256"))
    with pytest.raises(UnauthenticatedError):
        verifier.decode(jwt.encode({**claims, "iss": "https://evil"}, private, algorithm="RS256"))
    # Without dev mode, HS256 tokens are never accepted, even if signed with a known secret.
    with pytest.raises(UnauthenticatedError):
        verifier.decode(jwt.encode(claims, "anything-at-all-long-enough-for-the-hs256-check", algorithm="HS256"))


def test_production_refuses_unsafe_settings():
    with pytest.raises(ValueError):
        Settings(database_url="postgresql+asyncpg://x/y", environment="production", auth_dev_mode=True, auth_dev_secret="x")
    with pytest.raises(ValueError):
        Settings(database_url="postgresql+asyncpg://x/y", environment="production", allowed_origins=["https://erp.evr"], docs_enabled=False)


async def test_revoked_sessions_are_refused(monkeypatch):
    s = Settings(database_url="postgresql+asyncpg://x/y_test", auth_dev_mode=True, auth_dev_secret="s", auth_revocation_url="https://identity.evr/internal/sessions")
    verifier = TokenVerifier(s)
    calls = []

    class _Resp:
        def __init__(self, active):
            self._active = active

        def raise_for_status(self):
            return None

        def json(self):
            return {"active": self._active}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def get(self, url, headers=None):
            calls.append(url)
            return _Resp(url.endswith("/S-ok"))

    monkeypatch.setattr("app.core.security.httpx.AsyncClient", _Client)
    ok = Principal(user_id="u", name="u", permissions=frozenset(), session_id="S-ok")
    await verifier.ensure_active(ok)
    await verifier.ensure_active(ok)  # cached
    assert calls == ["https://identity.evr/internal/sessions/S-ok"]
    with pytest.raises(UnauthenticatedError):
        await verifier.ensure_active(Principal(user_id="u", name="u", permissions=frozenset(), session_id="S-revoked"))


# --- Permissions ---------------------------------------------------------------------------------------


def test_permission_matching_follows_the_frontend_rules():
    assert has_permission(["*"], "hr.payroll:approve")
    assert has_permission(["hr.payroll:*"], "hr.payroll:approve")
    assert not has_permission(["hr.payroll:*"], "hr.payroll-config:manage")
    assert has_permission(["admin:*"], "admin:organization.manage")
    assert not has_permission(["hr.leave:view"], "hr.leave:approve")
    assert has_any(["hr.leave:view"], ["hr.leave:approve", "hr.leave:view"])
    codes = catalogue()
    assert "hr.employees:view-sensitive" in codes and "admin:policies.payroll-manage" in codes


async def test_missing_permission_is_403_and_audited(probe, client, db):
    r = await client.get("/api/v1/_probe/secure", headers=auth(["hr.leave:view"], name="Ravi"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    denial = (await db.execute(select(AuditLog).where(AuditLog.result == "denied"))).scalars().one()
    assert denial.actor_name == "Ravi" and "hr.employees:view" in denial.summary and denial.request_id == r.headers["x-request-id"]
    assert (await client.get("/api/v1/_probe/secure", headers=auth(["hr.employees:*"]))).status_code == 200


# --- CSRF --------------------------------------------------------------------------------------------------


async def test_cookie_writes_need_an_allowed_origin(probe, client):
    client.cookies.set("evr_session", make_token(["*"]))
    assert (await client.post("/api/v1/_probe/audit")).status_code == 403
    r = await client.post("/api/v1/_probe/audit", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_REJECTED"
    assert (await client.post("/api/v1/_probe/audit", headers={"Origin": ORIGIN})).status_code == 200
    assert (await client.post("/api/v1/_probe/audit", headers={"Referer": f"{ORIGIN}/hr/employees"})).status_code == 200


async def test_bearer_only_writes_are_not_csrf_checked(probe, client):
    assert (await client.post("/api/v1/_probe/audit", headers=auth(["*"]))).status_code == 200


# --- Paging ----------------------------------------------------------------------------------------------------


async def test_paging_defaults_allowed_sizes_and_unknown_sort(probe, client):
    r = await client.get("/api/v1/_probe/page")
    assert r.json() == {"page": 1, "pageSize": 25, "sort": None, "q": None}
    r = await client.get("/api/v1/_probe/page", params={"pageSize": 30})
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "pageSize"
    r = await client.get("/api/v1/_probe/page", params={"sort": "salary:desc"})
    assert r.status_code == 400 and r.json()["error"]["details"][0]["field"] == "sort"
    r = await client.get("/api/v1/_probe/page", params={"sort": "joiningDate:sideways"})
    assert r.status_code == 400
    assert (await client.get("/api/v1/_probe/page", params={"sort": "joiningDate:desc", "page": 2, "q": "  anitha "})).json() == {"page": 2, "pageSize": 25, "sort": "joiningDate:desc", "q": "anitha"}


# --- Audit fields and audit log ----------------------------------------------------------------------------------


class _ProbeBase(DeclarativeBase):
    pass


class _Probe(UUIDPrimaryKeyMixin, AuditMixin, VersionMixin, _ProbeBase):
    __tablename__ = "_audit_probe"
    name: Mapped[str] = mapped_column(String(50))


async def test_audit_fields_come_from_the_principal_never_from_data(db):
    await db.run_sync(lambda s: _ProbeBase.metadata.create_all(s.connection()))
    creator = Principal(user_id="22222222-2222-2222-2222-222222222222", name="Creator", permissions=frozenset())
    editor = Principal(user_id="hr-user-7", name="Editor", permissions=frozenset())  # non-UUID ids are mapped
    with acting_as(creator):
        row = _Probe(name="a", created_by=uuid.uuid4(), updated_by=uuid.uuid4())  # spoofed values are overwritten
        db.add(row)
        await db.flush()
    assert row.created_by == row.updated_by == uuid.UUID("22222222-2222-2222-2222-222222222222")
    assert row.created_at.tzinfo is not None and row.version == 1
    created_at = row.created_at
    with acting_as(editor):
        row.name = "b"
        await db.flush()
    assert row.created_by == uuid.UUID("22222222-2222-2222-2222-222222222222")
    assert row.updated_by == editor.actor_uuid != row.created_by
    assert row.updated_at >= created_at and row.version == 2
    with acting_as(SYSTEM_PRINCIPAL):
        row.name = "c"
        await db.flush()
    assert str(row.updated_by) == "00000000-0000-0000-0000-000000000001"


async def test_writes_without_an_actor_are_refused(db):
    await db.run_sync(lambda s: _ProbeBase.metadata.create_all(s.connection()))
    token = principal_var.set(None)
    try:
        db.add(_Probe(name="x"))
        with pytest.raises(MissingActorError):
            await db.flush()
    finally:
        principal_var.reset(token)
        await db.rollback()


async def test_optimistic_concurrency_detects_concurrent_updates(db):
    await db.run_sync(lambda s: _ProbeBase.metadata.create_all(s.connection()))
    with acting_as(SYSTEM_PRINCIPAL):
        row = _Probe(name="a")
        db.add(row)
        await db.flush()
        await db.execute(text("UPDATE _audit_probe SET version = version + 1 WHERE id = :id"), {"id": row.id})
        row.name = "b"
        with pytest.raises(StaleDataError):
            await db.flush()


def test_every_business_table_has_the_audit_columns():
    import app.models  # noqa: F401

    required = {"created_at", "created_by", "updated_at", "updated_by"}
    missing = {t.name: sorted(required - set(t.columns.keys())) for t in Base.metadata.sorted_tables if t.name not in AUDIT_FIELD_EXCEPTIONS and not required <= set(t.columns.keys())}
    assert missing == {}


async def test_audit_log_masks_sensitive_values_and_is_append_only(probe, client, db):
    r = await client.post("/api/v1/_probe/audit", headers=auth(["*"], name="Anita"))
    assert r.status_code == 200
    entry = (await db.execute(select(AuditLog).where(AuditLog.summary == "Probe"))).scalars().one()
    assert entry.actor_name == "Anita" and entry.request_id == r.headers["x-request-id"]
    changes = {c["field"]: c for c in entry.changes}
    assert changes["name"] == {"field": "name", "before": "A", "after": "B"}
    assert changes["bankAccount"]["before"] == "••••" and "456" not in str(entry.changes)
    for statement in ("UPDATE audit_log SET summary = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
        nested = await db.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text(statement))
        await nested.rollback()
