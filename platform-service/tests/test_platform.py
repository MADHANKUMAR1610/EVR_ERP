"""Platform: company settings, notifications (delivery, own feed, read marks, preferences), integrations (write-only
secrets), the merged audit log and the overview. Identity and HRMS are mocked with httpx.MockTransport."""

import httpx
import pytest
from sqlalchemy import select

from app.core import service_tokens
from app.models.audit_log_model import AuditLog
from app.models.platform_model import Integration
from app.services import peers
from tests.conftest import auth, service_token

API = "/api/v1"
ME = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
SETTINGS = {"legalName": "EVR Power Private Limited", "displayName": "EVR Power", "registrationNumber": "", "taxId": "", "address": {"line1": "Plot 7", "city": "Chennai", "country": "India"},
            "phone": "", "email": "office@example.com", "website": "https://example.com", "timeZone": "Asia/Kolkata", "currency": "INR", "locale": "en-IN", "dateFormat": "DD-MM-YYYY",
            "timeFormat": "24h", "weekStart": 1, "workingDays": [1, 2, 3, 4, 5, 6], "fiscalYearStartMonth": 4}


def details(r) -> dict:
    return {d["field"]: d["message"] for d in r.json()["error"]["details"]}


@pytest.fixture
def peers_mock():
    calls = []
    state = {"identity_users": [], "identity_audit": None, "hrms_audit": None, "identity_counts": None, "hrms_counts": None}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path == "/internal/service-tokens":
            return httpx.Response(200, json={"accessToken": service_token(("identity:users.read",), "platform-service"), "expiresIn": 900})
        if path == "/internal/users":
            return httpx.Response(200, json=state["identity_users"])
        if path == "/internal/audit-events":
            return httpx.Response(200, json=state["identity_audit"]) if state["identity_audit"] else httpx.Response(403, json={})
        if path == "/api/v1/hr/internal/audit-events":
            return httpx.Response(200, json=state["hrms_audit"]) if state["hrms_audit"] else httpx.Response(403, json={})
        if path == "/internal/overview-counts":
            return httpx.Response(200, json=state["identity_counts"])
        if path == "/api/v1/hr/internal/admin-counts":
            return httpx.Response(200, json=state["hrms_counts"])
        return httpx.Response(404, json={})

    mock = httpx.MockTransport(handler)
    peers.transport = service_tokens.transport = mock
    yield state, calls
    peers.transport = service_tokens.transport = None


async def test_company_settings(client):
    empty = (await client.get(f"{API}/admin/settings/company", headers=auth())).json()
    assert empty["legalName"] == "" and empty["timeZone"] == "" and empty["weekStart"] is None and empty["version"] == 0, "nothing is pre-filled"
    bad = await client.put(f"{API}/admin/settings/company", json={**SETTINGS, "timeZone": "Mars/Base", "currency": "inr", "website": "http://x.com", "workingDays": [], "version": 0}, headers=auth())
    assert bad.status_code == 422 and {"timeZone", "currency", "website", "workingDays"} <= set(details(bad))
    r = await client.put(f"{API}/admin/settings/company", json={**SETTINGS, "version": 0}, headers=auth())
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["timeZone"] == "Asia/Kolkata" and saved["version"] == 1 and saved["updatedBy"] == "Test Admin"
    assert (await client.put(f"{API}/admin/settings/company", json={**SETTINGS, "version": 0}, headers=auth())).status_code == 409
    assert (await client.put(f"{API}/admin/settings/company", json={**SETTINGS, "version": 1}, headers=auth(permissions=["admin:settings.view"]))).status_code == 403
    assert (await client.get(f"{API}/admin/settings/company", headers=auth(permissions=["admin:settings.view"]))).status_code == 200


