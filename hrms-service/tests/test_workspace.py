"""Module 10: HR workspace summary, the derived task queue (types by permission, counts, filters), activity and events."""

from datetime import timedelta

from app.core.config import get_settings
from app.services.employee_support import company_today
from tests.conftest import auth
from tests.employee_fixtures import create, org  # noqa: F401

HR = "/api/v1/hr"
ALL_TASKS = ["hr.dashboard:view", "hr.employees:view", "hr.employees:edit", "hr.documents:upload", "hr.employees:change-status"]


def hr(perms=ALL_TASKS, roles=("test-hr-all",)):
    return auth(list(perms), roles=list(roles), name="Workspace User")


async def test_task_queue_is_derived_and_filtered(client, org):
    today = company_today()
    # Template record: attendance policy missing -> an incomplete-record task (medium, no due date: joined in 2020).
    await create(client, org, "EVR-1")
    joiner = await create(client, org, "EVR-2", employment__joiningDate=(today - timedelta(days=3)).isoformat())
    await create(client, org, "EVR-3", employment__probation={"applicable": True, "endDate": (today + timedelta(days=5)).isoformat(), "confirmationDate": None})

    page = (await client.get(f"{HR}/tasks", params={"pageSize": 25}, headers=hr())).json()
    by = {(t["subject"]["employeeCode"], t["type"]): t for t in page["items"]}
    rec = by[("EVR-2", "employee_record_incomplete")]
    assert rec["priority"] == "high" and rec["dueDate"] == (today + timedelta(days=4)).isoformat() and rec["missingItems"] == ["Attendance policy"], "labels only, never values"
    assert by[("EVR-1", "employee_record_incomplete")]["dueDate"] is None
    assert by[("EVR-2", "onboarding_documents")]["dueDate"] == joiner["employment"]["joiningDate"]
    prob = by[("EVR-3", "probation_review_due")]
    assert prob["priority"] == "high" and "ends in 5 day(s)" in prob["description"]
    assert page["counts"] == {"total": 5, "overdue": 1, "highPriority": 2, "byType": {"employee_record_incomplete": 3, "probation_review_due": 1, "onboarding_documents": 1}}
    assert [t["dueDate"] for t in page["items"]][:3] == sorted(t["dueDate"] for t in page["items"] if t["dueDate"]), "earliest due first, undated last"

    one = (await client.get(f"{HR}/tasks", params={"pageSize": 1}, headers=hr())).json()
    assert len(one["items"]) == 1 and one["meta"]["totalItems"] == 5 and one["counts"]["total"] == 5
    overdue = (await client.get(f"{HR}/tasks", params={"due": "overdue"}, headers=hr())).json()
    assert [t["type"] for t in overdue["items"]] == ["onboarding_documents"] and overdue["counts"]["total"] == 5, "counts ignore filters"
    assert (await client.get(f"{HR}/tasks", params={"type": "probation_review_due"}, headers=hr())).json()["meta"]["totalItems"] == 1
    assert (await client.get(f"{HR}/tasks", params={"priority": "high", "due": "next7"}, headers=hr())).json()["meta"]["totalItems"] == 2

    # Each type only for users who can do the work.
    editors = (await client.get(f"{HR}/tasks", headers=hr(["hr.employees:edit"]))).json()
    assert set(editors["counts"]["byType"].values()) == {3, 0} and editors["counts"]["total"] == 3
    assert (await client.get(f"{HR}/tasks", headers=hr(["hr.dashboard:view"]))).json()["counts"]["total"] == 0
    assert (await client.get(f"{HR}/tasks", headers=auth(["hr.self:view"]))).status_code == 403


async def test_summary_activity_and_events(client, org, monkeypatch):
    today = company_today()
    await create(client, org, "EVR-1", employment__joiningDate=(today.replace(year=today.year - 3) + timedelta(days=10)).isoformat() if not (today.month == 2 and today.day == 29) else "2020-01-15")
    await create(client, org, "EVR-2", employment__joiningDate=(today + timedelta(days=12)).isoformat())

    summary = (await client.get(f"{HR}/workspace/summary", headers=hr(["hr.dashboard:view"]))).json()
    assert summary["totalEmployees"] == {"value": 2} or summary["totalEmployees"]["value"] == 2
    assert summary["activeEmployees"]["value"] is None and "WORKSPACE_ACTIVE_STATUS_CODES" in summary["activeEmployees"]["unavailableReason"], "never guessed"
    assert summary["presentToday"]["value"] is None and summary["pendingApprovals"]["value"] is None
    monkeypatch.setattr(get_settings(), "workspace_active_status_codes", ["active"])
    full = (await client.get(f"{HR}/workspace/summary", headers=hr(["hr.dashboard:view", "hr.attendance:view", "hr.approvals:view"]))).json()
    assert full["activeEmployees"]["value"] == 2 and full["presentToday"]["value"] == 0 and full["pendingApprovals"]["value"] == 0

    activity = (await client.get(f"{HR}/activity", params={"limit": 6}, headers=hr())).json()
    assert len(activity) == 2 and activity[0]["subject"]["employeeCode"] == "EVR-2" and activity[0]["action"] == "created"

    events = (await client.get(f"{HR}/upcoming-events", params={"days": 30}, headers=hr())).json()
    kinds = {(e["type"], e["subject"]["employeeCode"]) for e in events}
    assert ("joining", "EVR-2") in kinds
    anniversary = [e for e in events if e["type"] == "work_anniversary"]
    if not (today.month == 2 and today.day == 29):
        assert anniversary and anniversary[0]["years"] == 3 and anniversary[0]["subject"]["employeeCode"] == "EVR-1"
    assert events == sorted(events, key=lambda e: e["date"])
    assert (await client.get(f"{HR}/upcoming-events", params={"days": 365}, headers=hr())).status_code == 422
    qa_only = (await client.get(f"{HR}/activity", headers=hr(roles=("test-hr-qa",)))).json()
    assert len(qa_only) == 2  # both are QA employees (template department)
