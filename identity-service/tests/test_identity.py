"""Identity: sign-in, lockout, sessions and revocation, forced password change, users, roles, safeguards, internal endpoints."""

from datetime import UTC, datetime, timedelta

import httpx
import jwt
from sqlalchemy import select

from app.core.context import SYSTEM_PRINCIPAL
from app.core.passwords import hash_password
from app.database.audit_listener import acting_as
from app.models.audit_log_model import AuditLog
from app.models.identity_model import Role, UserAccount
from app.services import hrms_client
from tests.conftest import PRIVATE_PEM, SERVICE_SECRET

API = "/api/v1"
ADMIN_PW = "Admin-pass-2026"
USER_PW = "Worker-pass-2026"


async def seed(db, *, admin_roles=("admin:*",)):
    with acting_as(SYSTEM_PRINCIPAL):
        admin_role = Role(name="System Administrator", description="", permissions=list(admin_roles), system=True)
        staff = Role(name="Staff", description="", permissions=["hr.self:view"])
        db.add_all([admin_role, staff])
        await db.flush()
        admin = UserAccount(username="it.admin", display_name="IT Admin", email="it@example.com", status="active", password_hash=hash_password(ADMIN_PW),
                            password_set_at=datetime.now(UTC), role_ids=[admin_role.id])
        db.add(admin)
        await db.commit()
    return admin, admin_role, staff


async def login(client, username="it.admin", password=ADMIN_PW):
    return await client.post(f"{API}/auth/login", json={"username": username, "password": password})


def details(r) -> dict:
    return {d["field"]: d["message"] for d in r.json()["error"]["details"]}


def public_key():
    from cryptography.hazmat.primitives import serialization

    return serialization.load_pem_private_key(PRIVATE_PEM.encode(), password=None).public_key()