async def test_notifications_delivery_feed_and_preferences(client, peers_mock):
    state, calls = peers_mock
    state["identity_users"] = [{"id": OTHER, "name": "Ravi", "employeeId": "e-1", "active": True, "roleIds": []}]
    svc = {"Authorization": f"Bearer {service_token()}"}
    body = {"userIds": [ME], "employeeIds": ["e-1"], "category": "approval", "title": "Leave request awaiting your approval", "message": "EVR-1042 · 2 days", "link": "https://evil.example"}
    r = await client.post("/internal/notifications", json=body, headers=svc)
    assert r.status_code == 200 and r.json() == {"delivered": 2, "skipped": 0}, r.text
    lookup = next(c for c in calls if c.url.path == "/internal/users")
    assert lookup.url.params["employeeIds"] == "e-1" and lookup.headers["authorization"].startswith("Bearer "), "recipients are resolved with a service token"
    assert (await client.post("/internal/notifications", json=body, headers=auth())).status_code == 401, "a user session is not a service token"
    assert (await client.post("/internal/notifications", json=body, headers={"Authorization": f"Bearer {service_token(('other:scope',))}"})).status_code == 403

    feed = (await client.get(f"{API}/notifications", headers=auth())).json()
    assert feed["unreadCount"] == 1 and len(feed["items"]) == 1 and feed["items"][0]["link"] is None, "external links are dropped"
    nid = feed["items"][0]["id"]
    assert (await client.post(f"{API}/notifications/{nid}/read", headers=auth(user_id=OTHER))).status_code == 404, "only the caller's own"
    assert (await client.post(f"{API}/notifications/{nid}/read", headers=auth())).status_code == 204
    assert (await client.get(f"{API}/notifications", headers=auth())).json()["unreadCount"] == 0
    history = (await client.get(f"{API}/notifications/history", params={"status": "read"}, headers=auth())).json()
    assert history["meta"]["totalItems"] == 1 and history["unreadCount"] == 0

    prefs = (await client.get(f"{API}/notifications/preferences", headers=auth(user_id=OTHER))).json()
    assert {c["channel"]: c["available"] for c in prefs["channels"]} == {"in_app": True, "email": False, "sms": False} and prefs["version"] == 0
    saved = await client.put(f"{API}/notifications/preferences", json={"categories": [{"category": "approval", "channels": {"in_app": False, "email": True, "sms": True}}], "version": 0},
                             headers=auth(user_id=OTHER))
    assert saved.status_code == 200
    approval = next(c for c in saved.json()["categories"] if c["category"] == "approval")
    assert approval["channels"] == {"in_app": False, "email": False, "sms": False}, "unavailable channels are forced off"
    again = await client.post("/internal/notifications", json={**body, "link": "/hr/approvals"}, headers=svc)
    assert again.json() == {"delivered": 1, "skipped": 1}, "a user who switched the category off does not receive it"
    assert (await client.get(f"{API}/notifications", headers=auth())).json()["items"][0]["link"] == "/hr/approvals"
    assert (await client.post(f"{API}/notifications/read-all", headers=auth())).status_code == 204
    assert (await client.get(f"{API}/notifications", headers=auth())).json()["unreadCount"] == 0


