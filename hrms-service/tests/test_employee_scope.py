"""Module 2: organizational scope (decision Q12) and the employee picker (B4 lookup, decision Q6)."""

from sqlalchemy import select

from app.models.audit_log_model import AuditLog
from tests.employee_fixtures import HEAD, HR_ALL, HR_QA, MANAGER, SELF, create, details, hr, org, payload  # noqa: F401
from tests.conftest import auth

BASE = "/api/v1/hr/employees"
VIEW = ["hr.employees:view"]


async def codes(client, headers) -> list[str]:
    return [i["employeeCode"] for i in (await client.get(BASE, params={"pageSize": 100}, headers=headers)).json()["items"]]


async def staff(client, org):
    """QA: EVR-1 (head of QA) ← EVR-2 ← EVR-3; HR department: EVR-4."""
    e1 = await create(client, org, "EVR-1")
    e2 = await create(client, org, "EVR-2", employment__reportingManagerId=e1["id"])
    e3 = await create(client, org, "EVR-3", employment__reportingManagerId=e2["id"])
    e4 = await create(client, org, "EVR-4", dept="HR")
    return e1, e2, e3, e4


async def test_no_scope_assignment_means_no_employee_records(client, org):
    e1, *_ = await staff(client, org)
    for headers in (hr(VIEW, roles=[]), hr(VIEW, roles=["unassigned-role"]), auth(["*"])):
        assert await codes(client, headers) == []
        assert (await client.get(f"{BASE}/{e1['id']}", headers=headers)).status_code == 404, "out of scope looks like missing (A4)"


async def test_each_scope_type(client, org):
    e1, e2, e3, e4 = await staff(client, org)
    assert await codes(client, hr(VIEW, roles=[HR_ALL])) == ["EVR-1", "EVR-2", "EVR-3", "EVR-4"]
    assert await codes(client, hr(VIEW, roles=[HR_QA])) == ["EVR-1", "EVR-2", "EVR-3"]
    assert await codes(client, hr(VIEW, roles=[MANAGER], employee_id=e1["id"])) == ["EVR-2", "EVR-3"]
    assert await codes(client, hr(VIEW, roles=[MANAGER], employee_id=e2["id"])) == ["EVR-3"]
    assert await codes(client, hr(VIEW, roles=[SELF], employee_id=e3["id"])) == ["EVR-3"]
    assert await codes(client, hr(VIEW, roles=[SELF, MANAGER], employee_id=e2["id"])) == ["EVR-2", "EVR-3"], "roles combine"
    assert await codes(client, hr(VIEW, roles=[HEAD], employee_id=e1["id"])) == []
    dept = (await client.get("/api/v1/admin/departments", headers=auth(["admin:organization.view"]))).json()
    qa = next(d for d in dept if d["code"] == "QA")
    r = await client.put(f"/api/v1/admin/departments/{qa['id']}", json={"code": "QA", "name": qa["name"], "headEmployeeId": e1["id"], "parentId": None, "active": True, "version": qa["version"]}, headers=auth(["admin:organization.manage"]))
    assert r.status_code == 200 and r.json()["head"] == {"id": e1["id"], "fullName": "Ravi Iyer"}
    assert await codes(client, hr(VIEW, roles=[HEAD], employee_id=e1["id"])) == ["EVR-1", "EVR-2", "EVR-3"]
    # Scope also guards the record, its history and writes.
    qa_hr = hr(roles=[HR_QA])
    assert (await client.get(f"{BASE}/{e4['id']}", headers=qa_hr)).status_code == 404
    assert (await client.get(f"{BASE}/{e4['id']}/history", headers=qa_hr)).status_code == 404
    assert (await client.patch(f"{BASE}/{e4['id']}", json=payload(org, "EVR-4", dept="HR"), headers=qa_hr)).status_code == 404


async def test_writes_cannot_leave_the_callers_scope(client, org):
    qa_hr = hr(roles=[HR_QA])
    r = await client.post(BASE, json=payload(org, "EVR-9", dept="HR"), headers=qa_hr)
    assert r.status_code == 422 and details(r) == {"employment.departmentId": "You can only add or move employees within your organizational scope."}
    e = await create(client, org, "EVR-8", headers=qa_hr)
    r = await client.patch(f"{BASE}/{e['id']}", json=payload(org, "EVR-8", dept="HR", version=1), headers=qa_hr)
    assert r.status_code == 422 and "employment.departmentId" in details(r)


