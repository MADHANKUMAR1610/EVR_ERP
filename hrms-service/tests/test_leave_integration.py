"""Module 6 integrations: attendance (on_leave, half_day, holiday, locked periods), accrual and
carry-forward jobs, the leave summary, the approval inbox, and Part B (permission and overtime)."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.context import SYSTEM_PRINCIPAL
from app.database.audit_listener import acting_as
from app.models.attendance_model import AttendanceDay
from app.models.leave_model import LeaveLedgerEntry
from app.services.employee_support import company_today
from app.services.leave.balance_service import run_accrual
from tests.attendance_fixtures import BASE, device, ingest, local, past_workday  # noqa: F401
from tests.conftest import auth
from tests.employee_fixtures import create, details, hr, org  # noqa: F401
from tests.leave_fixtures import APPROVER, LEAVE, SETUP, apply, credit, decide, hr_leave, leave_type, monday, set_leave_policy, setup_headers
from tests.test_attendance_corrections_workflow import as_employee, run_jobs, team

ATT = hr(["hr.attendance:view"])


async def test_approved_leave_and_holidays_in_attendance(client, db, org, device):
    manager, e = await team(client, org)
    lt = await leave_type(client, tracked=False)
    d1 = past_workday(6)
    d2 = past_workday((company_today() - d1).days + 1)  # the working day before d1
    hol = past_workday(3)
    await client.post(f"{SETUP}/holidays", json={"date": hol.isoformat(), "name": "Founders day", "type": "company"}, headers=setup_headers())
    full = (await apply(client, as_employee(e), lt, d1)).json()
    await decide(client, as_employee(manager, APPROVER), full)
    await ingest(client, device, ("2", local(d2, 9, 40), "in"), ("2", local(d2, 17, 30), "out"))  # late, but on first-half leave
    half = (await apply(client, as_employee(e), lt, d2, portion="first_half")).json()
    await decide(client, as_employee(manager, APPROVER), half)

    day = (await client.get(f"{BASE}/daily/{e['id']}", params={"date": d1.isoformat()}, headers=ATT)).json()
    assert day["status"] == "on_leave" and day["leaveTypeName"] == "Earned leave" and day["exceptions"] == []
    day = (await client.get(f"{BASE}/daily/{e['id']}", params={"date": d2.isoformat()}, headers=ATT)).json()
    assert day["status"] == "half_day" and day["leaveTypeName"] == "Earned leave" and "late_arrival" not in day["exceptions"] and day["lateMinutes"] == 0
    day = (await client.get(f"{BASE}/daily/{e['id']}", params={"date": hol.isoformat()}, headers=ATT)).json()
    assert day["status"] == "holiday" and day["holidayName"] == "Founders day" and "absent" not in day["exceptions"]
    if d1.strftime("%Y-%m") == hol.strftime("%Y-%m") == d2.strftime("%Y-%m"):
        cal = (await client.get(f"{BASE}/employees/{e['id']}/calendar", params={"month": d1.strftime("%Y-%m")}, headers=ATT)).json()
        assert cal["summary"]["approvedLeaveDays"] == 1.5 and cal["summary"]["holidays"] == 1
    await run_jobs(db)
    stored = await db.scalar(select(AttendanceDay).where(AttendanceDay.employee_id == uuid.UUID(e["id"]), AttendanceDay.date == d1))
    assert stored is not None and stored.status == "on_leave", "approval recalculated the stored day"


async def test_locked_payroll_periods_refuse_leave_and_holiday_changes(client, org):
    manager, e = await team(client, org)
    lt = await leave_type(client, tracked=False)
    d = past_workday(5)
    req = (await apply(client, as_employee(e), lt, d)).json()
    lock = await client.post("/api/v1/hr/setup/attendance-period-locks", json={"fromDate": d.isoformat(), "toDate": d.isoformat(), "reason": "Payroll finalized"}, headers=hr(["hr.payroll:approve"]))
    assert lock.status_code == 201
    r = await decide(client, as_employee(manager, APPROVER), req)
    assert r.status_code == 409 and r.json()["error"]["code"] == "PERIOD_LOCKED"
    h = await client.post(f"{SETUP}/holidays", json={"date": d.isoformat(), "name": "Late holiday", "type": "company"}, headers=setup_headers())
    assert h.status_code == 409 and h.json()["error"]["code"] == "PERIOD_LOCKED"


async def test_accrual_and_carry_forward_apply_only_hr_policies_and_are_idempotent(client, db, org):
    e = await create(client, org, "EVR-1")
    lt = await leave_type(client)
    with acting_as(SYSTEM_PRINCIPAL):
        assert await run_accrual(db) == {"credited": 0, "carriedForward": 0}, "nothing is credited without an HR policy"
    today = company_today()
    year = today.year
    await client.post(f"{SETUP}/leave-policies", json={"leaveTypeId": lt["id"], "accrualMethod": "monthly", "accrualDays": 1.5, "carryForwardAllowed": True, "carryForwardMaxDays": 5,
                                                       "effectiveFrom": f"{year - 1}-01-01"}, headers=setup_headers())
    # Last year's remaining balance: 8 days (credited by HR for the test).
    await credit(client, e, lt, 8, year=year - 1)
    with acting_as(SYSTEM_PRINCIPAL):
        first = await run_accrual(db)
        again = await run_accrual(db)
    assert first == {"credited": today.month, "carriedForward": 1} and again == {"credited": 0, "carriedForward": 0}, "monthly credits Jan..this month, once"
    entries = (await db.scalars(select(LeaveLedgerEntry).where(LeaveLedgerEntry.employee_id == uuid.UUID(e["id"])).order_by(LeaveLedgerEntry.leave_year, LeaveLedgerEntry.entry_type))).all()
    kinds = [(x.leave_year, x.entry_type, float(x.days)) for x in entries]
    assert (year, "carry_forward", 5.0) in kinds and (year - 1, "lapse", -8.0) in kinds, "capped at maxDays; the old year is closed"
    bal = (await client.get("/api/v1/hr/me/leave/balances", params={"year": year}, headers=as_employee(e))).json()["balances"][0]
    assert bal["allocated"] == 1.5 * today.month and bal["carriedForward"] == 5 and bal["available"] == 1.5 * today.month + 5
    old = (await client.get("/api/v1/hr/me/leave/balances", params={"year": year - 1}, headers=as_employee(e))).json()["balances"][0]
    assert old["available"] == 0, "unused leave of a past year is not counted in the new year"


async def test_leave_year_start_month_setting(client, org):
    e = await create(client, org, "EVR-1")
    lt = await leave_type(client)
    today = company_today()
    start_month = today.month  # the leave year starts this month
    await set_leave_policy(client, {"leaveYearStartMonth": start_month})
    await credit(client, e, lt, 4, year=today.year)
    mon = monday()
    r = await client.get(f"{LEAVE}/requests/estimate", params={"leaveTypeId": lt["id"], "from": mon.isoformat(), "to": mon.isoformat()}, headers=as_employee(e))
    assert r.json()["availableBefore"] == 4


async def test_summary_lists_follow_hr_settings(client, org):
    manager, e = await team(client, org)
    lt = await leave_type(client)
    await credit(client, e, lt, 3, year=company_today().year)
    today = company_today()
    if today.isoweekday() != 7:
        on = (await apply(client, as_employee(e), lt, today)).json()
        await decide(client, as_employee(manager, APPROVER), on)
    s = (await client.get(f"{LEAVE}/summary", headers=hr_leave())).json()
    assert s["upcoming"] == [] and s["upcomingWindowDays"] == 0 and s["lowBalances"] == [] and s["lowBalanceThreshold"] == 0, "empty settings: no lists"
    if today.isoweekday() != 7:
        assert [x["employee"]["id"] for x in s["onLeaveToday"]] == [e["id"]]
    await set_leave_policy(client, {"upcomingWindowDays": 30, "lowBalanceThreshold": 5})
    soon = today + timedelta(days=8 if (today + timedelta(days=8)).isoweekday() != 7 else 9)
    up = (await apply(client, as_employee(e), lt, soon)).json()
    await decide(client, as_employee(manager, APPROVER), up)
    pend = await apply(client, as_employee(e), lt, soon + timedelta(days=1 if (soon + timedelta(days=1)).isoweekday() != 7 else 2))
    assert pend.status_code == 201
    s = (await client.get(f"{LEAVE}/summary", headers=hr_leave())).json()
    assert [x["id"] for x in s["upcoming"]] == [up["id"]] and s["pendingRequests"] == 1 and s["awaitingMyAction"] == 1
    assert s["lowBalances"][0]["employee"]["id"] == e["id"] and s["lowBalances"][0]["available"] <= 5
    assert (await client.get(f"{LEAVE}/summary", headers=auth(["hr.approvals:view"]))).status_code == 403


async def test_permission_and_overtime_requests(client, db, org, device):
    manager, e = await team(client, org)
    me = as_employee(e)
    d = past_workday(4)
    r = await client.post("/api/v1/hr/permission-requests", json={"date": d.isoformat(), "from": "11:00", "to": "10:30", "reason": "x"}, headers=me)
    assert r.status_code == 422 and details(r) == {"to": "The end time must be after the start time.", "reason": "Enter a reason."}
    p = await client.post("/api/v1/hr/permission-requests", json={"date": d.isoformat(), "from": "10:00", "to": "11:30", "reason": "Bank visit"}, headers=me)
    assert p.status_code == 201 and p.json()["minutes"] == 90 and p.json()["from"] == "10:00"
    clash = await client.post("/api/v1/hr/permission-requests", json={"date": d.isoformat(), "from": "11:00", "to": "12:00", "reason": "Second visit"}, headers=me)
    assert clash.status_code == 422
    pr = p.json()
    assert (await client.post(f"/api/v1/hr/permission-requests/{pr['id']}/decision", json={"decision": "approve", "version": pr["version"]}, headers=as_employee(e, ("hr.approvals:act",)))).status_code == 403
    ok = await client.post(f"/api/v1/hr/permission-requests/{pr['id']}/decision", json={"decision": "approve", "version": pr["version"]}, headers=as_employee(manager, APPROVER))
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and [h["action"] for h in ok.json()["history"]] == ["submitted", "approved"]
    again = await client.post(f"/api/v1/hr/permission-requests/{pr['id']}/decision", json={"decision": "reject", "comment": "No", "version": ok.json()["version"]}, headers=hr(["hr.permission-requests:approve"]))
    assert again.status_code == 409

    await ingest(client, device, ("2", local(d, 9), "in"), ("2", local(d, 19), "out"))
    o = await client.post("/api/v1/hr/overtime-requests", json={"date": d.isoformat(), "minutes": 961, "reason": "Transformer test run"}, headers=me)
    assert details(o)["minutes"] == "Overtime for one day cannot exceed 16 hours."
    future = await client.post("/api/v1/hr/overtime-requests", json={"date": (company_today() + timedelta(days=2)).isoformat(), "minutes": 60, "reason": "Later"}, headers=me)
    assert future.status_code == 422
    o = await client.post("/api/v1/hr/overtime-requests", json={"date": d.isoformat(), "minutes": 90, "reason": "Transformer test run"}, headers=me)
    assert o.status_code == 201, o.text
    ot = o.json()
    assert ot["recordedMinutes"] == 90, "attendance's time beyond the shift (09:00-17:30)"
    listed = (await client.get("/api/v1/hr/overtime-requests", params={"scope": "mine"}, headers=me)).json()
    assert listed["meta"]["totalItems"] == 1
    assert (await client.get("/api/v1/hr/overtime-requests", headers=me)).status_code == 403, "scope=all needs a view permission"
    rej = await client.post(f"/api/v1/hr/overtime-requests/{ot['id']}/decision", json={"decision": "reject", "version": ot["version"]}, headers=hr(["hr.overtime:approve"]))
    assert details(rej)["comment"] == "Enter a comment explaining the rejection."
    ok = await client.post(f"/api/v1/hr/overtime-requests/{ot['id']}/decision", json={"decision": "approve", "version": ot["version"]}, headers=hr(["hr.overtime:approve", "hr.overtime:view"]))
    assert ok.status_code == 200 and ok.json()["status"] == "approved"


async def test_approval_inbox_lists_what_the_caller_may_decide_now(client, org):
    manager, e = await team(client, org)
    lt = await leave_type(client, tracked=False)
    me = as_employee(e)
    d = past_workday(4)
    await apply(client, me, lt, monday())
    await client.post("/api/v1/hr/permission-requests", json={"date": d.isoformat(), "from": "10:00", "to": "11:00", "reason": "Bank visit"}, headers=me)
    await client.post("/api/v1/hr/overtime-requests", json={"date": d.isoformat(), "minutes": 30, "reason": "Late dispatch"}, headers=me)
    inbox = (await client.get("/api/v1/hr/approvals", headers=as_employee(manager, APPROVER))).json()
    assert inbox["counts"] == {"leave": 1, "permission": 1, "overtime": 1, "attendance_correction": 0}
    assert [i["type"] for i in inbox["items"]] == ["leave", "permission", "overtime"], "oldest first"
    item = inbox["items"][0]
    assert item["id"] == f"leave:{item['requestId']}" and "Earned leave · 1 day" in item["summary"] and item["employee"]["id"] == e["id"]
    only = (await client.get("/api/v1/hr/approvals", params={"type": "permission", "pageSize": 10}, headers=as_employee(manager, APPROVER))).json()
    assert len(only["items"]) == 1 and only["counts"]["leave"] == 1 and only["meta"]["totalItems"] == 1
    own = (await client.get("/api/v1/hr/approvals", headers=as_employee(e, ("hr.approvals:view", "hr.approvals:act")))).json()
    assert own["meta"]["totalItems"] == 0, "never one's own requests"
    hr_view = (await client.get("/api/v1/hr/approvals", headers=hr(["hr.leave:approve", "hr.permission-requests:approve"]))).json()
    assert hr_view["counts"] == {"leave": 1, "permission": 1, "overtime": 0, "attendance_correction": 0}
    assert (await client.get("/api/v1/hr/approvals", headers=auth(["hr.self:view"]))).status_code == 403
