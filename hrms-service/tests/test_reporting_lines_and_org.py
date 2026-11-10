"""Module 2: reporting lines (G4) and the Module 1 rules that needed employee records."""

import pytest
from sqlalchemy import select

from app.core import crypto
from app.core.config import Settings
from app.models.employee_model import EmployeePayrollValue
from app.scripts.rotate_payroll_encryption import rotate_all
from tests.conftest import auth
from tests.employee_fixtures import HR_QA, create, details, hr, org  # noqa: F401

LINES = "/api/v1/admin/reporting-lines"
ORG_VIEW = ["admin:organization.view", "hr.employees:view"]


def admin(perms, roles=None, **kw):
    return hr(perms, roles=roles, **kw)


async def test_reporting_lines_need_both_permissions_and_follow_scope(client, org):
    boss = await create(client, org, "EVR-1")
    await create(client, org, "EVR-2", employment__reportingManagerId=boss["id"])
    await create(client, org, "EVR-3", dept="HR")
    assert (await client.get(LINES, headers=admin(["admin:organization.view"]))).status_code == 403
    assert (await client.get(LINES, headers=admin(["hr.employees:view"]))).status_code == 403
    r = (await client.get(LINES, params={"pageSize": 10}, headers=admin(ORG_VIEW))).json()
    rows = {i["employee"]["employeeCode"]: i for i in r["items"]}
    assert set(rows) == {"EVR-1", "EVR-2", "EVR-3"}
    assert rows["EVR-1"]["directReports"] == 1 and rows["EVR-1"]["manager"] is None and rows["EVR-1"]["effectiveFrom"] is None
    assert rows["EVR-2"]["manager"] == {"id": boss["id"], "employeeCode": "EVR-1", "fullName": "Ravi Iyer"} and rows["EVR-2"]["effectiveFrom"] == "2020-01-15"
    assert set(rows["EVR-2"]) == {"employee", "department", "designation", "manager", "effectiveFrom", "directReports"}
    scoped = (await client.get(LINES, headers=admin(ORG_VIEW, roles=[HR_QA]))).json()["items"]
    assert {i["employee"]["employeeCode"] for i in scoped} == {"EVR-1", "EVR-2"}
    by_manager = (await client.get(LINES, params={"managerId": boss["id"]}, headers=admin(ORG_VIEW))).json()["items"]
    assert [i["employee"]["employeeCode"] for i in by_manager] == ["EVR-2"]


async def test_change_manager(client, org):
    a = await create(client, org, "EVR-1")
    b = await create(client, org, "EVR-2", employment__reportingManagerId=a["id"])
    manage = admin(["admin:organization.manage"])
    r = await client.post(f"{LINES}/{a['id']}", json={"managerId": b["id"], "effectiveFrom": "2026-11-01", "reason": "Restructure"}, headers=manage)
    assert r.status_code == 422 and r.json()["error"]["message"] == "The manager cannot be one of this employee's reports."
    r = await client.post(f"{LINES}/{b['id']}", json={"managerId": a["id"], "effectiveFrom": "x", "reason": "no"}, headers=manage)
    assert details(r) == {"managerId": "This employee already reports to this manager.", "effectiveFrom": "Enter the effective date.", "reason": "Enter the reason."}
    r = await client.post(f"{LINES}/{b['id']}", json={"managerId": None, "effectiveFrom": "2026-11-01", "reason": "Reports to the plant head directly"}, headers=manage)
    assert r.status_code == 200 and r.json()["manager"] is None
    h = (await client.get(f"/api/v1/hr/employees/{b['id']}/history", headers=hr())).json()["items"][0]
    assert h["summary"] == "Reporting manager changed" and h["effectiveDate"] == "2026-11-01" and h["comment"] == "Reports to the plant head directly"
    record = (await client.get(f"/api/v1/hr/employees/{b['id']}", headers=hr())).json()
    assert record["employment"]["reportingManagerId"] is None and record["version"] == 2
    assert (await client.post(f"{LINES}/{b['id']}", json={"managerId": a["id"], "effectiveFrom": "2026-11-01", "reason": "Back"}, headers=admin(["admin:organization.view"]))).status_code == 403


