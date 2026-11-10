"""Module 2: employee status changes (B4 status-changes, decisions Q1, Q7, Q8)."""

from tests.employee_fixtures import create, details, hr, org, payload  # noqa: F401
from tests.conftest import auth

BASE = "/api/v1/hr/employees"


async def change(client, e, headers=None, **body):
    data = {"toStatus": "on_notice", "effectiveDate": "2026-11-01", "reason": None, "version": e["version"], **body}
    return await client.post(f"{BASE}/{e['id']}/status-changes", json=data, headers=headers or hr())


async def test_status_change_records_history_with_labels(client, org):
    e = await create(client, org)
    r = await change(client, e, reason="Resigned; serving notice")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["employment"]["statusCode"] == "on_notice" and out["version"] == 2 and out["display"]["status"]["label"] == "On notice"
    h = (await client.get(f"{BASE}/{e['id']}/history", headers=hr())).json()["items"][0]
    assert {k: h[k] for k in ("action", "fromStatus", "toStatus", "effectiveDate", "comment")} == {
        "action": "status_changed", "fromStatus": "Active", "toStatus": "On notice", "effectiveDate": "2026-11-01", "comment": "Resigned; serving notice",
    }


async def test_status_change_rules(client, org):
    e = await create(client, org)
    r = await change(client, e, toStatus="on_probation")
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TRANSITION" and details(r) == {"toStatus": "This change is not allowed from the current status."}
    r = await change(client, e, toStatus="active")
    assert details(r) == {"toStatus": "The employee already has this status."}
    r = await change(client, e, effectiveDate="2019-12-31")
    assert details(r) == {"effectiveDate": "The effective date cannot be before the joining date."}
    r = await change(client, e, effectiveDate="soon", reason="x" * 501)
    assert details(r) == {"effectiveDate": "Enter the effective date.", "reason": "Keep the reason under 500 characters."}
    r = await change(client, e, version=99)
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_VERSION"
    assert (await change(client, e, headers=hr(["hr.employees:edit"]))).status_code == 403


async def test_reason_required_is_an_hr_setting_off_by_default(client, org):
    e = await create(client, org)
    assert (await change(client, e, toStatus="suspended")).status_code == 200  # no reason needed by default (Q8 pending)
    statuses = (await client.get("/api/v1/hr/setup/employee-statuses", headers=auth(["hr.settings:manage"]))).json()
    exited = next(s for s in statuses if s["code"] == "exited")
    assert exited["employmentEnded"] is True and exited["reasonRequired"] is False
    body = {k: exited[k] for k in ("code", "label", "tone", "active", "allowedOnCreate", "transitions", "sortOrder", "employmentEnded", "version")}
    r = await client.put(f"/api/v1/hr/setup/employee-statuses/{exited['id']}", json={**body, "reasonRequired": True}, headers=auth(["hr.settings:manage"]))
    assert r.status_code == 200 and r.json()["reasonRequired"] is True
    e = (await client.get(f"{BASE}/{e['id']}", headers=hr())).json()
    r = await change(client, e, toStatus="exited")
    assert details(r) == {"reason": "Enter a reason for this change."}
    assert (await change(client, e, toStatus="exited", reason="Left the company")).status_code == 200


async def test_patch_status_change_needs_both_permissions_and_a_valid_transition(client, db, org):
    e = await create(client, org)
    body = payload(org, employment__statusCode="on_notice", version=1)
    r = await client.patch(f"{BASE}/{e['id']}", json=body, headers=hr(["hr.employees:edit", "hr.employees:view-contact", "hr.employees:view-sensitive"]))
    assert r.status_code == 403, "decision Q1: edit alone cannot change status"
    r = await client.patch(f"{BASE}/{e['id']}", json=payload(org, employment__statusCode="on_probation", version=1), headers=hr())
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_TRANSITION"
    assert details(r) == {"employment.statusCode": "An employee cannot move from Active to On probation."}
    r = await client.patch(f"{BASE}/{e['id']}", json=body, headers=hr())
    assert r.status_code == 200 and r.json()["employment"]["statusCode"] == "on_notice"
    actions = [h["action"] for h in (await client.get(f"{BASE}/{e['id']}/history", headers=hr())).json()["items"]]
    assert actions[0] == "status_changed" and "created" in actions


async def test_probation_is_not_confirmed_automatically(client, org):
    e = await create(client, org, status="on_probation", employment__probation={"applicable": True, "endDate": "2020-07-15", "confirmationDate": None})
    out = (await change(client, e, toStatus="active", effectiveDate="2020-07-15")).json()
    assert out["employment"]["probation"]["confirmationDate"] is None, "Q9 pending: HR enters the confirmation date"
