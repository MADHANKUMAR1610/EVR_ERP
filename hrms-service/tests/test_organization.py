"""Module 1: departments, designations and shifts (Administration → Organization, HR → Shifts)."""

from sqlalchemy import select

from app.models.audit_log_model import AuditLog
from app.models.department_model import Department
from tests.conftest import auth

ORG_MANAGE = auth(["admin:organization.manage"], name="Asha HR")
ORG_VIEW = auth(["admin:organization.view"])
SHIFT_MANAGE = auth(["hr.shifts:manage"], name="Asha HR")


async def make_department(client, code="PRD", name="Production", **extra):
    r = await client.post("/api/v1/admin/departments", json={"code": code, "name": name, "headEmployeeId": None, "parentId": None, "active": True, **extra}, headers=ORG_MANAGE)
    assert r.status_code == 201, r.text
    return r.json()


def details(r):
    return {d["field"]: d["message"] for d in r.json()["error"]["details"]}


# --- Departments ------------------------------------------------------------------------------------


async def test_department_create_matches_frontend_shape_and_fills_audit_fields(client, db):
    body = await make_department(client, code=" prd ", name=" Production ")
    assert body == {"id": body["id"], "code": "PRD", "name": "Production", "head": None, "parent": None, "active": True, "employeeCount": 0, "version": 1}
    row = await db.scalar(select(Department).where(Department.code == "PRD"))
    assert row.created_by_name == "Asha HR" and row.updated_by is not None and row.created_at is not None
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "department.created"))
    assert entry.entity_id == body["id"] and entry.actor_name == "Asha HR"


async def test_department_list_requires_permission_and_returns_array(client):
    await make_department(client)
    assert (await client.get("/api/v1/admin/departments", headers=auth(["hr.employees:view"]))).status_code == 403
    r = await client.get("/api/v1/admin/departments", headers=ORG_VIEW)
    assert r.status_code == 200 and [d["code"] for d in r.json()] == ["PRD"]
    assert (await client.post("/api/v1/admin/departments", json={}, headers=ORG_VIEW)).status_code == 403


async def test_department_validation_messages(client):
    await make_department(client)
    r = await client.post("/api/v1/admin/departments", json={"code": "prd", "name": "X", "headEmployeeId": None, "parentId": "nope", "active": True}, headers=ORG_MANAGE)
    assert r.status_code == 422
    assert details(r) == {"code": "Another department uses this code.", "name": "Enter a name.", "parentId": "Select an existing department."}
    r = await client.post("/api/v1/admin/departments", json={"code": "TOO_LONG_CODE", "name": "Valid", "headEmployeeId": None, "parentId": None, "active": True}, headers=ORG_MANAGE)
    assert details(r) == {"code": "Use 1–10 capital letters, digits or hyphens."}


async def test_department_parent_and_cycle(client):
    top = await make_department(client, code="PRD", name="Production")
    child = await make_department(client, code="WND", name="Winding", parentId=top["id"])
    assert child["parent"] == {"id": top["id"], "name": "Production"}
    r = await client.put(f"/api/v1/admin/departments/{top['id']}", json={"code": "PRD", "name": "Production", "headEmployeeId": None, "parentId": child["id"], "active": True}, headers=ORG_MANAGE)
    assert r.status_code == 422 and details(r) == {"parentId": "A department cannot sit under itself or one of its sub-departments."}
    r = await client.put(f"/api/v1/admin/departments/{top['id']}", json={"code": "PRD", "name": "Production", "headEmployeeId": None, "parentId": top["id"], "active": True}, headers=ORG_MANAGE)
    assert r.status_code == 422