async def test_department_head_counts_and_deactivation(client, org):
    head = await create(client, org, "EVR-1")
    await create(client, org, "EVR-2")
    manage = auth(["admin:organization.manage"])
    deps = {d["code"]: d for d in (await client.get("/api/v1/admin/departments", headers=manage)).json()}
    qa = deps["QA"]
    assert qa["employeeCount"] == 2 and deps["HR"]["employeeCount"] == 0
    body = {"code": "QA", "name": qa["name"], "headEmployeeId": "00000000-0000-0000-0000-00000000abcd", "parentId": None, "active": True, "version": qa["version"]}
    r = await client.put(f"/api/v1/admin/departments/{qa['id']}", json=body, headers=manage)
    assert details(r) == {"headEmployeeId": "Select an existing employee."}
    r = await client.put(f"/api/v1/admin/departments/{qa['id']}", json={**body, "headEmployeeId": None, "active": False}, headers=manage)
    assert details(r) == {"active": "2 active employee(s) are in this department. Move them before deactivating it."}
    exit_body = {"toStatus": "exited", "effectiveDate": "2026-11-01", "version": head["version"]}
    assert (await client.post(f"/api/v1/hr/employees/{head['id']}/status-changes", json=exit_body, headers=hr())).status_code == 200
    r = await client.put(f"/api/v1/admin/departments/{qa['id']}", json={**body, "headEmployeeId": head["id"]}, headers=manage)
    assert details(r) == {"headEmployeeId": "The department head must be an active employee."}
    assert (await client.get("/api/v1/admin/departments", headers=manage)).json()[[d["code"] for d in (await client.get("/api/v1/admin/departments", headers=manage)).json()].index("QA")]["employeeCount"] == 1

    designations = {d["code"]: d for d in (await client.get("/api/v1/admin/designations", headers=manage)).json()}
    eng = designations["ENG"]
    assert eng["employeeCount"] == 1
    r = await client.put(f"/api/v1/admin/designations/{eng['id']}", json={"code": "ENG", "name": eng["name"], "description": "", "departmentIds": [], "active": False, "version": eng["version"]}, headers=manage)
    assert details(r) == {"active": "1 active employee(s) have this designation. Change it before deactivating."}
    shifts = {s["code"]: s for s in (await client.get("/api/v1/hr/shifts", headers=auth(["hr.shifts:view"]))).json()}
    assert shifts["GEN"]["assignedEmployees"] == 1 and shifts["A"]["assignedEmployees"] == 0


# --- Encryption at rest ------------------------------------------------------------------------------


async def test_key_rotation_reencrypts_with_the_new_key(client, db, org, monkeypatch):
    await create(client, org)
    old_keys = crypto.get_settings().payroll_encryption_keys
    new_key = crypto.Fernet.generate_key().decode()
    monkeypatch.setattr(crypto.get_settings(), "payroll_encryption_keys", [new_key, *old_keys])
    crypto.reset_cache()
    try:
        assert await rotate_all(db) == 1
        row = await db.scalar(select(EmployeePayrollValue).where(EmployeePayrollValue.field_key == "bankAccountNumber"))
        assert crypto.Fernet(new_key.encode()).decrypt(row.value.encode()).decode() == "000012345678"
    finally:
        monkeypatch.undo()
        crypto.reset_cache()


async def test_switching_a_field_to_sensitive_encrypts_existing_values(client, db, org):
    await create(client, org)
    manage = auth(["hr.settings:manage"])
    field = next(f for f in (await client.get("/api/v1/hr/setup/payroll-fields", headers=manage)).json() if f["key"] == "bankIfsc")
    body = {k: field[k] for k in ("key", "label", "type", "required", "maxLength", "pattern", "patternMessage", "options", "hint", "sortOrder", "active", "version")}
    assert (await client.put(f"/api/v1/hr/setup/payroll-fields/{field['id']}", json={**body, "sensitive": True}, headers=manage)).status_code == 200
    row = await db.scalar(select(EmployeePayrollValue).where(EmployeePayrollValue.field_key == "bankIfsc"))
    await db.refresh(row)
    assert row.encrypted and crypto.decrypt(row.value) == "ABCD0123456"
    e = (await client.get("/api/v1/hr/employees", headers=hr())).json()["items"][0]
    values = (await client.get(f"/api/v1/hr/employees/{e['id']}", headers=hr())).json()["payroll"]["values"]
    assert values["bankIfsc"] == "••••3456"


def test_production_requires_an_encryption_key():
    base = dict(environment="production", auth_dev_mode=False, auth_jwt_public_key="k", allowed_origins=["https://erp.example.com"], docs_enabled=False, database_url="postgresql+asyncpg://x/y",
                document_encryption_keys=["k"], malware_scanner="clamav")
    with pytest.raises(ValueError, match="PAYROLL_ENCRYPTION_KEYS"):
        Settings(**base, payroll_encryption_keys=[])
    with pytest.raises(ValueError, match="COMPANY_TIME_ZONE"):
        Settings(**base, payroll_encryption_keys=["k"], company_time_zone="Mars/Base")
    assert Settings(**base, payroll_encryption_keys=["k"]).company_time_zone == "UTC"