async def test_scope_assignments_are_managed_by_hr_setup(client, org):
    manage = auth(["hr.settings:manage"])
    assert (await client.get("/api/v1/hr/setup/employee-access-scopes", headers=auth(["hr.employees:view"]))).status_code == 403
    r = await client.post("/api/v1/hr/setup/employee-access-scopes", json={"roleCode": "plant-hr", "scopeType": "departments", "departmentIds": []}, headers=manage)
    assert details(r) == {"departmentIds": "Select at least one department."}
    r = await client.post("/api/v1/hr/setup/employee-access-scopes", json={"roleCode": "plant-hr", "scopeType": "departments", "departmentIds": [org.dept["PRD"], org.dept["WND"]]}, headers=manage)
    assert r.status_code == 201 and [d["name"] for d in r.json()["departments"]] == ["Production", "Winding"]
    r = await client.post("/api/v1/hr/setup/employee-access-scopes", json={"roleCode": "plant-hr", "scopeType": "departments", "departmentIds": [org.dept["QA"]]}, headers=manage)
    assert details(r) == {"scopeType": "This role already has this scope type."}
    r = await client.post("/api/v1/hr/setup/employee-access-scopes", json={"roleCode": "x", "scopeType": "all", "departmentIds": [org.dept["QA"]]}, headers=manage)
    assert "departmentIds" in details(r)
    await create(client, org, "EVR-5", dept="PRD")
    assert await codes(client, hr(VIEW, roles=["plant-hr"])) == ["EVR-5"]
    scope = next(s for s in (await client.get("/api/v1/hr/setup/employee-access-scopes", headers=manage)).json() if s["roleCode"] == "plant-hr")
    r = await client.put(f"/api/v1/hr/setup/employee-access-scopes/{scope['id']}", json={"roleCode": "plant-hr", "scopeType": "departments", "departmentIds": [org.dept["PRD"]], "active": False, "version": 1}, headers=manage)
    assert r.status_code == 200 and r.json()["version"] == 2
    assert await codes(client, hr(VIEW, roles=["plant-hr"])) == [], "inactive assignments grant nothing"


# --- Picker (lookup) ---------------------------------------------------------------------------------


async def test_lookup_follows_the_contract(client, org):
    e1, e2, e3, e4 = await staff(client, org)
    picker = hr(["hr.leave:apply-on-behalf"])
    r = await client.get(f"{BASE}/lookup", headers=picker)
    assert r.status_code == 200
    assert r.json()[0] == {"id": e1["id"], "employeeCode": "EVR-1", "fullName": "Ravi Iyer", "department": "Quality Assurance"}, "only the 4 contract fields"
    assert len(r.json()) == 4, "empty q returns the first `limit` (decision Q6)"
    assert len((await client.get(f"{BASE}/lookup", params={"limit": 2}, headers=picker)).json()) == 2
    assert (await client.get(f"{BASE}/lookup", params={"limit": 21}, headers=picker)).status_code == 422
    r = await client.get(f"{BASE}/lookup", params={"q": "evr-3"}, headers=picker)
    assert [i["employeeCode"] for i in r.json()] == ["EVR-3"]
    r = await client.get(f"{BASE}/lookup", params={"excludeId": e1["id"]}, headers=picker)
    assert e1["id"] not in [i["id"] for i in r.json()]


async def test_lookup_respects_permissions_scope_and_ended_employment(client, db, org):
    e1, e2, e3, e4 = await staff(client, org)
    assert (await client.get(f"{BASE}/lookup", headers=hr(["hr.self:view"], user_id="44444444-4444-4444-4444-444444444444"))).status_code == 403
    assert await db.scalar(select(AuditLog).where(AuditLog.result == "denied", AuditLog.actor_user_id == "44444444-4444-4444-4444-444444444444")) is not None
    r = await client.get(f"{BASE}/lookup", headers=hr(["hr.shifts:assign"], roles=[HR_QA]))
    assert [i["employeeCode"] for i in r.json()] == ["EVR-1", "EVR-2", "EVR-3"], "picker results stay inside the caller's scope"
    assert (await client.get(f"{BASE}/lookup", headers=hr(["hr.shifts:assign"], roles=[]))).json() == []
    exit_body = {"toStatus": "exited", "effectiveDate": "2026-11-01", "version": e4["version"]}
    assert (await client.post(f"{BASE}/{e4['id']}/status-changes", json=exit_body, headers=hr())).status_code == 200
    r = await client.get(f"{BASE}/lookup", headers=hr(["hr.documents:view"]))
    assert "EVR-4" not in [i["employeeCode"] for i in r.json()], "statuses marked employmentEnded are excluded (Q5)"


async def test_self_service_department_list_is_own_department(client, org):
    e = await create(client, org, "EVR-1")
    r = await client.get("/api/v1/hr/departments", headers=auth(["hr.self:view"], employee_id=e["id"]))
    assert [d["code"] for d in r.json()] == ["QA"]
    assert (await client.get("/api/v1/hr/departments", headers=auth(["hr.self:view"]))).json() == []