async def test_department_update_versioning_and_not_found(client):
    dep = await make_department(client)
    payload = {"code": "PRD", "name": "Production Floor", "headEmployeeId": None, "parentId": None, "active": True, "version": 1}
    r = await client.put(f"/api/v1/admin/departments/{dep['id']}", json=payload, headers=ORG_MANAGE)
    assert r.status_code == 200 and r.json()["version"] == 2 and r.json()["name"] == "Production Floor"
    r = await client.put(f"/api/v1/admin/departments/{dep['id']}", json=payload, headers=ORG_MANAGE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_VERSION"
    assert (await client.put("/api/v1/admin/departments/not-a-uuid", json=payload, headers=ORG_MANAGE)).status_code == 404
    assert (await client.put("/api/v1/admin/departments/00000000-0000-0000-0000-00000000abcd", json=payload, headers=ORG_MANAGE)).status_code == 404


async def test_department_head_must_be_an_existing_employee(client):
    r = await client.post(
        "/api/v1/admin/departments", json={"code": "QA", "name": "Quality", "headEmployeeId": "00000000-0000-0000-0000-000000000099", "parentId": None, "active": True}, headers=ORG_MANAGE
    )
    assert r.status_code == 422 and "headEmployeeId" in details(r)


async def test_hr_reference_list_of_departments(client):
    await make_department(client)
    await make_department(client, code="OLD", name="Old unit", active=False)
    r = await client.get("/api/v1/hr/departments", headers=auth(["hr.leave:view"]))
    assert r.status_code == 200
    assert [(d["code"], d["active"]) for d in r.json()] == [("OLD", False), ("PRD", True)]
    assert set(r.json()[0]) == {"id", "code", "name", "active"}
    assert (await client.get("/api/v1/hr/departments")).status_code == 401


# --- Designations -----------------------------------------------------------------------------------


async def test_designation_create_update_and_department_links(client):
    prd = await make_department(client)
    wnd = await make_department(client, code="WND", name="Winding")
    payload = {"code": "opr", "name": "Operator", "description": "Machine operator", "departmentIds": [prd["id"]], "active": True}
    r = await client.post("/api/v1/admin/designations", json=payload, headers=ORG_MANAGE)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["code"] == "OPR" and d["departments"] == [{"id": prd["id"], "name": "Production"}] and d["employeeCount"] == 0 and d["version"] == 1

    r = await client.put(f"/api/v1/admin/designations/{d['id']}", json={**payload, "departmentIds": [wnd["id"]], "version": 1}, headers=ORG_MANAGE)
    assert r.status_code == 200 and r.json()["departments"] == [{"id": wnd["id"], "name": "Winding"}]
    assert r.json()["version"] == 2, "changing only the links still moves the version"

    r = await client.post("/api/v1/admin/designations", json={**payload, "departmentIds": ["00000000-0000-0000-0000-00000000abcd"]}, headers=ORG_MANAGE)
    assert r.status_code == 422 and details(r) == {"code": "Another designation uses this code.", "departmentIds": "Select existing departments."}

    r = await client.get("/api/v1/hr/designations", headers=auth(["hr.employees:view"]))
    assert [x["code"] for x in r.json()] == ["OPR"]


# --- Shifts -----------------------------------------------------------------------------------------

SHIFT = {"code": "GEN", "name": "General shift", "start": "09:00", "end": "17:30", "overnight": False, "breakMinutes": 30, "graceMinutes": 10, "workingDays": [1, 2, 3, 4, 5, 6], "departmentIds": [], "active": True}


async def test_shift_create_shape_and_options(client):
    prd = await make_department(client)
    r = await client.post("/api/v1/hr/shifts", json={**SHIFT, "departmentIds": [prd["id"]]}, headers=SHIFT_MANAGE)
    assert r.status_code == 201, r.text
    s = r.json()
    assert {k: s[k] for k in ("code", "start", "end", "overnight", "workingDays", "assignedEmployees", "version", "updatedBy")} == {
        "code": "GEN", "start": "09:00", "end": "17:30", "overnight": False, "workingDays": [1, 2, 3, 4, 5, 6], "assignedEmployees": 0, "version": 1, "updatedBy": "Asha HR",
    }
    assert s["departments"] == [{"id": prd["id"], "name": "Production"}] and s["updatedAt"].endswith("Z")

    night = {**SHIFT, "code": "C", "name": "Night shift", "start": "22:00", "end": "06:00", "overnight": True}
    assert (await client.post("/api/v1/hr/shifts", json=night, headers=SHIFT_MANAGE)).status_code == 201
    await client.post("/api/v1/hr/shifts", json={**SHIFT, "code": "OLD", "name": "Retired shift", "active": False}, headers=SHIFT_MANAGE)

    r = await client.get("/api/v1/hr/shifts/options", headers=auth(["hr.employees:create"]))
    assert r.json() == [
        {"id": s["id"], "name": "General shift", "description": "09:00–17:30"},
        {"id": r.json()[1]["id"], "name": "Night shift", "description": "22:00–06:00, overnight"},
    ]
    assert len((await client.get("/api/v1/hr/shifts", headers=auth(["hr.shifts:view"]))).json()) == 3


async def test_shift_rules_mirror_the_frontend_form(client):
    async def errors(**changes):
        r = await client.post("/api/v1/hr/shifts", json={**SHIFT, **changes}, headers=SHIFT_MANAGE)
        assert r.status_code == 422, r.text
        return details(r)

    assert await errors(end="09:00") == {"end": "End time must differ from start time."}
    assert await errors(start="22:00", end="06:00", overnight=False) == {"overnight": "This shift ends after midnight. Confirm it is an overnight shift, or correct the times."}
    assert await errors(overnight=True) == {"overnight": "An overnight shift must end earlier in the day than it starts (e.g. 22:00–06:00)."}
    assert await errors(start="06:00", end="23:00") == {"end": "A shift cannot be longer than 16 hours."}
    assert await errors(start="09:00", end="09:30", breakMinutes=30) == {"breakMinutes": "The break must be shorter than the shift."}
    assert await errors(workingDays=[]) == {"workingDays": "Select at least one working day."}
    assert await errors(workingDays=[0, 8]) == {"workingDays": "Use weekdays 1 (Monday) to 7 (Sunday)."}
    assert await errors(start="9am") == {"start": "Enter a start time."}
    assert await errors(breakMinutes=-1, graceMinutes=121) == {"breakMinutes": "Cannot be negative.", "graceMinutes": "At most 120 minutes."}
    assert await errors(code="G 1") == {"code": "Use letters, digits and hyphens only."}

    assert (await client.post("/api/v1/hr/shifts", json=SHIFT, headers=SHIFT_MANAGE)).status_code == 201
    assert await errors(code="gen") == {"code": "Another shift already uses this code."}


async def test_shift_update_permissions_and_versioning(client):
    s = (await client.post("/api/v1/hr/shifts", json=SHIFT, headers=SHIFT_MANAGE)).json()
    assert (await client.put(f"/api/v1/hr/shifts/{s['id']}", json=SHIFT, headers=auth(["hr.shifts:view"]))).status_code == 403
    assert (await client.get("/api/v1/hr/shifts", headers=auth(["hr.employees:view"]))).status_code == 403
    r = await client.put(f"/api/v1/hr/shifts/{s['id']}", json={**SHIFT, "graceMinutes": 15, "version": 1}, headers=SHIFT_MANAGE)
    assert r.status_code == 200 and r.json()["graceMinutes"] == 15 and r.json()["version"] == 2
    r = await client.put(f"/api/v1/hr/shifts/{s['id']}", json={**SHIFT, "version": 1}, headers=SHIFT_MANAGE)
    assert r.status_code == 409
    # Same code on the same shift is not a duplicate.
    assert (await client.put(f"/api/v1/hr/shifts/{s['id']}", json={**SHIFT, "code": "gen"}, headers=SHIFT_MANAGE)).status_code == 200
