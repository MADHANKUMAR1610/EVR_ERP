"""Module 1: HR reference lists (frontend referenceData.http.ts) and their /hr/setup maintenance API."""

import pytest

from tests.conftest import auth

SETUP = auth(["hr.settings:manage"], name="Asha HR")
SETUP_VIEW = auth(["hr.settings:view"])
READER = auth(["hr.employees:create", "hr.employees:change-status", "hr.documents:view"])  # screens that use the lists


def details(r):
    return {d["field"]: d["message"] for d in r.json()["error"]["details"]}


@pytest.mark.parametrize(
    ("kind", "read_path"),
    [("employment-types", "/hr/employment-types"), ("work-locations", "/hr/work-locations")],
)
async def test_coded_lists_round_trip(client, kind, read_path):
    r = await client.post(f"/api/v1/hr/setup/{kind}", json={"code": "PERM", "name": "Permanent"}, headers=SETUP)
    assert r.status_code == 201, r.text
    item = r.json()
    assert item == {"id": item["id"], "code": "PERM", "name": "Permanent", "description": None, "active": True, "version": 1}
    r = await client.put(f"/api/v1/hr/setup/{kind}/{item['id']}", json={"code": "PERM", "name": "Permanent staff", "active": False, "version": 1}, headers=SETUP)
    assert r.status_code == 200 and r.json()["version"] == 2
    r = await client.get(f"/api/v1{read_path}", headers=READER)
    assert r.json() == [{"id": item["id"], "code": "PERM", "name": "Permanent staff", "active": False}]


async def test_policy_options_show_only_active_items_with_description(client):
    await client.post("/api/v1/hr/setup/attendance-policies", json={"code": "AP-STAFF", "name": "Staff attendance policy", "description": "Office staff"}, headers=SETUP)
    await client.post("/api/v1/hr/setup/attendance-policies", json={"code": "AP-OLD", "name": "Old policy", "active": False}, headers=SETUP)
    await client.post("/api/v1/hr/setup/overtime-policies", json={"code": "OT-NONE", "name": "Not eligible"}, headers=SETUP)
    r = await client.get("/api/v1/hr/attendance-policies/options", headers=READER)
    assert [(o["name"], o["description"]) for o in r.json()] == [("Staff attendance policy", "Office staff")]
    r = await client.get("/api/v1/hr/overtime-policies/options", headers=READER)
    assert [o["name"] for o in r.json()] == ["Not eligible"]


async def test_setup_permissions_and_validation(client):
    assert (await client.post("/api/v1/hr/setup/employment-types", json={"code": "X", "name": "Xx"}, headers=SETUP_VIEW)).status_code == 403
    assert (await client.get("/api/v1/hr/setup/employment-types", headers=SETUP_VIEW)).status_code == 200
    assert (await client.get("/api/v1/hr/setup/employment-types", headers=READER)).status_code == 403
    assert (await client.get("/api/v1/hr/setup/unknown-list", headers=SETUP)).status_code == 404
    await client.post("/api/v1/hr/setup/employment-types", json={"code": "PERM", "name": "Permanent"}, headers=SETUP)
    r = await client.post("/api/v1/hr/setup/employment-types", json={"code": "PERM", "name": "Again", "description": "no"}, headers=SETUP)
    assert r.status_code == 422 and details(r) == {"code": "Another employment type uses this code.", "description": "A employment type has no description."}
    r = await client.post("/api/v1/hr/setup/employment-types", json={"code": "has space", "name": "Spaced"}, headers=SETUP)
    assert details(r) == {"code": "Use 1–20 letters, digits, hyphens or underscores."}


async def test_employee_statuses_and_transitions(client):
    async def add(code, label, tone, transitions, on_create=False, order=0):
        r = await client.post(
            "/api/v1/hr/setup/employee-statuses",
            json={"code": code, "label": label, "tone": tone, "allowedOnCreate": on_create, "transitions": transitions, "sortOrder": order},
            headers=SETUP,
        )
        assert r.status_code == 201, r.text
        return r.json()

    exited = await add("exited", "Exited", "neutral", [], order=5)
    active = await add("active", "Active", "success", ["exited"], on_create=True, order=2)
    r = await client.post("/api/v1/hr/setup/employee-statuses", json={"code": "on_notice", "label": "On notice", "tone": "warning", "transitions": ["active", "retired"]}, headers=SETUP)
    assert r.status_code == 422 and details(r) == {"transitions": "Unknown status: retired."}
    r = await client.post("/api/v1/hr/setup/employee-statuses", json={"code": "suspended", "label": "Suspended", "tone": "danger", "transitions": ["suspended"]}, headers=SETUP)
    assert details(r) == {"transitions": "A status cannot move to itself."}

    r = await client.put(f"/api/v1/hr/setup/employee-statuses/{exited['id']}", json={"code": "gone", "label": "Exited", "tone": "neutral"}, headers=SETUP)
    assert r.status_code == 422 and "code" in details(r)
    r = await client.put(f"/api/v1/hr/setup/employee-statuses/{exited['id']}", json={"code": "exited", "label": "Exited", "tone": "neutral", "transitions": ["active"], "sortOrder": 5, "version": 1}, headers=SETUP)
    assert r.status_code == 200 and r.json()["transitions"] == ["active"] and r.json()["version"] == 2

    r = await client.get("/api/v1/hr/employee-statuses", headers=READER)
    assert r.json() == [
        {"code": "active", "label": "Active", "tone": "success", "active": True, "allowedOnCreate": True, "transitions": ["exited"]},
        {"code": "exited", "label": "Exited", "tone": "neutral", "active": True, "allowedOnCreate": False, "transitions": ["active"]},
    ]
    assert active["sortOrder"] == 2


