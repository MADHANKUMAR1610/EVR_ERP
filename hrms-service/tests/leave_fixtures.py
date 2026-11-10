"""Shared setup for the leave tests (Module 6). Every leave type, policy, balance and holiday here is
test data entered through the HR setup API; nothing is pre-filled by the service."""

from datetime import date, timedelta

from app.services.employee_support import company_today
from tests.conftest import auth

LEAVE = "/api/v1/hr/leave"
SETUP = "/api/v1/hr/setup"
MANAGE = ["hr.leave-policies:manage", "hr.leave-policies:view"]
HR_LEAVE = ["hr.leave:view", "hr.leave:approve", "hr.leave:apply-on-behalf", "hr.leave-balances:view", "hr.leave-policies:view", "hr.approvals:view"]
APPROVER = ["hr.approvals:act", "hr.approvals:view"]
from tests.document_fixtures import PDF, PNG  # noqa: F401 - synthetic files, no real documents


def setup_headers(roles=("test-hr-all",)):
    return auth(MANAGE, roles=list(roles), name="Leave Admin")


def hr_leave(perms=None, roles=("test-hr-all",)):
    return auth(perms or HR_LEAVE, roles=list(roles), name="Hema HR")


def monday(weeks_ahead: int = 3) -> date:
    """A Monday at least `weeks_ahead` weeks from today (the template shifts work Monday-Saturday)."""
    d = company_today() + timedelta(days=7 * weeks_ahead)
    return d - timedelta(days=d.weekday())


async def leave_type(client, code="EL", name="Earned leave", *, paid=True, tracked=True, half=True, attach=None, active=True) -> dict:
    r = await client.post(f"{SETUP}/leave-types", json={"code": code, "name": name, "paid": paid, "allowHalfDay": half, "balanceTracked": tracked, "attachmentAfterDays": attach, "active": active},
                          headers=setup_headers())
    assert r.status_code == 201, r.text
    return r.json()


async def credit(client, employee: dict, lt: dict, days: float, year: int | None = None, kind="leave-allocations") -> dict:
    year = year or company_today().year
    r = await client.post(f"{SETUP}/{kind}", json={"employeeId": employee["id"], "leaveTypeId": lt["id"], "year": year, "days": days, "reason": "Opening balance (test)"}, headers=setup_headers())
    assert r.status_code == 201, r.text
    return r.json()


async def set_leave_policy(client, values: dict, effective: date | None = None) -> dict:
    headers = auth(["admin:policies.manage", "admin:policies.view"])
    current = (await client.get("/api/v1/admin/policies/leave", headers=headers)).json()
    body = {"values": {**current["values"], **values}, "effectiveFrom": (effective or company_today()).isoformat(), "version": current["version"]}
    r = await client.put("/api/v1/admin/policies/leave", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


async def apply(client, headers, lt: dict, start: date, end: date | None = None, *, portion="full", reason="Family function", employee_id=None, files=None):
    data = {"leaveTypeId": lt["id"], "from": start.isoformat(), "to": (end or start).isoformat(), "portion": portion, "reason": reason}
    if employee_id:
        data["employeeId"] = employee_id
    if files:
        return await client.post(f"{LEAVE}/requests", data=data, files=[("attachments", f) for f in files], headers=headers)
    # Multipart without files, as the frontend's FormData sends it.
    return await client.post(f"{LEAVE}/requests", files={k: (None, v) for k, v in data.items()}, headers=headers)


async def decide(client, headers, req: dict, decision="approve", **kw):
    return await client.post(f"{LEAVE}/requests/{req['id']}/decision", json={"decision": decision, "version": req["version"], **kw}, headers=headers)


def workflow_body(**over) -> dict:
    body = {
        "name": "Company leave routing", "status": "active", "scope": "company", "departmentIds": [], "firstApprover": "reporting_manager", "fallbackApprover": None,
        "escalation": {"enabled": False, "after": None, "unit": "hours", "reminderHoursBefore": None, "recipient": None},
        "notifications": {"onSubmit": True, "beforeDeadline": True, "onEscalation": True, "onDecision": True},
        "effectiveFrom": company_today().isoformat(), "effectiveTo": None,
    }
    body.update(over)
    return body


async def create_workflow(client, **over) -> dict:
    r = await client.post(f"{LEAVE}/approval-workflows", json=workflow_body(**over), headers=auth(["hr.leave-workflows:manage"], name="Workflow Admin"))
    assert r.status_code == 201, r.text
    return r.json()
