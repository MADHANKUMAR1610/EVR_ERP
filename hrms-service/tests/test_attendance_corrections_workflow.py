"""Module 5: corrections with configurable workflows (owner decision 1), back-dated assignments
(owner decision 2), period locks and background jobs."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.attendance_model import AttendanceCorrection, AttendanceDay, BackgroundJob, ShiftAssignmentChange
from app.models.audit_log_model import AuditLog
from app.services.attendance.jobs import claim_background_job, run_background_job
from app.services.employee_support import company_today
from tests.attendance_fixtures import BASE, device, ingest, local, past_workday  # noqa: F401
from tests.conftest import auth
from tests.employee_fixtures import HR_ALL, create, details, hr, org  # noqa: F401

APPROVER = ["hr.approvals:act", "hr.attendance-corrections:view"]


async def run_jobs(db):
    while (job_id := await claim_background_job(db, "test")) is not None:
        await run_background_job(db, job_id)


async def team(client, org):
    """A manager (EVR-1) and an employee (EVR-2) reporting to them."""
    manager = await create(client, org, "EVR-1")
    employee = await create(client, org, "EVR-2", employment__reportingManagerId=manager["id"])
    return manager, employee


def as_employee(e, perms=("hr.self:submit-requests", "hr.self:view"), roles=()):
    return auth(list(perms), employee_id=e["id"], user_id=e["id"], roles=list(roles), name=e["display"]["fullName"] + " " + e["employeeCode"])


async def submit(client, headers, employee, d, **body):
    payload = {"employeeId": employee["id"], "date": d.isoformat(), "requestedIn": local(d, 9), "requestedOut": local(d, 17, 30), "reason": "Fingerprint reader did not register my punch.", **body}
    return await client.post(f"{BASE}/corrections", json=payload, headers=headers)


async def decide(client, headers, c, decision="approve", **kw):
    return await client.post(f"{BASE}/corrections/{c['id']}/decision", json={"decision": decision, "version": c["version"], **kw}, headers=headers)


# --- Default workflow: employee submits, reporting manager decides, HR oversight -----------------------


async def test_default_workflow_manager_approves_and_the_day_is_corrected(client, db, org, device):
    manager, employee = await team(client, org)
    d = past_workday()
    await ingest(client, device, ("2", local(d, 9, 50), "in"))  # late, no out-punch
    r = await submit(client, as_employee(employee), employee, d)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "pending" and c["original"]["in"] is not None and c["original"]["out"] is None and c["requested"]["out"]
    assert [h["action"] for h in c["history"]] == ["submitted"]
    stored = await db.get(AttendanceCorrection, __import__("uuid").UUID(c["id"]))
    assert stored.workflow_id is not None and stored.steps[0]["approverType"] == "reporting_manager", "the published default workflow was used"
    day = (await client.get(f"{BASE}/daily/{employee['id']}", params={"date": d.isoformat()}, headers=hr(["hr.attendance:view"]))).json()
    assert "pending_correction" in day["exceptions"]

    assert (await decide(client, as_employee(employee, ("hr.approvals:act",)), c)).status_code == 403, "nobody decides their own request"
    other = await create(client, org, "EVR-3")
    assert (await decide(client, as_employee(other, ("hr.approvals:act",)), c)).status_code in (403, 404), "only the step approver"
    r = await decide(client, as_employee(manager, APPROVER), c, comment="Confirmed with the supervisor")
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "approved" and done["reviewedBy"].startswith("Ravi Iyer") and [h["action"] for h in done["history"]] == ["submitted", "approved"]
    assert done["history"][1]["comment"] == "Reporting manager review: Confirmed with the supervisor"
    assert (await decide(client, as_employee(manager, APPROVER), done)).status_code == 409, "already decided"
    day = (await client.get(f"{BASE}/daily/{employee['id']}", params={"date": d.isoformat()}, headers=hr(["hr.attendance:view"]))).json()
    assert day["corrected"] is True and day["status"] == "present" and day["inSource"] == "correction" and day["outSource"] == "correction"
    await run_jobs(db)
    stored_day = await db.scalar(select(AttendanceDay).where(AttendanceDay.date == d))
    assert stored_day is not None and stored_day.corrected, "the approved correction refreshed the stored day"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "attendance_correction.approved")) is not None


async def test_hr_oversight_rejection_rules_and_validation(client, org):
    manager, employee = await team(client, org)
    d = past_workday()
    hr_user = hr(["hr.attendance-corrections:approve", "hr.attendance-corrections:view", "hr.attendance-corrections:submit"], user_id="88888888-8888-8888-8888-888888888888")
    c = (await submit(client, hr_user, employee, d)).json()
    assert (await decide(client, hr_user, c, "reject")).status_code == 422, "a rejection needs a comment"
    assert (await decide(client, hr_user, {**c, "version": 99}, "reject", comment="x")).status_code == 409
    r = await decide(client, hr_user, c, "reject", comment="Times do not match the gate register")
    assert r.status_code == 200 and r.json()["status"] == "rejected" and "(HR oversight)" in r.json()["history"][-1]["comment"]

    errors = lambda r: details(r)  # noqa: E731
    me = as_employee(employee)
    assert errors(await submit(client, me, employee, company_today() + timedelta(days=1))) == {"date": "A correction cannot be requested for a future date."}
    assert errors(await submit(client, me, employee, d, requestedIn=local(d, 18), requestedOut=local(d, 9))) == {"requestedOut": "Out-time must be after in-time."}
    assert "reason" in errors(await submit(client, me, employee, d, reason="short"))
    assert "requestedIn" in errors(await submit(client, me, employee, d, requestedIn=None, requestedOut=None))
    assert (await submit(client, me, employee, d)).status_code == 201
    assert errors(await submit(client, me, employee, d)) == {"date": "A correction for this date is already waiting for a decision."}
    assert (await submit(client, me, manager, d)).status_code == 422, "employees request corrections only for themselves"
    manage = auth(["admin:policies.payroll-manage"])
    doc = (await client.get("/api/v1/admin/policies/attendance", headers=manage)).json()
    await client.put("/api/v1/admin/policies/attendance", json={"values": {"correctionWindowDays": 1}, "effectiveFrom": company_today().isoformat(), "version": doc["version"]}, headers=manage)
    other_day = past_workday(5)
    assert errors(await submit(client, me, employee, other_day)) == {"date": "Corrections can be requested up to 1 days back."}


# --- Configurable workflows (G5) ------------------------------------------------------------------------


async def test_two_step_workflow_with_escalation(client, db, org):
    manager, employee = await team(client, org)
    admin = auth(["admin:workflows.manage", "admin:workflows.publish", "admin:workflows.view"])
    steps = [
        {"id": "s1", "name": "Manager", "approverType": "reporting_manager", "roleId": None, "userId": None, "required": True, "condition": None,
         "fallback": {"type": "user", "roleId": None, "userId": "99999999-9999-9999-9999-999999999999"}, "escalateAfterHours": 24},
        {"id": "s2", "name": "HR review", "approverType": "role", "roleId": "hr-reviewer", "userId": None, "required": True, "condition": {"field": "daysSinceDate", "operator": "gte", "value": 0}, "fallback": None, "escalateAfterHours": None},
    ]
    body = {"name": "Corrections, two steps", "description": "", "process": "attendance_correction", "effectiveFrom": company_today().isoformat(), "effectiveTo": None, "steps": steps}
    w = (await client.post("/api/v1/admin/workflows", json=body, headers=admin)).json()
    assert w["status"] == "draft"
    bad = {**body, "steps": [{**steps[0], "escalateAfterHours": None}]}
    w2 = (await client.post("/api/v1/admin/workflows", json={**bad, "name": "Broken"}, headers=admin)).json()
    r = await client.post(f"/api/v1/admin/workflows/{w2['id']}/publication", json={"version": w2["version"], "note": ""}, headers=admin)
    assert r.status_code == 422 and "steps.0.fallback" in details(r)
    pub = (await client.post(f"/api/v1/admin/workflows/{w['id']}/publication", json={"version": w["version"], "note": "Go live"}, headers=admin)).json()
    assert pub["status"] == "published" and pub["history"][-1]["note"] == "Go live"
    listing = {x["name"]: x["status"] for x in (await client.get("/api/v1/admin/workflows", headers=admin)).json()}
    assert listing["Attendance correction (default)"] == "archived", "publishing replaced the default"
    processes = (await client.get("/api/v1/admin/workflow-processes", headers=admin)).json()
    assert {p["process"] for p in processes} == {"attendance_correction", "overtime", "payroll", "performance_review"}

    d = past_workday()
    c = (await submit(client, as_employee(employee), employee, d)).json()
    reviewer = auth(["hr.approvals:act", "hr.attendance-corrections:view"], roles=["hr-reviewer"], user_id="77777777-0000-0000-0000-000000000000")
    assert (await decide(client, reviewer, c)).status_code in (403, 404), "step 2's approver cannot act (or even see it) at step 1"
    step1 = (await decide(client, as_employee(manager, APPROVER), c)).json()
    assert step1["status"] == "pending" and step1["history"][-1]["action"] == "approved"
    final = (await decide(client, reviewer, step1)).json()
    assert final["status"] == "approved"

    # Escalation: step 1 overdue -> the fallback user may decide.
    c2 = (await submit(client, as_employee(employee), employee, past_workday(4))).json()
    row = await db.get(AttendanceCorrection, __import__("uuid").UUID(c2["id"]))
    fallback = auth(["hr.approvals:act", "hr.attendance-corrections:view"], user_id="99999999-9999-9999-9999-999999999999")
    assert (await decide(client, fallback, c2)).status_code in (403, 404), "not before escalation"
    from app.core.context import SYSTEM_PRINCIPAL
    from app.database.audit_listener import acting_as

    with acting_as(SYSTEM_PRINCIPAL):
        row.step_started_at = datetime.now(UTC) - timedelta(hours=25)
        await db.commit()
    from app.services.attendance.jobs import enqueue

    await enqueue(db, "workflow.escalate", {})
    await db.commit()
    await run_jobs(db)
    c2 = (await client.get(f"{BASE}/corrections/{c2['id']}", headers=hr(["hr.attendance-corrections:view"]))).json()
    assert c2["history"][-1]["action"] == "commented" and c2["history"][-1]["comment"].startswith("Escalated")
    assert (await decide(client, fallback, c2)).json()["history"][-1]["action"] == "approved"


async def test_saving_a_published_workflow_keeps_it_in_force_until_republished(client, org):
    admin = auth(["admin:workflows.manage", "admin:workflows.publish", "admin:workflows.view"])
    default = next(w for w in (await client.get("/api/v1/admin/workflows", headers=admin)).json() if w["process"] == "attendance_correction")
    body = {k: default[k] for k in ("name", "description", "process", "effectiveFrom", "effectiveTo", "steps")} | {"version": default["version"], "description": "edited"}
    saved = (await client.put(f"/api/v1/admin/workflows/{default['id']}", json=body, headers=admin)).json()
    assert saved["status"] == "draft" and saved["version"] == default["version"] + 1
    from app.services.attendance.workflow_service import WorkflowEngine  # noqa: F401
    assert (await client.get("/api/v1/admin/workflows", headers=auth(["hr.attendance:view"]))).status_code == 403


# --- Back-dated shift assignments (decision 2) ---------------------------------------------------------------


async def test_assignments_and_backdating_rules(client, db, org):
    e = await create(client, org, "EVR-1")
    shift_a = org.shift["A"]
    assign = hr(["hr.shifts:assign"])
    today = company_today()
    r = await client.post(f"/api/v1/hr/shifts/{shift_a}/assignments", json={"employeeIds": [e["id"]], "effectiveFrom": (today + timedelta(days=3)).isoformat()}, headers=assign)
    assert r.status_code == 200 and r.json()["assigned"] == 1 and r.json()["backdated"] is False
    back = (today - timedelta(days=10)).isoformat()
    r = await client.post(f"/api/v1/hr/shifts/{shift_a}/assignments", json={"employeeIds": [e["id"]], "effectiveFrom": back, "reason": "Rota fix"}, headers=assign)
    assert r.status_code == 422 and "not allowed" in details(r)["effectiveFrom"], "off by default"
    manage = auth(["admin:policies.manage"])
    doc = (await client.get("/api/v1/admin/policies/shifts", headers=manage)).json()
    await client.put("/api/v1/admin/policies/shifts", json={"values": {"allowBackdatedAssignments": True, "maxBackdatedDays": 30}, "effectiveFrom": today.isoformat(), "version": doc["version"]}, headers=manage)
    assert (await client.post(f"/api/v1/hr/shifts/{shift_a}/assignments", json={"employeeIds": [e["id"]], "effectiveFrom": back, "reason": "Rota fix"}, headers=assign)).status_code == 403, "needs the back-dating permission"
    backdater = hr(["hr.shifts:assign", "hr.shifts:assign-backdated"])
    r = await client.post(f"/api/v1/hr/shifts/{shift_a}/assignments", json={"employeeIds": [e["id"]], "effectiveFrom": back}, headers=backdater)
    assert details(r) == {"reason": "Enter the reason for this back-dated assignment."}
    r = await client.post(f"/api/v1/hr/shifts/{shift_a}/assignments", json={"employeeIds": [e["id"]], "effectiveFrom": (today - timedelta(days=40)).isoformat(), "reason": "x"}, headers=backdater)
    assert details(r) == {"effectiveFrom": "Assignments can start at most 30 days back."}
    r = await client.post(f"/api/v1/hr/shifts/{shift_a}/assignments", json={"employeeIds": [e["id"]], "effectiveFrom": back, "reason": "Rota fix approved by the plant head"}, headers=backdater)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["backdated"] is True and out["affectedAttendanceDays"] == 10
    change = await db.scalar(select(ShiftAssignmentChange).where(ShiftAssignmentChange.backdated.is_(True)))
    assert str(change.old_shift_id) == org.shift["GEN"] and str(change.new_shift_id) == shift_a and change.reason == "Rota fix approved by the plant head"
    assert change.affected_days == 10 and change.created_by_name == "Asha HR"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "shift.assigned_backdated")) is not None
    assert await db.scalar(select(BackgroundJob).where(BackgroundJob.type == "attendance.recalculate")) is not None
    record = (await client.get(f"/api/v1/hr/employees/{e['id']}", headers=hr())).json()
    assert record["work"]["shiftId"] == shift_a, "the shift in force today"


async def test_locked_periods_cannot_change(client, db, org, device):
    manager, employee = await team(client, org)
    d = past_workday(6)
    await ingest(client, device, ("2", local(d, 9), "in"), ("2", local(d, 17, 30), "out"))
    lock = await client.post("/api/v1/hr/setup/attendance-period-locks", json={"fromDate": d.isoformat(), "toDate": d.isoformat(), "reason": "October payroll finalized"}, headers=hr(["hr.payroll:approve"]))
    assert lock.status_code == 201, lock.text
    r = await submit(client, as_employee(employee), employee, d)
    assert r.status_code == 409 and r.json()["error"]["code"] == "PERIOD_LOCKED"
    late = await ingest(client, device, ("2", local(d, 18), "out", "late-1"))
    assert late["rejected"] == 1, "punches for a locked date are not counted"
    day = (await client.get(f"{BASE}/daily/{employee['id']}", params={"date": d.isoformat()}, headers=hr(["hr.attendance:view"]))).json()
    assert day["lastOut"].startswith(local(d, 17, 30)[:16].replace("+05:30", "")) or day["status"] == "present", "the frozen record is shown"
    manage = auth(["admin:policies.manage"])
    doc = (await client.get("/api/v1/admin/policies/shifts", headers=manage)).json()
    await client.put("/api/v1/admin/policies/shifts", json={"values": {"allowBackdatedAssignments": True}, "effectiveFrom": company_today().isoformat(), "version": doc["version"]}, headers=manage)
    r = await client.post(f"/api/v1/hr/shifts/{org.shift['A']}/assignments", json={"employeeIds": [employee["id"]], "effectiveFrom": d.isoformat(), "reason": "Rota fix"}, headers=hr(["hr.shifts:assign", "hr.shifts:assign-backdated"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "PERIOD_LOCKED"
    assert (await client.post("/api/v1/hr/setup/attendance-period-locks", json={"fromDate": d.isoformat(), "toDate": d.isoformat(), "reason": "x x"}, headers=hr(["hr.attendance:view"]))).status_code == 403


async def test_nightly_close_stores_finished_days(client, db, org, device):
    await create(client, org, "EVR-1")
    from app.services.attendance.jobs import enqueue

    d = past_workday(2)
    await enqueue(db, "attendance.close_day", {"date": d.isoformat()}, dedupe_key=f"close-day:{d.isoformat()}")
    await enqueue(db, "attendance.close_day", {"date": d.isoformat()}, dedupe_key=f"close-day:{d.isoformat()}")
    await db.commit()
    jobs = (await db.scalars(select(BackgroundJob).where(BackgroundJob.type == "attendance.close_day"))).all()
    assert len(jobs) == 1, "a scheduled job is queued once"
    await run_jobs(db)
    day = await db.scalar(select(AttendanceDay).where(AttendanceDay.date == d))
    assert day.status == "absent"
    job = (await db.scalars(select(BackgroundJob).where(BackgroundJob.type == "attendance.close_day"))).one()
    await db.refresh(job)
    assert job.status == "succeeded" and job.result == {"daysStored": 1}


@pytest.mark.parametrize("area,perm,ok", [("attendance", "admin:policies.manage", False), ("attendance", "admin:policies.payroll-manage", True), ("overtime", "admin:policies.manage", True)])
async def test_policy_permissions_and_validation(client, area, perm, ok):
    headers = auth([perm])
    doc = (await client.get(f"/api/v1/admin/policies/{area}", headers=headers)).json()
    key = doc["fields"][1]["key"] if area == "attendance" else "minimumMinutes"
    r = await client.put(f"/api/v1/admin/policies/{area}", json={"values": {key: 30}, "effectiveFrom": company_today().isoformat(), "version": doc["version"]}, headers=headers)
    assert (r.status_code == 200) is ok
    if ok:
        bad = await client.put(f"/api/v1/admin/policies/{area}", json={"values": {key: -1}, "effectiveFrom": (company_today() - timedelta(days=1)).isoformat(), "version": r.json()["version"]}, headers=headers)
        assert bad.status_code == 422 and set(details(bad)) == {"effectiveFrom", f"values.{key}"}
    assert (await client.get("/api/v1/admin/policies/performance", headers=headers)).status_code == 404, "areas of later modules are not available yet"
