"""Module 2: employee records (contract B4): shape, field scoping, encryption, validation, history."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core import crypto
from app.models.audit_log_model import AuditLog
from app.models.employee_model import EmployeeContact, EmployeePayrollValue
from tests.employee_fixtures import HR_PERMS, create, details, hr, org, payload  # noqa: F401

BASE = "/api/v1/hr/employees"


async def test_create_returns_contract_shape_with_masked_payroll(client, org):
    e = await create(client, org)
    assert set(e) == {"id", "employeeCode", "version", "personal", "employment", "work", "payroll", "display", "restricted", "audit"}
    assert e["employeeCode"] == "EVR-1001" and e["version"] == 1
    assert e["personal"]["email"] == "evr-1001@example.com" and e["personal"]["address"]["city"] == "Chennai"
    assert e["employment"]["departmentId"] == org.dept["QA"] and e["employment"]["probation"] == {"applicable": False, "endDate": None, "confirmationDate": None}
    assert set(e["display"]) == {"fullName", "department", "designation", "employmentType", "status", "reportingManager", "workLocation", "shift", "attendancePolicy", "overtimePolicy"}
    assert e["display"]["fullName"] == "Ravi Iyer" and e["display"]["department"] == "Quality Assurance" and e["display"]["status"] == {"code": "active", "label": "Active", "tone": "success"}
    assert e["display"]["shift"] == "General shift" and e["display"]["workLocation"] == "Main Plant"
    assert e["payroll"]["values"] == {"payrollGroup": "group_a", "paymentMode": "bank_transfer", "bankAccountNumber": "••••5678", "bankIfsc": "ABCD0123456"}
    assert e["restricted"] == {"contact": False, "payroll": False}
    assert e["audit"]["createdBy"] == "Asha HR" and e["audit"]["createdAt"].endswith("Z")
    assert (await client.get(f"{BASE}/{e['id']}", headers=hr())).json() == e


async def test_bank_account_is_encrypted_at_rest(client, db, org):
    e = await create(client, org)
    rows = {r.field_key: r for r in (await db.scalars(select(EmployeePayrollValue))).all()}
    bank = rows["bankAccountNumber"]
    assert bank.encrypted and "12345678" not in bank.value and crypto.decrypt(bank.value) == "000012345678"
    assert not rows["bankIfsc"].encrypted and rows["bankIfsc"].value == "ABCD0123456"
    # Nothing stores or logs the plain value.
    entries = (await db.scalars(select(AuditLog).where(AuditLog.entity_id == e["id"]))).all()
    assert entries and all("000012345678" not in str(x.changes) + x.summary for x in entries)


async def test_field_scoping_contact_and_payroll(client, org):
    e = await create(client, org)
    basic = hr(["hr.employees:view"])
    r = (await client.get(f"{BASE}/{e['id']}", headers=basic)).json()
    assert r["restricted"] == {"contact": True, "payroll": True} and r["payroll"] is None
    assert {k: r["personal"][k] for k in ("mobile", "email", "address", "emergencyContact")} == {"mobile": None, "email": None, "address": None, "emergencyContact": None}
    row = (await client.get(BASE, headers=basic)).json()["items"][0]
    assert row["email"] is None and row["mobile"] is None and row["fullName"] == "Ravi Iyer"
    row = (await client.get(BASE, headers=hr(["hr.employees:view", "hr.employees:view-contact"]))).json()["items"][0]
    assert row["email"] == "evr-1001@example.com"


async def test_restricted_sections_cannot_be_written_without_permission(client, db, org):
    no_sensitive = hr(["hr.employees:create", "hr.employees:view-contact"], user_id="33333333-3333-3333-3333-333333333333")
    r = await client.post(BASE, json=payload(org), headers=no_sensitive)
    assert r.status_code == 403
    denial = await db.scalar(select(AuditLog).where(AuditLog.result == "denied", AuditLog.actor_user_id == "33333333-3333-3333-3333-333333333333"))
    assert "hr.employees:view-sensitive" in denial.summary
    body = payload(org)
    body.pop("payroll")
    r = await client.post(BASE, json=body, headers=hr(["hr.employees:create"]))
    assert r.status_code == 403, "contact details need hr.employees:view-contact"
    for k in ("mobile", "email", "address", "emergencyContact"):
        body["personal"].pop(k)
    r = await client.post(BASE, json=body, headers=hr(["hr.employees:create"]))
    assert r.status_code == 201 and r.json()["restricted"] == {"contact": True, "payroll": True}
    assert await db.scalar(select(EmployeeContact)) is None


async def test_update_keeps_withheld_and_write_only_values(client, db, org):
    e = await create(client, org)
    body = payload(org, version=1)
    for k in ("mobile", "email", "address", "emergencyContact"):
        body["personal"].pop(k)  # caller-without-contact behaviour: omitted = unchanged
    body["payroll"] = {"payrollGroup": "group_b", "paymentMode": "", "bankIfsc": "ABCD0123456"}  # bank account omitted = keep
    r = await client.patch(f"{BASE}/{e['id']}", json=body, headers=hr())
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["version"] == 2 and out["personal"]["email"] == "evr-1001@example.com"
    assert out["payroll"]["values"] == {"payrollGroup": "group_b", "paymentMode": None, "bankAccountNumber": "••••5678", "bankIfsc": "ABCD0123456"}
    r = await client.patch(f"{BASE}/{e['id']}", json=body, headers=hr())
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_VERSION"
    history = (await client.get(f"{BASE}/{e['id']}/history", headers=hr())).json()
    assert [h["action"] for h in history["items"]] == ["updated", "created"]
    assert history["items"][0]["changes"] == ["Payroll details"] and history["items"][0]["actor"]["name"] == "Asha HR"


async def test_contact_only_edit_moves_version_and_history(client, org):
    e = await create(client, org)
    body = payload(org, version=1, personal__mobile="+91 90000 00000")
    r = await client.patch(f"{BASE}/{e['id']}", json=body, headers=hr())
    assert r.json()["version"] == 2
    entry = (await client.get(f"{BASE}/{e['id']}/history", headers=hr())).json()["items"][0]
    assert entry["changes"] == ["Contact details"] and "90000" not in str(entry)


async def test_validation_messages_match_the_form(client, org):
    await create(client, org)
    bad = payload(
        org, "evr-1001", personal__firstName="", personal__dateOfBirth="2099-01-01", personal__mobile="12", personal__email="nope",
        personal__emergencyContact={"relationship": "Brother"}, employment__departmentId="x", employment__designationId="", employment__statusCode="exited",
        employment__probation={"applicable": True, "endDate": None, "confirmationDate": "2019-01-01"}, work__attendanceId="1001",
        payroll={"bankAccountNumber": "12", "paymentMode": "cash", "unknownKey": "1"},
    )
    r = await client.post(BASE, json=bad, headers=hr())
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_FAILED"
    assert details(r) == {
        "employeeCode": "Another employee uses this employee ID.",
        "personal.firstName": "First name is required.",
        "personal.dateOfBirth": "Date of birth cannot be in the future.",
        "personal.mobile": "Enter a valid contact number (7–15 digits).",
        "personal.email": "Enter a valid email address.",
        "personal.emergencyContact.name": "Enter the contact name, or clear the emergency contact.",
        "personal.emergencyContact.phone": "Enter the contact phone number, or clear the emergency contact.",
        "employment.departmentId": "Select an existing department.",
        "employment.designationId": "Select a designation.",
        "employment.statusCode": "This status cannot be used for a new employee.",
        "employment.probation.endDate": "Enter the probation end date.",
        "employment.probation.confirmationDate": "Confirmation date cannot be before the joining date.",
        "work.attendanceId": "Another employee uses this attendance ID.",
        "payroll.bankAccountNumber": "Enter 6–18 digits.",
        "payroll.paymentMode": "Select a valid payment mode.",
        "payroll.unknownKey": "This payroll field is not in use.",
    }
    r = await client.post(BASE, json=payload(org, "EVR 9", personal__email="EVR-1001@EXAMPLE.COM"), headers=hr())
    assert details(r)["employeeCode"] == "Employee ID cannot contain spaces." and details(r)["personal.email"] == "Another employee uses this email address."
    r = await client.post(BASE, json=payload(org, "EVR-2", personal__dateOfBirth="2020-01-15"), headers=hr())
    assert details(r) == {"personal.dateOfBirth": "Date of birth must be before the joining date."}


async def test_reporting_manager_rules(client, org):
    boss = await create(client, org, "EVR-1")
    mid = await create(client, org, "EVR-2", employment__reportingManagerId=boss["id"])
    assert mid["display"]["reportingManager"] == {"id": boss["id"], "name": "Ravi Iyer"}
    r = await client.patch(f"{BASE}/{boss['id']}", json=payload(org, "EVR-1", employment__reportingManagerId=mid["id"]), headers=hr())
    assert details(r) == {"employment.reportingManagerId": "The manager cannot be one of this employee's reports."}
    r = await client.patch(f"{BASE}/{boss['id']}", json=payload(org, "EVR-1", employment__reportingManagerId=boss["id"]), headers=hr())
    assert details(r) == {"employment.reportingManagerId": "An employee cannot report to themself."}


async def test_directory_paging_sorting_and_filters(client, org):
    await create(client, org, "EVR-3", first="Chitra", dept="HR")
    await create(client, org, "EVR-1", first="Anil")
    await create(client, org, "EVR-2", first="Bala")
    r = (await client.get(BASE, params={"pageSize": 10, "sort": "fullName:desc"}, headers=hr())).json()
    assert [i["fullName"] for i in r["items"]] == ["Chitra Iyer", "Bala Iyer", "Anil Iyer"] and r["meta"]["totalItems"] == 3
    assert set(r["items"][0]) == {"id", "employeeCode", "fullName", "photoUrl", "department", "designation", "employmentType", "status", "joiningDate", "reportingManager", "email", "mobile"}
    r = (await client.get(BASE, params={"departmentId": org.dept["HR"]}, headers=hr())).json()
    assert [i["employeeCode"] for i in r["items"]] == ["EVR-3"]
    r = (await client.get(BASE, params={"q": "bala"}, headers=hr())).json()
    assert [i["employeeCode"] for i in r["items"]] == ["EVR-2"]
    assert (await client.get(BASE, params={"sort": "salary:asc"}, headers=hr())).status_code == 400
    assert (await client.get(BASE, params={"pageSize": 7}, headers=hr())).status_code == 422
    assert (await client.get(BASE, params={"status": "on_notice"}, headers=hr())).json()["items"] == []


async def test_history_is_append_only(client, db, org):
    await create(client, org)
    for sql in ("UPDATE employee_history SET summary = 'x'", "DELETE FROM employee_history"):
        nested = await db.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text(sql))
        await nested.rollback()


async def test_unknown_or_invalid_ids_are_404(client, org):
    assert (await client.get(f"{BASE}/not-a-uuid", headers=hr())).status_code == 404
    assert (await client.get(f"{BASE}/00000000-0000-0000-0000-00000000abcd", headers=hr())).status_code == 404
    assert (await client.get(f"{BASE}/00000000-0000-0000-0000-00000000abcd/history", headers=hr())).status_code == 404