async def test_document_types(client):
    cat = (await client.post("/api/v1/hr/setup/document-categories", json={"code": "DC-ID", "name": "Identity documents"}, headers=SETUP)).json()
    payload = {"code": "DT-IDP", "name": "Identity proof", "categoryId": cat["id"], "required": True, "allowedExtensions": ["PDF", ".jpg", "pdf"], "maxSizeBytes": 2 * 1024 * 1024}
    r = await client.post("/api/v1/hr/setup/document-types", json=payload, headers=SETUP)
    assert r.status_code == 201, r.text
    assert r.json()["allowedExtensions"] == [".jpg", ".pdf"]
    r = await client.get("/api/v1/hr/document-types", headers=READER)
    assert r.json() == [
        {"id": r.json()[0]["id"], "name": "Identity proof", "category": {"id": cat["id"], "name": "Identity documents"}, "required": True, "expiryRequired": False, "allowedExtensions": [".jpg", ".pdf"], "maxSizeBytes": 2097152, "active": True}
    ]
    r = await client.post("/api/v1/hr/setup/document-types", json={**payload, "categoryId": "x"}, headers=SETUP)
    assert r.status_code == 422 and details(r) == {"code": "Another document type uses this code.", "categoryId": "Select an existing document category."}
    r = await client.post("/api/v1/hr/setup/document-types", json={**payload, "code": "Z", "allowedExtensions": ["p d f"]}, headers=SETUP)
    assert r.status_code == 422 and "allowedExtensions" in str(r.json())


async def test_payroll_fields_need_sensitive_permission(client):
    bank = {"key": "bankAccountNumber", "label": "Bank account number", "type": "text", "sensitive": True, "maxLength": 18, "pattern": "^[0-9]{6,18}$", "patternMessage": "Enter 6–18 digits.", "sortOrder": 3}
    group = {"key": "payrollGroup", "label": "Payroll group", "type": "select", "options": [{"value": "A", "label": "Group A"}], "sortOrder": 1}
    for f in (bank, group):
        r = await client.post("/api/v1/hr/setup/payroll-fields", json=f, headers=SETUP)
        assert r.status_code == 201, r.text
    assert (await client.get("/api/v1/hr/employees/payroll-fields", headers=auth(["hr.employees:view"]))).status_code == 403
    r = await client.get("/api/v1/hr/employees/payroll-fields", headers=auth(["hr.employees:view-sensitive"]))
    assert [f["key"] for f in r.json()] == ["payrollGroup", "bankAccountNumber"]
    assert r.json()[0] == {"key": "payrollGroup", "label": "Payroll group", "type": "select", "required": False, "sensitive": False, "maxLength": None, "pattern": None, "patternMessage": None, "options": [{"value": "A", "label": "Group A"}], "hint": None}

    r = await client.post("/api/v1/hr/setup/payroll-fields", json={**group, "key": "otherGroup", "options": None}, headers=SETUP)
    assert details(r) == {"options": "Add at least one option."}
    r = await client.post("/api/v1/hr/setup/payroll-fields", json={**bank, "key": "x2", "pattern": "([", "options": [{"value": "a", "label": "a"}]}, headers=SETUP)
    assert details(r) == {"options": "Only select fields have options.", "pattern": "Enter a valid pattern."}
    field_id = (await client.get("/api/v1/hr/setup/payroll-fields", headers=SETUP)).json()[0]["id"]
    r = await client.put(f"/api/v1/hr/setup/payroll-fields/{field_id}", json={**group, "key": "renamed"}, headers=SETUP)
    assert r.status_code == 422 and "key" in details(r)


async def test_database_also_refuses_renaming_stable_codes(client, db):
    """Approved rule: status codes and payroll keys are stable. The database enforces it too."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    await client.post("/api/v1/hr/setup/employee-statuses", json={"code": "active", "label": "Active", "tone": "success"}, headers=SETUP)
    await client.post("/api/v1/hr/setup/payroll-fields", json={"key": "bankIfsc", "label": "Bank IFSC", "type": "text"}, headers=SETUP)
    for sql in ("UPDATE employee_status SET code = 'working' WHERE code = 'active'", "UPDATE payroll_field_definition SET key = 'ifsc' WHERE key = 'bankIfsc'"):
        nested = await db.begin_nested()
        with pytest.raises(DBAPIError, match="cannot be changed once created"):
            await db.execute(text(sql))
        await nested.rollback()
    # Other columns stay editable.
    nested = await db.begin_nested()
    await db.execute(text("UPDATE employee_status SET label = 'Working' WHERE code = 'active'"))
    await nested.rollback()
