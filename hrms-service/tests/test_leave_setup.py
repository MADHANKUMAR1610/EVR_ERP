"""Module 6: leave configuration. Nothing is pre-filled; types, policies, holidays and balances are
entered by HR and audited; holidays are company-wide or location-specific (owner decision 4)."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models.audit_log_model import AuditLog
from app.models.leave_model import LeaveLedgerEntry
from app.services.employee_support import company_today
from tests.conftest import auth
from tests.employee_fixtures import create, details, org  # noqa: F401
from tests.leave_fixtures import LEAVE, SETUP, credit, leave_type, setup_headers
from tests.test_attendance_corrections_workflow import as_employee


async def test_nothing_is_prefilled(client, org):
    anyone = auth([])
    assert (await client.get("/api/v1/hr/leave-types", headers=anyone)).json() == []
    assert (await client.get("/api/v1/hr/holidays", headers=anyone)).json() == []
    assert (await client.get(f"{LEAVE}/policies", headers=auth(["hr.leave-policies:view"]))).json() == []
    assert (await client.get(f"{LEAVE}/approval-workflows", headers=auth(["hr.leave-policies:view"]))).json() == []
    doc = (await client.get("/api/v1/admin/policies/leave", headers=auth(["admin:policies.view"]))).json()
    assert set(doc["values"]) == {"allowNegativeBalance", "countOffsWithinLeave", "minimumNoticeDays", "backdatedWindowDays", "leaveYearStartMonth", "lowBalanceThreshold", "upcomingWindowDays"}
    assert all(v is None for v in doc["values"].values()), "every leave rule starts empty"
    assert (await client.get("/api/v1/hr/leave-types")).status_code == 401


async def test_leave_types_setup_rules_and_audit(client, db):
    assert (await client.post(f"{SETUP}/leave-types", json={"code": "CL", "name": "Casual", "paid": True, "balanceTracked": True}, headers=auth(["hr.leave-policies:view"]))).status_code == 403
    r = await client.post(f"{SETUP}/leave-types", json={"code": "bad code!", "name": "X", "paid": True, "balanceTracked": True, "attachmentAfterDays": -1}, headers=setup_headers())
    assert r.status_code == 422 and set(details(r)) == {"code", "name", "attachmentAfterDays"}
    lt = await leave_type(client, "CL", "Casual leave", attach=2)
    assert lt == {**lt, "code": "CL", "paid": True, "allowHalfDay": True, "balanceTracked": True, "attachmentAfterDays": 2, "active": True}
    dup = await client.post(f"{SETUP}/leave-types", json={"code": "CL", "name": "Again", "paid": True, "balanceTracked": True}, headers=setup_headers())
    assert dup.status_code == 422 and "already uses" in details(dup)["code"]
    stored = (await client.get(f"{SETUP}/leave-types", headers=setup_headers())).json()[0]
    changed = await client.put(f"{SETUP}/leave-types/{lt['id']}", json={"code": "CL2", "name": "Casual", "paid": True, "balanceTracked": True, "version": 1}, headers=setup_headers())
    assert changed.status_code == 422 and "cannot be changed" in details(changed)["code"]
    ok = await client.put(f"{SETUP}/leave-types/{lt['id']}", json={"code": "CL", "name": "Casual leave (CL)", "paid": True, "balanceTracked": True, "active": False, "version": 1}, headers=setup_headers())
    assert ok.status_code == 200 and ok.json()["active"] is False and stored["name"] == "Casual leave"
    stale = await client.put(f"{SETUP}/leave-types/{lt['id']}", json={"code": "CL", "name": "X Y", "paid": True, "balanceTracked": True, "version": 1}, headers=setup_headers())
    assert stale.status_code == 409
    assert {a.action for a in (await db.scalars(select(AuditLog).where(AuditLog.module == "Leave"))).all()} >= {"leave_type.created", "leave_type.updated"}
    # The code is also protected in the database (as Module 1 codes).
    with pytest.raises(DBAPIError, match="cannot be changed"):
        async with db.begin_nested():
            await db.execute(text("UPDATE leave_type SET code = 'ZZ'"))


async def test_policies_are_hr_entered_effective_dated_and_never_overlap(client, org):
    lt = await leave_type(client)
    unpaid = await leave_type(client, "LOP", "Loss of pay", paid=False, tracked=False)
    base = {"leaveTypeId": lt["id"], "accrualMethod": "monthly", "accrualDays": 1.5, "carryForwardAllowed": True, "carryForwardMaxDays": 10, "effectiveFrom": "2026-01-01"}
    r = await client.post(f"{SETUP}/leave-policies", json={**base, "employmentTypeIds": [org.etype["PERM"]]}, headers=setup_headers())
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["accrual"] == {"method": "monthly", "days": 1.5} and p["carryForward"] == {"allowed": True, "maxDays": 10.0}
    assert p["appliesTo"] != "All employees" and p["allowHalfDay"] is True
    clash = await client.post(f"{SETUP}/leave-policies", json={**base, "effectiveFrom": "2026-06-01"}, headers=setup_headers())
    assert clash.status_code == 422 and "applies to some of the same employees" in details(clash)["effectiveFrom"]
    other_type = await client.post(f"{SETUP}/leave-policies", json={**base, "employmentTypeIds": [next(v for k, v in org.etype.items() if k != "PERM")]}, headers=setup_headers())
    assert other_type.status_code == 201, "another employment type may have its own rules"
    bad = await client.post(f"{SETUP}/leave-policies", json={"leaveTypeId": unpaid["id"], "accrualMethod": "annual", "accrualDays": 12, "effectiveFrom": "2026-01-01"}, headers=setup_headers())
    assert bad.status_code == 422 and "does not track a balance" in details(bad)["accrualMethod"]
    invalid = await client.post(f"{SETUP}/leave-policies", json={"leaveTypeId": lt["id"], "accrualMethod": "annual", "accrualDays": 0.3, "carryForwardMaxDays": 5, "effectiveFrom": "x"}, headers=setup_headers())
    assert invalid.status_code == 422 and set(details(invalid)) >= {"accrualDays", "carryForwardMaxDays", "effectiveFrom"}
    listed = (await client.get(f"{LEAVE}/policies", headers=auth(["hr.leave-policies:view"]))).json()
    assert len(listed) == 2 and "employmentTypeIds" not in listed[0], "the read-only contract shape"


async def test_holidays_company_wide_and_per_location(client, org):
    year = company_today().year
    h = lambda d, name, loc=None, t="festival": {"date": d, "name": name, "type": t, "workLocationId": loc}  # noqa: E731
    for body in (h(f"{year}-08-15", "Independence Day", t="national"), h(f"{year}-10-20", "Diwali"), h(f"{year}-09-05", "Plant 2 day", org.loc["PLANT2"], "company"),
                 h(f"{year}-08-15", "Plant 1 flag day", org.loc["PLANT1"], "company")):
        r = await client.post(f"{SETUP}/holidays", json=body, headers=setup_headers())
        assert r.status_code == 201, r.text
    dup = await client.post(f"{SETUP}/holidays", json=h(f"{year}-10-20", "Again"), headers=setup_headers())
    assert dup.status_code == 422 and "already exists" in details(dup)["date"]
    bad = await client.post(f"{SETUP}/holidays", json=h("2026-13-01", "X", "not-an-id"), headers=setup_headers())
    assert bad.status_code == 422 and set(details(bad)) == {"date", "name", "workLocationId"}

    plant1 = await create(client, org, "EVR-1")  # work location PLANT1
    mine = (await client.get("/api/v1/hr/holidays", params={"year": year}, headers=as_employee(plant1))).json()
    assert [(x["date"], x["name"]) for x in mine] == [(f"{year}-08-15", "Independence Day"), (f"{year}-08-15", "Plant 1 flag day"), (f"{year}-10-20", "Diwali")]
    assert all(set(x) == {"date", "name", "type"} for x in mine), "the contract shape"
    all_ = (await client.get("/api/v1/hr/holidays", params={"year": year}, headers=auth(["hr.leave:view"]))).json()
    assert len(all_) == 4, "HR sees every holiday"
    none_linked = (await client.get("/api/v1/hr/holidays", params={"year": year}, headers=auth([]))).json()
    assert len(none_linked) == 2, "a caller without an employee record gets the company-wide holidays"
    setup = (await client.get(f"{SETUP}/holidays", params={"year": year}, headers=setup_headers())).json()
    plant2 = next(x for x in setup if x["name"] == "Plant 2 day")
    assert plant2["location"]["name"] == "Unit 2"
    assert (await client.delete(f"{SETUP}/holidays/{plant2['id']}", headers=setup_headers())).status_code == 204


async def test_allocations_and_adjustments_are_ledger_entries_with_reasons(client, db, org):
    lt = await leave_type(client)
    unpaid = await leave_type(client, "LOP", "Loss of pay", tracked=False)
    e = await create(client, org, "EVR-1")
    await credit(client, e, lt, 12)
    adj = await credit(client, e, lt, -1.5, kind="leave-adjustments")
    assert adj["entryType"] == "adjustment" and adj["days"] == -1.5 and adj["reason"] == "Opening balance (test)"
    r = await client.post(f"{SETUP}/leave-allocations", json={"employeeId": e["id"], "leaveTypeId": unpaid["id"], "year": 2026, "days": -2, "reason": ""}, headers=setup_headers())
    assert r.status_code == 422 and set(details(r)) == {"leaveTypeId", "days", "reason"}
    other_scope = auth(["hr.leave-policies:manage"], roles=["test-hr-qa"])
    outside = await create(client, org, "EVR-2", dept="ENG")
    r = await client.post(f"{SETUP}/leave-allocations", json={"employeeId": outside["id"], "leaveTypeId": lt["id"], "year": 2026, "days": 1, "reason": "x y z"}, headers=other_scope)
    assert r.status_code == 422 and "organizational scope" in details(r)["employeeId"]
    ledger = (await client.get(f"{SETUP}/leave-ledger", params={"employeeId": e["id"]}, headers=setup_headers())).json()
    assert [x["entryType"] for x in ledger["items"]] == ["adjustment", "allocation"] and ledger["meta"]["totalItems"] == 2
    year = company_today().year
    bal = (await client.get("/api/v1/hr/me/leave/balances", params={"year": year}, headers=as_employee(e))).json()
    el = next(b for b in bal["balances"] if b["leaveType"]["code"] == "EL")
    assert el == {**el, "allocated": 12.0, "carriedForward": 0.0, "used": 0.0, "pending": 0.0, "available": 10.5}
    lop = next(b for b in bal["balances"] if b["leaveType"]["code"] == "LOP")
    assert lop["allocated"] is None and lop["available"] is None, "untracked types have no allocation"
    # Append-only in the database: balances are corrected by new entries only.
    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(text("UPDATE leave_ledger_entry SET days = 99"))
    assert await db.scalar(select(LeaveLedgerEntry).where(LeaveLedgerEntry.days == 99)) is None