async def test_integrations_keep_secrets_write_only(client, db):
    listed = (await client.get(f"{API}/admin/integrations", headers=auth())).json()
    assert [i["id"] for i in listed] == ["INT-ZOHO", "INT-DEVICES", "INT-EMAIL", "INT-SMS", "INT-SSO"] and all(i["configurationStatus"] == "not_configured" and i["connectionStatus"] == "unknown" for i in listed)
    sms = await client.put(f"{API}/admin/integrations/INT-SMS", json={"enabled": True, "values": {"provider": "Acme"}, "secrets": {}, "version": 0}, headers=auth())
    assert sms.status_code == 422 and "enabled" in details(sms)
    r = await client.put(f"{API}/admin/integrations/INT-SMS", json={"enabled": True, "values": {"provider": "Acme", "senderId": "EVRPWR"}, "secrets": {"apiKey": "sk-live-123456"}, "version": 0}, headers=auth())
    assert r.status_code == 200, r.text
    out = r.json()
    key = next(s for s in out["settings"] if s["key"] == "apiKey")
    assert key == {"key": "apiKey", "label": "API key", "secret": True, "value": None, "isSet": True, "required": True} and out["configurationStatus"] == "configured"
    assert "sk-live-123456" not in r.text
    row = await db.scalar(select(Integration).where(Integration.code == "INT-SMS"))
    assert "sk-live-123456" not in str(row.secrets), "secrets are stored encrypted"
    kept = await client.put(f"{API}/admin/integrations/INT-SMS", json={"enabled": True, "values": {"senderId": "EVRHR"}, "secrets": {}, "version": out["version"]}, headers=auth())
    assert next(s for s in kept.json()["settings"] if s["key"] == "apiKey")["isSet"] is True, "an omitted secret keeps the stored value"
    assert (await client.put(f"{API}/admin/integrations/INT-SMS", json={"enabled": True, "values": {"apiKey": "x"}, "secrets": {}, "version": kept.json()["version"]}, headers=auth())).status_code == 422
    test = (await client.post(f"{API}/admin/integrations/INT-SMS/test", headers=auth())).json()
    assert test["ok"] is False and "No connector" in test["message"]
    audit = (await db.scalars(select(AuditLog))).all()
    assert all("sk-live-123456" not in (a.summary + str(a.changes)) for a in audit)
    assert (await client.put(f"{API}/admin/integrations/INT-SMS", json={"enabled": False, "version": 3}, headers=auth(permissions=["admin:integrations.view"]))).status_code == 403


async def test_audit_merges_services_and_overview(client, peers_mock):
    state, calls = peers_mock
    await client.put(f"{API}/admin/settings/company", json={**SETTINGS, "version": 0}, headers=auth())
    event = lambda i, at, module: {"id": i, "at": at, "actor": {"id": "u-9", "name": "Asha HR"}, "module": module, "action": f"{module.lower()}.saved", "record": None, "result": "success",
                                  "summary": f"{module} change {i}", "changes": None}
    state["identity_audit"] = {"items": [event("i-1", "2099-01-02T00:00:00+00:00", "Identity")], "total": 1, "facets": {"modules": ["Identity"], "actions": ["identity.saved"], "actors": [{"id": "u-9", "name": "Asha HR"}]}}
    state["hrms_audit"] = {"items": [event("h-1", "2099-01-03T00:00:00+00:00", "Leave"), event("h-2", "2000-01-01T00:00:00+00:00", "Leave")], "total": 2,
                           "facets": {"modules": ["Leave"], "actions": ["leave.saved"], "actors": [{"id": "u-9", "name": "Asha HR"}]}}
    page = (await client.get(f"{API}/admin/audit-events", params={"pageSize": 10}, headers=auth())).json()
    assert page["meta"]["totalItems"] == 4 and [e["id"] for e in page["items"]][:2] == ["h-1", "i-1"], "newest first across services"
    assert set(page["facets"]["modules"]) == {"Identity", "Leave", "Platform"} and {a["name"] for a in page["facets"]["actors"]} == {"Asha HR", "Test Admin"}
    forwarded = [c for c in calls if c.url.path.endswith("audit-events")]
    assert all(c.headers["authorization"] == auth()["Authorization"] or c.headers["authorization"].startswith("Bearer ") for c in forwarded), "the caller's session is forwarded"
    state["hrms_audit"] = None  # the caller may not read HRMS's log: left out, not an error
    assert (await client.get(f"{API}/admin/audit-events", headers=auth())).json()["meta"]["totalItems"] == 2

    state["identity_counts"] = {"users": {"total": 3, "active": 2, "invited": 0, "inactive": 1, "locked": 0}, "roles": {"total": 2, "administrators": 1}}
    state["hrms_counts"] = {"departments": 15, "designations": 9, "workflows": {"published": 1, "draft": 0, "processesWithoutWorkflow": ["overtime", "payroll"]}}
    overview = (await client.get(f"{API}/admin/overview", headers=auth())).json()
    assert overview["users"]["total"] == 3 and overview["departments"] == 15 and overview["workflows"]["processesWithoutWorkflow"] == ["overtime", "payroll"] and overview["recentAudit"]
    assert (await client.get(f"{API}/admin/overview", headers=auth(permissions=["hr.self:view"]))).status_code == 403
