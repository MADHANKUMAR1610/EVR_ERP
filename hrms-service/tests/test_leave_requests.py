"""Module 6: leave applications, day counting, balances (owner decision 3), decisions (decision 2),
cancellation, comments and attachments."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.models.audit_log_model import AuditLog
from app.models.leave_model import LeaveLedgerEntry, RequestEvent
from app.services.employee_support import company_today
from tests.attendance_fixtures import past_workday
from tests.conftest import auth
from tests.employee_fixtures import create, details, org  # noqa: F401
from tests.leave_fixtures import APPROVER, LEAVE, PDF, PNG, SETUP, apply, credit, decide, hr_leave, leave_type, monday, set_leave_policy, setup_headers
from tests.test_attendance_corrections_workflow import as_employee, team


async def _estimate(client, headers, lt, start, end=None, portion="full", **kw):
    params = {"leaveTypeId": lt["id"], "from": start.isoformat(), "to": (end or start).isoformat(), "portion": portion, **kw}
    return await client.get(f"{LEAVE}/requests/estimate", params=params, headers=headers)


async def test_estimate_excludes_weekly_offs_and_holidays(client, org):
    _, e = await team(client, org)
    lt = await leave_type(client)
    mon = monday()
    await client.post(f"{SETUP}/holidays", json={"date": (mon + timedelta(days=2)).isoformat(), "name": "Test festival", "type": "festival"}, headers=setup_headers())
    await credit(client, e, lt, 3, year=mon.year)
    r = await _estimate(client, as_employee(e), lt, mon, mon + timedelta(days=6))
    assert r.status_code == 200, r.text
    est = r.json()
    # Monday-Sunday: Sunday is the GEN shift's weekly off, Wednesday the holiday -> 5 days.
    assert est["days"] == 5 and {x["reason"] for x in est["excludedDates"]} == {"Weekly off", "Holiday: Test festival"}
    assert est["availableBefore"] == 3 and any("needs 5 days but only 3 are available" in w for w in est["warnings"]), "the shortfall is always shown"
    half = (await _estimate(client, as_employee(e), lt, mon, portion="first_half")).json()
    assert half["days"] == 0.5
    await set_leave_policy(client, {"countOffsWithinLeave": True})
    assert (await _estimate(client, as_employee(e), lt, mon, mon + timedelta(days=6))).json()["days"] == 7, "HR setting: offs inside leave are charged"
    sunday = (await _estimate(client, as_employee(e), lt, mon + timedelta(days=13)))
    assert sunday.json()["days"] == 1


async def test_balance_is_blocked_by_default_and_allowed_only_when_hr_enables_it(client, db, org):
    _, e = await team(client, org)
    lt = await leave_type(client)
    mon = monday()
    await credit(client, e, lt, 2, year=mon.year)
    r = await apply(client, as_employee(e), lt, mon, mon + timedelta(days=2))
    assert r.status_code == 422 and details(r)["leaveTypeId"] == "This request needs 3 days but only 2 are available.", "decision 3: blocked by default"
    ok = await apply(client, as_employee(e), lt, mon, mon + timedelta(days=1))
    assert ok.status_code == 201 and ok.json()["days"] == 2
    again = await apply(client, as_employee(e), lt, mon + timedelta(days=7))
    assert again.status_code == 422 and "only 0 are available" in details(again)["leaveTypeId"], "pending days reduce the available balance"
    await set_leave_policy(client, {"allowNegativeBalance": True})
    neg = await apply(client, as_employee(e), lt, mon + timedelta(days=7))
    assert neg.status_code == 201, neg.text
    bal = (await client.get("/api/v1/hr/me/leave/balances", params={"year": mon.year}, headers=as_employee(e))).json()["balances"][0]
    assert bal == {**bal, "allocated": 2.0, "pending": 3.0, "available": -1.0}
    untracked = await leave_type(client, "LOP", "Loss of pay", paid=False, tracked=False)
    assert (await apply(client, as_employee(e), untracked, mon + timedelta(days=14))).status_code == 201, "no balance check for untracked types"


async def test_application_rules_and_messages(client, org):
    _, e = await team(client, org)
    lt = await leave_type(client, half=False)
    mon = monday()
    await credit(client, e, lt, 30, year=mon.year)
    me = as_employee(e)
    r = await client.post(f"{LEAVE}/requests", files={"leaveTypeId": (None, ""), "from": (None, "x"), "to": (None, ""), "portion": (None, "full"), "reason": (None, "a")}, headers=me)
    assert r.status_code == 422 and details(r) == {"leaveTypeId": "Choose a leave type.", "from": "Enter the first day.", "to": "Enter the last day.", "reason": "Enter a reason."}
    r = await apply(client, me, lt, mon + timedelta(days=2), mon, reason="x" * 501)
    assert details(r) == {"to": "The last day cannot be before the first day.", "reason": "Keep the reason under 500 characters."}
    r = await apply(client, me, lt, mon, mon + timedelta(days=1), portion="first_half")
    assert details(r)["portion"] == "Half days are only possible when the first and last day are the same."
    r = await apply(client, me, lt, mon, portion="second_half")
    assert details(r)["portion"] == "This leave type cannot be taken as a half day."
    r = await apply(client, me, lt, mon + timedelta(days=6))
    assert details(r)["from"] == "There are no working days in this range."
    first = await apply(client, me, lt, mon, mon + timedelta(days=2))
    assert first.status_code == 201
    r = await apply(client, me, lt, mon + timedelta(days=1))
    assert r.status_code == 422 and details(r)["from"].startswith("This overlaps with another leave request")
    est = (await _estimate(client, me, lt, mon + timedelta(days=1))).json()
    assert [o["id"] for o in est["overlapping"]] == [first.json()["id"]] and est["overlapping"][0]["leaveTypeName"] == "Earned leave"
    await set_leave_policy(client, {"minimumNoticeDays": 60, "backdatedWindowDays": 3})
    r = await apply(client, me, lt, mon + timedelta(days=8))
    assert details(r)["from"] == "Leave must be applied at least 60 days before it starts."
    r = await apply(client, me, lt, past_workday(10))
    assert details(r)["from"] == "Leave can be applied up to 3 days back."
    inactive = await leave_type(client, "OLD", "Old type", active=False)
    r = await apply(client, me, inactive, mon + timedelta(days=70))
    assert details(r)["leaveTypeId"] == "This leave type is no longer in use."


async def test_who_may_apply(client, org):
    manager, e = await team(client, org)
    lt = await leave_type(client, tracked=False)
    mon = monday()
    assert (await apply(client, as_employee(e, perms=("hr.self:view",)), lt, mon)).status_code == 403
    r = await apply(client, as_employee(e), lt, mon, employee_id=manager["id"])
    assert r.status_code == 422 and "only for yourself" in details(r)["employeeId"]
    qa_hr = auth(["hr.leave:apply-on-behalf"], roles=["test-hr-qa"])
    eng = await create(client, org, "EVR-9", dept="ENG")
    assert (await apply(client, qa_hr, lt, mon, employee_id=eng["id"])).status_code == 422, "outside the organizational scope"
    r = await apply(client, qa_hr, lt, mon, employee_id=e["id"])
    assert r.status_code == 201 and r.json()["submittedBy"] != e["display"]["fullName"]


async def test_manager_decides_first_decision_wins_and_ledger_is_charged_once(client, db, org):
    manager, e = await team(client, org)
    lt = await leave_type(client)
    mon = monday()
    await credit(client, e, lt, 10, year=mon.year)
    req = (await apply(client, as_employee(e), lt, mon, mon + timedelta(days=1))).json()
    assert req["approval"]["currentApprover"] == {"type": "reporting_manager", "name": manager["display"]["fullName"]}
    assert req["approval"]["escalation"] == "not_configured" and req["approval"]["workflow"] is None and req["approval"]["events"][0]["action"] == "assigned"
    assert (await decide(client, as_employee(e, ("hr.approvals:act",)), req)).status_code == 403, "never one's own request"
    outsider = await create(client, org, "EVR-3")
    assert (await decide(client, as_employee(outsider, APPROVER), req)).status_code == 404
    rej = await decide(client, as_employee(manager, APPROVER), req, "reject")
    assert rej.status_code == 422 and details(rej)["comment"] == "Enter a comment explaining the rejection."
    # A review comment moves the version: a decision based on the older view is stale.
    c = await client.post(f"{LEAVE}/requests/{req['id']}/comments", json={"comment": "Please confirm handover", "version": req["version"]}, headers=as_employee(manager, APPROVER))
    assert c.status_code == 200 and c.json()["version"] == req["version"] + 1 and c.json()["history"][-1]["action"] == "commented"
    stale = await decide(client, as_employee(manager, APPROVER), req)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "STALE_VERSION"
    ok = await decide(client, as_employee(manager, APPROVER), c.json(), comment="Enjoy")
    assert ok.status_code == 200, ok.text
    done = ok.json()
    assert done["status"] == "approved" and done["reviewComment"] == "Enjoy" and done["approval"]["stage"] == "completed" and done["approval"]["escalation"] == "not_applicable"
    hr_late = await decide(client, hr_leave(), done)
    assert hr_late.status_code == 409 and hr_late.json()["error"]["code"] == "INVALID_TRANSITION", "the first valid decision wins"
    reject_late = await decide(client, as_employee(manager, APPROVER), done, "reject", comment="No")
    assert reject_late.status_code == 409
    usage = (await db.scalars(select(LeaveLedgerEntry).where(LeaveLedgerEntry.leave_request_id == uuid.UUID(req["id"])))).all()
    assert [(u.entry_type, float(u.days)) for u in usage] == [("usage", -2.0)], "charged exactly once"
    bal = (await client.get("/api/v1/hr/me/leave/balances", params={"year": mon.year}, headers=as_employee(e))).json()["balances"][0]
    assert bal == {**bal, "used": 2.0, "pending": 0.0, "available": 8.0}
    events = (await db.scalars(select(RequestEvent.action).where(RequestEvent.request_id == uuid.UUID(req["id"])).order_by(RequestEvent.created_at))).all()
    assert list(events) == ["submitted", "commented", "approved"]
    assert {a.action for a in (await db.scalars(select(AuditLog).where(AuditLog.entity_id == req["id"]))).all()} >= {"leave_request.submitted", "leave_request.commented", "leave_request.approved"}


async def test_hr_oversight_and_rejection(client, org):
    manager, e = await team(client, org)
    lt = await leave_type(client, tracked=False)
    req = (await apply(client, as_employee(e), lt, monday())).json()
    qa_hr = auth(["hr.leave:approve", "hr.leave:view"], roles=["test-hr-qa"], name="QA HR")
    r = await decide(client, qa_hr, req, "reject", comment="Audit week")
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["reviewedBy"] == "QA HR"
    eng_hr = auth(["hr.leave:approve", "hr.leave:view"], roles=["test-hr-qa"])
    eng = await create(client, org, "EVR-7", dept="ENG")
    other = (await apply(client, as_employee(eng), lt, monday())).json()
    assert (await decide(client, eng_hr, other)).status_code == 404, "HR outside their scope cannot see it"


async def test_cancellation_rules_and_reversal(client, db, org):
    manager, e = await team(client, org)
    lt = await leave_type(client)
    mon = monday()
    await credit(client, e, lt, 10, year=mon.year)
    pending = (await apply(client, as_employee(e), lt, mon)).json()
    assert (await client.post(f"{LEAVE}/requests/{pending['id']}/cancellation", json={"version": pending["version"]}, headers=as_employee(manager, APPROVER))).status_code == 403
    r = await client.post(f"{LEAVE}/requests/{pending['id']}/cancellation", json={"version": pending["version"], "comment": "Plans changed"}, headers=as_employee(e))
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["approval"]["stage"] == "withdrawn"
    again = await client.post(f"{LEAVE}/requests/{pending['id']}/cancellation", json={"version": r.json()["version"]}, headers=as_employee(e))
    assert again.status_code == 409
    approved = (await decide(client, as_employee(manager, APPROVER), (await apply(client, as_employee(e), lt, mon + timedelta(days=1), mon + timedelta(days=2))).json())).json()
    r = await client.post(f"{LEAVE}/requests/{approved['id']}/cancellation", json={"version": approved["version"]}, headers=hr_leave())
    assert r.status_code == 200, r.text
    entries = (await db.scalars(select(LeaveLedgerEntry).where(LeaveLedgerEntry.leave_request_id == uuid.UUID(approved["id"])).order_by(LeaveLedgerEntry.created_at))).all()
    assert [(x.entry_type, float(x.days)) for x in entries] == [("usage", -2.0), ("usage_reversal", 2.0)]
    bal = (await client.get("/api/v1/hr/me/leave/balances", params={"year": mon.year}, headers=as_employee(e))).json()["balances"][0]
    assert bal["used"] == 0 and bal["available"] == 10
    # Started leave cannot be cancelled (L21).
    past = company_today() - timedelta(days=1)
    started = (await apply(client, as_employee(e), lt, past if past.isoweekday() != 7 else past - timedelta(days=1))).json()
    started = (await decide(client, as_employee(manager, APPROVER), started)).json()
    r = await client.post(f"{LEAVE}/requests/{started['id']}/cancellation", json={"version": started["version"]}, headers=as_employee(e))
    assert r.status_code == 409 and r.json()["error"]["message"] == "Leave that has started cannot be cancelled."


async def test_attachments_are_checked_stored_privately_and_downloadable_by_reviewers(client, db, org):
    manager, e = await team(client, org)
    lt = await leave_type(client, tracked=False, attach=1)
    mon = monday()
    est = (await _estimate(client, as_employee(e), lt, mon, mon + timedelta(days=2))).json()
    assert any("supporting document is expected" in w for w in est["warnings"]), "attachmentAfterDays is a warning (L15)"
    bad = await apply(client, as_employee(e), lt, mon, files=[("note.pdf", PNG, "application/pdf")])
    assert bad.status_code == 422 and "not a valid .pdf" in details(bad)["attachments"]
    exe = await apply(client, as_employee(e), lt, mon, files=[("tool.exe", b"MZ" + b"0" * 20, "application/octet-stream")])
    assert "only PDF, JPG and PNG" in details(exe)["attachments"]
    r = await apply(client, as_employee(e), lt, mon, mon + timedelta(days=2), files=[("medical.pdf", PDF, "application/pdf"), ("scan.png", PNG, "image/png")])
    assert r.status_code == 201, r.text
    req = r.json()
    assert [(a["fileName"], a["sizeBytes"]) for a in req["attachments"]] == [("medical.pdf", len(PDF)), ("scan.png", len(PNG))]
    url = f"{LEAVE}/requests/{req['id']}/attachments/{req['attachments'][0]['id']}/content"
    got = await client.get(url, headers=as_employee(manager, APPROVER))
    assert got.status_code == 200 and got.content == PDF and got.headers["cache-control"] == "no-store, private"
    outsider = await create(client, org, "EVR-4")
    assert (await client.get(url, headers=as_employee(outsider))).status_code == 404
    assert await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "leave_request.attachment_downloaded")) == 1