async def test_login_session_logout_and_token_claims(client, db):
    admin, admin_role, _ = await seed(db)
    r = await login(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["username"] == "it.admin" and body["user"]["roles"] == ["System Administrator"] and body["user"]["permissions"] == ["admin:*"] and body["expiresAt"]
    cookie = r.headers["set-cookie"]
    assert "evr_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax")
    token = client.cookies["evr_session"]
    claims = jwt.decode(token, public_key(), algorithms=["RS256"], audience="evr-erp", issuer="evr-identity")
    assert claims["sub"] == str(admin.id) and claims["roles"] == [str(admin_role.id)] and claims["permissions"] == ["admin:*"] and claims["sid"] and claims["name"] == "IT Admin"
    assert jwt.get_unverified_header(token)["kid"] == "identity-1"
    jwks = (await client.get("/.well-known/jwks.json")).json()
    assert jwks["keys"][0]["kty"] == "RSA" and "d" not in jwks["keys"][0], "only the public key is published"

    assert (await client.get(f"{API}/auth/session")).json()["user"]["id"] == str(admin.id)
    assert (await client.post(f"{API}/auth/logout")).status_code == 204
    client.cookies.set("evr_session", token)
    assert (await client.get(f"{API}/auth/session")).status_code == 401, "a signed-out session's token stops working"
    assert (await client.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {token}"})).status_code == 401


async def test_generic_errors_lockout_and_unlock(client, db):
    await seed(db)
    wrong = await login(client, password="nope")
    unknown = await login(client, username="ghost", password="nope")
    assert wrong.status_code == unknown.status_code == 401 and wrong.json()["error"]["code"] == unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"], "never reveal which field was wrong"
    await login(client, password="nope")
    await login(client, password="nope")  # third failure -> locked
    locked = await login(client)
    assert locked.status_code == 401, "a locked account refuses even the right password"
    user = await db.scalar(select(UserAccount).where(UserAccount.username == "it.admin"))
    assert user.status == "locked" and user.locked_until is not None
    with acting_as(SYSTEM_PRINCIPAL):
        user.locked_until = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
    assert (await login(client)).status_code == 200, "the lock expires by itself"
    await db.refresh(user)
    assert user.status == "active" and user.failed_attempts == 0
    audit = (await db.scalars(select(AuditLog.summary))).all()
    assert all(ADMIN_PW not in s for s in audit), "no password in the audit log"


async def test_users_roles_and_safeguards(client, db):
    admin, admin_role, staff = await seed(db)
    admin_id, admin_role_id, staff_id = str(admin.id), str(admin_role.id), str(staff.id)
    await login(client)
    employees = {"e-1": {"id": "e-1", "employeeCode": "EVR-1001", "display": {"fullName": "Ravi Iyer", "department": "Quality", "reportingManager": {"id": "e-9", "name": "Meena Rao"}},
                         "employment": {"departmentId": "d-qa"}}}

    def hrms(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"].startswith("Bearer "), "HRMS is called with the caller's session"
        eid = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=employees[eid]) if eid in employees else httpx.Response(404, json={})

    hrms_client.transport = httpx.MockTransport(hrms)
    try:
        weak = await client.post(f"{API}/admin/users", json={"username": "ravi", "displayName": "Ravi Iyer", "email": "ravi@example.com", "roleIds": [staff_id],
                                                            "departmentId": None, "employeeId": "e-1", "password": "short1", "mustChangePassword": True})
        assert weak.status_code == 422 and "at least 12 characters" in details(weak)["password"]
        r = await client.post(f"{API}/admin/users", json={"username": "ravi", "displayName": "Ravi Iyer", "email": "Ravi@Example.com", "roleIds": [staff_id],
                                                         "departmentId": None, "employeeId": "e-1", "password": USER_PW, "mustChangePassword": True})
        assert r.status_code == 201, r.text
        ravi = r.json()
        assert ravi["employee"] == {"id": "e-1", "employeeCode": "EVR-1001", "fullName": "Ravi Iyer"} and ravi["department"] == {"id": "d-qa", "name": "Quality"}
        assert ravi["reportingManager"] == {"id": "e-9", "fullName": "Meena Rao"} and ravi["mustChangePassword"] is True and "password" not in r.text.lower().replace("mustchangepassword", "").replace("passwordsetat", "")
        dup = await client.post(f"{API}/admin/users", json={"username": "RAVI", "displayName": "Other", "email": "ravi@example.com", "roleIds": [], "departmentId": None,
                                                           "employeeId": "e-1", "password": USER_PW, "mustChangePassword": False})
        assert dup.status_code == 422 and {"username", "email", "employeeId"} <= set(details(dup))
        missing = await client.post(f"{API}/admin/users", json={"username": "x.user", "displayName": "X User", "email": "x@example.com", "roleIds": [], "departmentId": None,
                                                               "employeeId": "e-404", "password": USER_PW, "mustChangePassword": False})
        assert missing.status_code == 422 and "employeeId" in details(missing)
    finally:
        hrms_client.transport = None

    listed = (await client.get(f"{API}/admin/users", params={"q": "evr-1001"})).json()
    assert listed["meta"]["totalItems"] == 1 and listed["items"][0]["username"] == "ravi"
    assert (await client.get(f"{API}/admin/users", params={"roleId": admin_role_id})).json()["meta"]["totalItems"] == 1

    # Forced password change: the session works but carries no permissions until changed.
    other = httpx.AsyncClient(transport=client._transport, base_url="http://identity.test", headers={"Origin": "http://localhost:5173"})
    first = await other.post(f"{API}/auth/login", json={"username": "ravi", "password": USER_PW})
    assert first.status_code == 200 and first.json()["user"]["mustChangePassword"] is True and first.json()["user"]["permissions"] == []
    changed = await other.post(f"{API}/auth/password", json={"currentPassword": USER_PW, "newPassword": "Chosen-pass-2026x"})
    assert changed.status_code == 200, changed.text
    assert changed.status_code == 200 and changed.json()["user"]["permissions"] == ["hr.self:view"] and changed.json()["user"]["mustChangePassword"] is False

    # HR reset: ends the user's sessions.
    ravi = (await client.get(f"{API}/admin/users/{ravi['id']}")).json()
    reset = await client.post(f"{API}/admin/users/{ravi['id']}/password", json={"password": "Reset-pass-2026x", "mustChangePassword": False, "version": ravi["version"]})
    assert reset.status_code == 200 and reset.json()["passwordSetAt"]
    assert (await other.get(f"{API}/auth/session")).status_code == 401, "a reset ends existing sessions"
    activity = (await client.get(f"{API}/admin/users/{ravi['id']}/activity")).json()
    assert {"created", "signed_in", "password_changed", "password_reset"} <= {a["action"] for a in activity}

    # Safeguards.
    me = (await client.get(f"{API}/admin/users/{admin_id}")).json()
    assert (await client.post(f"{API}/admin/users/{admin_id}/status", json={"status": "inactive", "reason": "Leaving", "version": me["version"]})).status_code == 409
    drop = await client.put(f"{API}/admin/users/{admin_id}", json={"username": "it.admin", "displayName": "IT Admin", "email": "it@example.com", "roleIds": [staff_id],
                                                                   "departmentId": None, "employeeId": None, "version": me["version"]})
    assert drop.status_code == 409 and "manage roles" in drop.json()["error"]["message"], "the last administrator stays"
    role = (await client.get(f"{API}/admin/roles/{admin_role_id}")).json()
    assert role["grantsAdministration"] is True and role["userCount"] == 1 and role["system"] is True
    off = await client.put(f"{API}/admin/roles/{admin_role_id}", json={"name": "System Administrator", "description": "", "permissions": ["admin:*"], "active": False, "version": role["version"]})
    assert off.status_code == 409
    rename = await client.put(f"{API}/admin/roles/{admin_role_id}", json={"name": "Root", "description": "", "permissions": ["admin:*"], "active": True, "version": role["version"]})
    assert rename.status_code == 422 and "renamed" in details(rename)["name"]

    new_role = await client.post(f"{API}/admin/roles", json={"name": "HR Executive", "description": "Daily HR work", "permissions": ["hr.employees:view", "hr.leave:*", "custom.module:run"]})
    assert new_role.status_code == 201 and new_role.json()["permissions"] == ["custom.module:run", "hr.employees:view", "hr.leave:*"], "wildcards and unknown codes are kept"
    assert (await client.post(f"{API}/admin/roles", json={"name": "hr executive", "permissions": []})).status_code == 422
    users_of = (await client.get(f"{API}/admin/roles/{staff_id}/users")).json()
    assert [u["username"] for u in users_of] == ["ravi"]
    catalogue = (await client.get(f"{API}/admin/permissions")).json()
    rows = {r["id"]: r for r in catalogue}
    assert rows["hr.leave"]["actions"]["approve"] == "hr.leave:approve" and rows["hr.leave"]["actions"]["reject"] == "hr.leave:approve"
    assert rows["admin.users"]["actions"] == {"view": "admin:users.view", "configure": "admin:users.manage"} and rows["admin.users"]["group"] == "Administration"
    assert any(x["code"] == "hr.shifts:assign-backdated" for x in rows["hr.shifts"]["extra"])

    # Deactivating another user ends their sessions.
    again = await other.post(f"{API}/auth/login", json={"username": "ravi", "password": "Reset-pass-2026x"})
    assert again.status_code == 200
    ravi = (await client.get(f"{API}/admin/users/{ravi['id']}")).json()  # signing in changes the account (last sign-in)
    off = await client.post(f"{API}/admin/users/{ravi['id']}/status", json={"status": "inactive", "reason": "Left the company", "version": ravi["version"]})
    assert off.status_code == 200 and off.json()["status"] == "inactive"
    assert (await other.get(f"{API}/auth/session")).status_code == 401
    assert (await other.post(f"{API}/auth/login", json={"username": "ravi", "password": "Reset-pass-2026x"})).status_code == 401
    await other.aclose()

    # Permissions are enforced and denials audited.
    staff_client = httpx.AsyncClient(transport=client._transport, base_url="http://identity.test", headers={"Origin": "http://localhost:5173"})
    with acting_as(SYSTEM_PRINCIPAL):
        db.add(UserAccount(username="plain", display_name="Plain User", email="plain@example.com", status="active", password_hash=hash_password(USER_PW), role_ids=[__import__('uuid').UUID(staff_id)]))
        await db.commit()
    assert (await staff_client.post(f"{API}/auth/login", json={"username": "plain", "password": USER_PW})).status_code == 200
    assert (await staff_client.get(f"{API}/admin/users")).status_code == 403
    await staff_client.aclose()
    denied = (await db.scalars(select(AuditLog).where(AuditLog.result == "denied"))).all()
    assert denied
    assert all(USER_PW not in (a.summary + str(a.changes)) for a in (await db.scalars(select(AuditLog))).all())


async def test_internal_service_endpoints(client, db):
    admin, admin_role, _ = await seed(db)
    bad = await client.post("/internal/service-tokens", json={"clientId": "hrms-service", "clientSecret": "wrong"})
    assert bad.status_code == 401
    tok = await client.post("/internal/service-tokens", json={"clientId": "hrms-service", "clientSecret": SERVICE_SECRET})
    assert tok.status_code == 200, tok.text
    service = {"Authorization": f"Bearer {tok.json()['accessToken']}"}
    sid = jwt.decode((await login(client)).cookies["evr_session"], public_key(), algorithms=["RS256"], audience="evr-erp")["sid"]
    assert (await client.get(f"/internal/sessions/{sid}", headers=service)).json() == {"active": True}
    users = (await client.get("/internal/users", params={"ids": str(admin.id)}, headers=service)).json()
    assert users == [{"id": str(admin.id), "name": "IT Admin", "employeeId": None, "active": True, "roleIds": [str(admin_role.id)]}]
    assert [r["name"] for r in (await client.get("/internal/roles", headers=service)).json()] == ["Staff", "System Administrator"]
    user_token = {"Authorization": f"Bearer {client.cookies['evr_session']}"}
    assert (await client.get(f"/internal/sessions/{sid}", headers=user_token)).status_code == 401, "a user session token is not a service token"
    await client.post(f"{API}/auth/logout")
    assert (await client.get(f"/internal/sessions/{sid}", headers=service)).json() == {"active": False}


async def test_rate_limit_and_login_csrf(client, db, monkeypatch):
    await seed(db)
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "login_rate_per_ip_per_minute", 2)
    await login(client, password="x")
    await login(client, password="x")
    assert (await login(client)).status_code == 429
    foreign = await client.post(f"{API}/auth/login", json={"username": "it.admin", "password": ADMIN_PW}, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403


async def test_internal_views_for_platform(client, db):
    admin, admin_role, staff = await seed(db)
    admin_role_id = str(admin_role.id)
    await login(client)
    counts = (await client.get("/internal/overview-counts")).json()
    assert counts == {"users": {"total": 1, "active": 1, "invited": 0, "inactive": 0, "locked": 0}, "roles": {"total": 2, "administrators": 1}}
    audit = (await client.get("/internal/audit-events", params={"limit": 5})).json()
    assert audit["total"] >= 1 and audit["items"][0]["module"] == "Identity" and "Identity" in audit["facets"]["modules"]
    tok = (await client.post("/internal/service-tokens", json={"clientId": "hrms-service", "clientSecret": SERVICE_SECRET})).json()["accessToken"]
    by_role = (await client.get("/internal/users", params={"roleIds": admin_role_id, "activeOnly": "true"}, headers={"Authorization": f"Bearer {tok}"})).json()
    assert [u["name"] for u in by_role] == ["IT Admin"]
    none = (await client.get("/internal/users", params={"employeeIds": "e-unknown"}, headers={"Authorization": f"Bearer {tok}"})).json()
    assert none == []
