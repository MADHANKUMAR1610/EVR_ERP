"""Module 6: leave approval workflows (H3), routing fixed at submission (owner decision 1),
escalation where both the original approver and the recipient may act (decision 2), reminders and
notifications through the outbox."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.context import SYSTEM_PRINCIPAL
from app.database.audit_listener import acting_as
from app.models.audit_log_model import AuditLog
from app.models.leave_model import LeaveRequest, NotificationOutbox
from app.services.leave.calendar import LeaveCalendar
from app.services.leave.notifications import deliver_pending
from app.services.leave.request_service import escalate_leave
from tests.conftest import auth
from tests.employee_fixtures import create, details, org  # noqa: F401
from tests.leave_fixtures import APPROVER, LEAVE, apply, create_workflow, decide, leave_type, monday, workflow_body
from tests.test_attendance_corrections_workflow import as_employee, team

WF = auth(["hr.leave-workflows:manage"], name="Workflow Admin")
ESC_ROLE = "test-hr-escalation"


async def test_workflow_validation_conflicts_history_and_options(client, org):
    bad = workflow_body(name="X", scope="departments", departmentIds=[], effectiveFrom="", escalation={"enabled": True, "after": 800, "unit": "hours", "reminderHoursBefore": 900, "recipient": None})
    r = await client.post(f"{LEAVE}/approval-workflows", json=bad, headers=WF)
    assert r.status_code == 422 and details(r) == {
        "name": "Enter a name of at least 3 characters.", "departmentIds": "Choose at least one department.", "effectiveFrom": "Enter the date the workflow takes effect.",
        "after": "Use at most 720 hours.", "recipient": "Choose who receives escalated requests.", "reminderHoursBefore": "The reminder must come before the deadline.",
    }
    wd = await client.post(f"{LEAVE}/approval-workflows", json=workflow_body(escalation={"enabled": True, "after": 2, "unit": "working_days", "reminderHoursBefore": None, "recipient": {"type": "role", "id": ESC_ROLE, "name": "HR desk"}}), headers=WF)
    assert wd.status_code == 422 and "working days are not configured" in details(wd)["unit"], "L18: nothing is guessed"
    assert (await client.post(f"{LEAVE}/approval-workflows", json=workflow_body(), headers=auth(["hr.leave-policies:view"]))).status_code == 403
    w = await create_workflow(client)
    assert w["history"][0]["action"] == "created" and w["version"] == 1 and w["status"] == "active"
    clash = await client.post(f"{LEAVE}/approval-workflows", json=workflow_body(name="Second default"), headers=WF)
    assert clash.status_code == 422 and details(clash)["scope"] == 'Conflicts with active workflow "Company leave routing" for the same scope and period.'
    dept = await client.post(f"{LEAVE}/approval-workflows", json=workflow_body(name="QA routing", scope="departments", departmentIds=[org.dept["QA"]], firstApprover="department_head"), headers=WF)
    assert dept.status_code == 201, "a department workflow does not conflict with the company default"
    off = await client.put(f"{LEAVE}/approval-workflows/{w['id']}", json={**workflow_body(status="inactive"), "version": w["version"]}, headers=WF)
    assert off.status_code == 200 and [h["action"] for h in off.json()["history"]] == ["created", "deactivated"]
    stale = await client.put(f"{LEAVE}/approval-workflows/{w['id']}", json={**workflow_body(), "version": w["version"]}, headers=WF)
    assert stale.status_code == 409
    opts = (await client.get(f"{LEAVE}/approval-workflows/options", headers=auth(["hr.leave-policies:view"]))).json()
    assert opts["workingDays"] == [] and any(r["id"] == "test-hr-all" for r in opts["roles"])
    listed = (await client.get(f"{LEAVE}/approval-workflows", headers=auth(["hr.leave-policies:view"]))).json()
    by_name = {x["name"]: x for x in listed}
    assert set(by_name) == {"Company leave routing", "QA routing"} and by_name["QA routing"]["departments"][0]["id"] == org.dept["QA"]


async def test_routing_department_first_fallback_and_no_rerouting(client, db, org):
    manager, e = await team(client, org)
    loner = await create(client, org, "EVR-5", dept="ENG")  # no reporting manager
    lt = await leave_type(client, tracked=False)
    w = await create_workflow(client, fallbackApprover={"type": "role", "id": "test-hr-all", "name": "HR team"},
                              escalation={"enabled": True, "after": 24, "unit": "hours", "reminderHoursBefore": 4, "recipient": {"type": "role", "id": ESC_ROLE, "name": "HR desk"}})
    req = (await apply(client, as_employee(e), lt, monday())).json()
    a = req["approval"]
    assert a["workflow"] == {"id": w["id"], "name": "Company leave routing"} and a["currentApprover"]["type"] == "reporting_manager" and a["escalation"] == "on_track"
    due = datetime.fromisoformat(a["escalationDueAt"].replace("Z", "+00:00"))
    assert timedelta(hours=23) < due - datetime.now(UTC) <= timedelta(hours=24)
    fb = (await apply(client, as_employee(loner), lt, monday())).json()
    assert fb["approval"]["currentApprover"] == {"type": "role", "name": "HR team"} and "fallback" in fb["approval"]["events"][0]["detail"]

    # Decision 1: changing or deactivating the workflow does not re-route existing requests.
    await client.put(f"{LEAVE}/approval-workflows/{w['id']}", json={**workflow_body(status="inactive", firstApprover="department_head"), "version": w["version"]}, headers=WF)
    again = (await client.get(f"{LEAVE}/requests/{req['id']}", headers=as_employee(e))).json()
    assert again["approval"]["currentApprover"] == a["currentApprover"] and again["approval"]["escalationDueAt"] == a["escalationDueAt"] and again["approval"]["workflow"]["id"] == w["id"]
    new = (await apply(client, as_employee(e), lt, monday(4))).json()
    assert new["approval"]["workflow"] is None and "no leave approval workflow is active" in new["approval"]["events"][0]["detail"]
    # The fallback role decides with hr.approvals:act.
    role_user = auth(APPROVER, roles=["test-hr-all"], name="Role Approver", user_id=str(uuid.uuid4()))
    assert (await decide(client, role_user, fb)).status_code == 200


async def test_escalation_reminder_both_may_act_first_wins(client, db, org):
    manager, e = await team(client, org)
    lt = await leave_type(client, tracked=False)
    await create_workflow(client, escalation={"enabled": True, "after": 8, "unit": "hours", "reminderHoursBefore": 2, "recipient": {"type": "role", "id": ESC_ROLE, "name": "HR desk"}})
    req = (await apply(client, as_employee(e), lt, monday())).json()
    second = (await apply(client, as_employee(e), lt, monday(4))).json()
    outbox = (await db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.created_at))).all()
    assert [n.category for n in outbox] == ["leave.submitted", "leave.submitted"] and outbox[0].employee_ids == [uuid.UUID(manager["id"])]
    recipient = auth(APPROVER, roles=[ESC_ROLE], name="Escalation Desk", user_id=str(uuid.uuid4()))
    assert (await decide(client, recipient, req)).status_code == 404, "the recipient cannot act before escalation"

    for rid, shift in ((req["id"], 7), (second["id"], 9)):  # move time forward: the first is due for a reminder, the second overdue
        r = await db.get(LeaveRequest, uuid.UUID(rid))
        with acting_as(SYSTEM_PRINCIPAL):
            r.escalation_due_at -= timedelta(hours=shift)
            r.reminder_at -= timedelta(hours=shift)
            await db.commit()
    with acting_as(SYSTEM_PRINCIPAL):
        result = await escalate_leave(db)
    assert result == {"reminders": 1, "escalated": 1}
    with acting_as(SYSTEM_PRINCIPAL):
        assert await escalate_leave(db) == {"reminders": 0, "escalated": 0}, "idempotent"
    first = (await client.get(f"{LEAVE}/requests/{req['id']}", headers=as_employee(e))).json()
    assert first["approval"]["escalation"] == "due_soon" and [x["action"] for x in first["approval"]["events"]] == ["assigned", "reminder_sent"]
    esc = (await client.get(f"{LEAVE}/requests/{second['id']}", headers=as_employee(e))).json()
    assert esc["approval"]["stage"] == "escalated" and esc["approval"]["escalation"] == "escalated" and esc["approval"]["currentApprover"] == {"type": "role", "name": "HR desk"}
    assert esc["approval"]["escalationDueAt"] is None and esc["approval"]["escalatedAt"] and esc["approval"]["events"][-1]["action"] == "escalated"
    categories = [n.category for n in (await db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.created_at))).all()]
    assert categories.count("leave.reminder") == 1 and categories.count("leave.escalated") == 2, "to the recipient and to the original approver"
    role_note = await db.scalar(select(NotificationOutbox).where(NotificationOutbox.category == "leave.escalated", NotificationOutbox.role_codes.any(ESC_ROLE)))
    assert role_note is not None

    # Decision 2: both the original approver and the recipient may act; the first valid decision wins.
    listed = (await client.get(f"{LEAVE}/requests", params={"awaitingMe": "true", "escalated": "true"}, headers=recipient)).json()
    assert [x["id"] for x in listed["items"]] == [second["id"]]
    assert (await client.get(f"{LEAVE}/requests", params={"awaitingMe": "true"}, headers=as_employee(manager, APPROVER))).json()["meta"]["totalItems"] == 2
    ok = await decide(client, recipient, esc, comment="Approved by HR desk")
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    late = await decide(client, as_employee(manager, APPROVER), esc)
    assert late.status_code == 409 and late.json()["error"]["code"] == "INVALID_TRANSITION"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "leave_request.escalated")) is not None
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "leave_request.reminder_sent")) is not None


async def test_working_day_deadlines_skip_offs_and_holidays(client, db, org, monkeypatch):
    monkeypatch.setattr(get_settings(), "company_working_days", [1, 2, 3, 4, 5])
    friday = monday() + timedelta(days=4)
    start = datetime.combine(friday, datetime.min.time(), UTC).replace(hour=10)
    calendar = LeaveCalendar(db)
    assert (await calendar.deadline(start, 1, "working_days", None)).date() == friday + timedelta(days=3), "Friday + 1 working day = Monday"
    await client.post("/api/v1/hr/setup/holidays", json={"date": (friday + timedelta(days=3)).isoformat(), "name": "Holiday", "type": "company"},
                      headers=auth(["hr.leave-policies:manage"]))
    assert (await calendar.deadline(start, 1, "working_days", None)).date() == friday + timedelta(days=4), "the holiday is skipped"
    assert await calendar.deadline(start, 30, "hours", None) == start + timedelta(hours=30)
    opts = (await client.get(f"{LEAVE}/approval-workflows/options", headers=auth(["hr.leave-policies:view"]))).json()
    assert opts["workingDays"] == [1, 2, 3, 4, 5]
    ok = await client.post(f"{LEAVE}/approval-workflows", json=workflow_body(escalation={"enabled": True, "after": 2, "unit": "working_days", "reminderHoursBefore": None, "recipient": {"type": "user", "id": "u-1", "name": "Hari"}}), headers=WF)
    assert ok.status_code == 201


async def test_notifications_stay_queued_until_configured_and_retry(client, db, org, monkeypatch):
    manager, e = await team(client, org)
    lt = await leave_type(client, tracked=False)
    await create_workflow(client)
    await apply(client, as_employee(e), lt, monday())
    with acting_as(SYSTEM_PRINCIPAL):
        assert (await deliver_pending(db))["skipped"] == "delivery not configured"
    status = (await client.get("/api/v1/hr/setup/notification-outbox", headers=auth(["hr.leave-policies:manage"]))).json()
    assert status["deliveryConfigured"] is False and status["pending"] == 1

    settings = get_settings()
    monkeypatch.setattr(settings, "platform_notifications_url", "https://platform.test/internal/notifications")
    monkeypatch.setattr(settings, "platform_service_token", "test-token-not-a-secret")
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 201)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with acting_as(SYSTEM_PRINCIPAL):
            assert await deliver_pending(db, http) == {"delivered": 0, "failed": 0}
            n = await db.scalar(select(NotificationOutbox))
            assert n.attempts == 1 and n.last_error == "RuntimeError: HTTP 503" and n.next_attempt_at > datetime.now(UTC)
            n.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()
            assert await deliver_pending(db, http) == {"delivered": 1, "failed": 0}
    body = json.loads(calls[-1].content)
    assert calls[-1].headers["authorization"] == "Bearer test-token-not-a-secret" and body["employeeIds"] == [manager["id"]] and body["category"] == "leave.submitted"
    status = (await client.get("/api/v1/hr/setup/notification-outbox", headers=auth(["hr.leave-policies:manage"]))).json()
    assert status["delivered"] == 1 and status["pending"] == 0
