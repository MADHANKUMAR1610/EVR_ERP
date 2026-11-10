"""Module 4: employee import (contract B6): fields, validation preview, jobs, duplicates, scope, audit."""

import uuid

import pytest
from sqlalchemy import func, select

from app.models.audit_log_model import AuditLog
from app.models.employee_model import Employee, EmployeeHistory
from app.models.import_job_model import EmployeeImportJob
from app.services.import_job_runner import claim_next_job, run_job
from tests.conftest import auth
from tests.employee_fixtures import HR_ALL, HR_QA, create, hr, org  # noqa: F401

BASE = "/api/v1/hr/employee-imports"
IMPORTER = ["hr.employees:import", "hr.employees:view-contact"]


def importer(perms=None, roles=None, **kw):
    return hr(perms or IMPORTER, roles=roles if roles is not None else [HR_ALL], name="Imran Importer", **kw)


def row(n: int, code: str, **values) -> dict:
    base = {"employeeCode": code, "personal.firstName": f"Person{n}", "employment.joiningDate": "15/01/2024", "employment.department": "QA",
            "employment.designation": "Engineer", "employment.employmentType": "PERM", "employment.status": "active"}
    return {"rowNumber": n, "values": {**base, **{k.replace("__", "."): v for k, v in values.items()}}}


async def run_all(db) -> None:
    """What the worker does: claim each queued job and run it."""
    while (job_id := await claim_next_job(db, "test-worker")) is not None:
        await run_job(db, job_id)


async def count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


# --- Fields --------------------------------------------------------------------------------------------


async def test_fields_follow_the_contract_and_the_callers_permissions(client, org):
    fields = (await client.get(f"{BASE}/fields", headers=importer())).json()
    keys = [f["key"] for f in fields]
    assert keys == ["employeeCode", "personal.firstName", "personal.middleName", "personal.lastName", "personal.dateOfBirth", "personal.mobile", "personal.email",
                    "employment.joiningDate", "employment.department", "employment.designation", "employment.employmentType", "employment.status",
                    "employment.workLocation", "employment.reportingManagerCode", "work.attendanceId"]
    required = {f["key"] for f in fields if f["required"]}
    assert required == {"employeeCode", "personal.firstName", "employment.joiningDate", "employment.department", "employment.designation", "employment.employmentType", "employment.status"}, "same as the employee form"
    dept = next(f for f in fields if f["key"] == "employment.department")
    assert dept == {"key": "employment.department", "label": "Department", "required": True, "type": "reference", "referenceType": "department", "aliases": ["dept"], "example": "Assembly", "unique": False}
    assert next(f for f in fields if f["key"] == "employment.status")["example"] == "On probation", "examples come from configuration"
    assert {f["key"] for f in fields if f.get("unique")} == {"employeeCode", "personal.email", "work.attendanceId"}
    no_contact = [f["key"] for f in (await client.get(f"{BASE}/fields", headers=importer(["hr.employees:import"]))).json()]
    assert "personal.mobile" not in no_contact and "personal.email" not in no_contact


# --- Validation preview ------------------------------------------------------------------------------


async def test_validate_reports_every_row_and_saves_nothing(client, db, org):
    await create(client, org, "EVR-1")  # existing employee, email evr-1@example.com, attendance ID 1
    rows = [
        row(2, "NEW-1", personal__email="new1@example.com", employment__reportingManagerCode="evr-1"),  # valid
        row(3, "NEW-2"),  # warning: no manager
        row(4, "evr-1"),  # duplicate code (case-insensitive)
        row(5, "NEW-3", personal__email="EVR-1@EXAMPLE.COM"),  # duplicate email
        row(6, "NEW-4", work__attendanceId="1"),  # duplicate attendance ID
        row(7, "NEW-1"),  # same code as row 2
        row(8, "NEW-5", employment__joiningDate="30/02/2024", personal__mobile="12", personal__email="nope", employment__department="Nowhere",
            employment__status="exited", employment__reportingManagerCode="X-9"),
        {"rowNumber": 9, "values": {"employeeCode": "NEW-6", "salary": "1"}},
    ]
    before = (await count(db, Employee), await count(db, AuditLog))
    r = await client.post(f"{BASE}/validate", json={"rows": rows}, headers=importer())
    assert r.status_code == 200, r.text
    res = {x["rowNumber"]: x for x in r.json()["rows"]}
    assert res[2]["status"] == "valid" and res[2]["messages"] == []
    assert res[3]["status"] == "warning" and res[3]["messages"] == [{"field": "employment.reportingManagerCode", "message": "No reporting manager given.", "severity": "warning"}]
    assert res[4]["status"] == "duplicate" and {"field": "employeeCode", "message": "Another employee uses this employee ID.", "severity": "error"} in res[4]["messages"]
    assert res[5]["status"] == "duplicate" and any(m["field"] == "personal.email" for m in res[5]["messages"])
    assert res[6]["status"] == "duplicate" and any(m["message"] == "Another employee uses this attendance ID." for m in res[6]["messages"])
    assert res[7]["status"] == "duplicate" and {"field": "employeeCode", "message": "Same employee id as row 2.", "severity": "error"} in res[7]["messages"]
    errors8 = {m["field"]: m["message"] for m in res[8]["messages"] if m["severity"] == "error"}
    assert res[8]["status"] == "error" and errors8 == {
        "employment.joiningDate": 'Joining date "30/02/2024" is not a valid date (use YYYY-MM-DD or DD/MM/YYYY).',
        "employment.department": 'Department "Nowhere" does not match any department.',
        "employment.reportingManagerCode": 'No existing employee has the Employee ID "X-9".',
        "personal.mobile": "Enter a valid contact number (7–15 digits).",
        "personal.email": "Enter a valid email address.",
        "employment.status": "This status cannot be used for a new employee.",
    }
    errors9 = {m["field"]: m["message"] for m in res[9]["messages"] if m["severity"] == "error"}
    assert errors9["salary"] == '"salary" is not an import column.' and errors9["personal.firstName"] == "First name is required."
    assert errors9["employment.department"] == "Department is required."
    assert r.json()["summary"] == {"total": 8, "valid": 1, "warning": 1, "duplicate": 4, "error": 2}
    assert (await count(db, Employee), await count(db, AuditLog)) == before, "validation must not persist anything"


async def test_references_match_code_or_name_case_insensitively(client, org):
    rows = [row(2, "A-1", employment__department="quality assurance", employment__designation="eng", employment__employmentType="Permanent", employment__status="On Probation",
                employment__workLocation="main plant")]
    res = (await client.post(f"{BASE}/validate", json={"rows": rows}, headers=importer())).json()["rows"][0]
    assert res["status"] == "warning", res


async def test_contact_columns_need_view_contact(client, org):
    rows = [row(2, "A-1", personal__email="a@example.com")]
    res = (await client.post(f"{BASE}/validate", json={"rows": rows}, headers=importer(["hr.employees:import"]))).json()["rows"][0]
    assert res["status"] == "error" and {"field": "personal.email", "message": "You do not have permission to import contact details.", "severity": "error"} in res["messages"]


async def test_rows_outside_the_callers_scope_are_refused(client, org):
    rows = [row(2, "A-1", employment__department="HR"), row(3, "A-2", employment__department="QA")]
    res = {x["rowNumber"]: x for x in (await client.post(f"{BASE}/validate", json={"rows": rows}, headers=importer(roles=[HR_QA]))).json()["rows"]}
    assert res[2]["status"] == "error" and any("organizational scope" in m["message"] for m in res[2]["messages"])
    assert res[3]["status"] == "warning"
    res = (await client.post(f"{BASE}/validate", json={"rows": rows}, headers=importer(roles=[]))).json()["rows"]
    assert all(r["status"] == "error" for r in res), "no scope assignment: nothing can be imported"


async def test_request_limits(client, org, monkeypatch):
    from app.core.config import get_settings

    assert (await client.post(f"{BASE}/validate", json={"rows": []}, headers=importer())).status_code == 422
    assert (await client.post(f"{BASE}/validate", json={"rows": [row(2, "A"), row(2, "B")]}, headers=importer())).status_code == 422
    monkeypatch.setattr(get_settings(), "import_max_rows", 3)
    r = await client.post(f"{BASE}/validate", json={"rows": [row(n, f"A-{n}") for n in range(2, 6)]}, headers=importer())
    assert r.status_code == 422 and r.json()["error"]["details"] == [{"field": "rows", "message": "At most 3 rows can be imported at once."}]
    assert (await client.post(f"{BASE}/validate", json={"rows": [{"rowNumber": 2, "values": {"employeeCode": "x" * 501}}]}, headers=importer())).status_code == 422


# --- Jobs ----------------------------------------------------------------------------------------------


async def test_import_job_creates_valid_rows_and_reports_the_rest(client, db, org):
    await create(client, org, "EVR-1")
    rows = [row(2, "NEW-1", personal__email="n1@example.com"), row(3, "EVR-1"), row(4, "NEW-2", employment__department="Nowhere"), row(5, "NEW-3", employment__reportingManagerCode="EVR-1")]
    r = await client.post(BASE, json={"rows": rows, "skipDuplicates": True}, headers=importer())
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "queued" and job["progress"] == {"processed": 0, "total": 4} and job["summary"] is None and job["failures"] == [] and job["finishedAt"] is None
    assert await count(db, Employee) == 1, "nothing is imported until the worker runs"
    await run_all(db)
    done = (await client.get(f"{BASE}/{job['id']}", headers=importer())).json()
    assert done["status"] == "succeeded" and done["progress"] == {"processed": 4, "total": 4} and done["error"] is None and done["finishedAt"]
    assert done["summary"] == {"created": 2, "skipped": 1, "failed": 1}
    assert done["failures"] == [
        {"rowNumber": 3, "messages": ["Skipped: Another employee uses this employee ID."]},
        {"rowNumber": 4, "messages": ['Department "Nowhere" does not match any department.']},
    ]
    new = await db.scalar(select(Employee).where(Employee.employee_code == "NEW-3"))
    assert new.created_by_name == "Imran Importer" and new.reporting_manager_id is not None
    h = await db.scalar(select(EmployeeHistory).where(EmployeeHistory.employee_id == new.id))
    assert h.action == "imported" and h.comment == f"Import job {job['id']}"
    actions = set((await db.scalars(select(AuditLog.action).where(AuditLog.action.like("employee%import%")))).all())
    assert {"employee_import.started", "employee_import.completed", "employee.imported"} <= actions
    stored = await db.get(EmployeeImportJob, uuid.UUID(job["id"]))
    assert stored.rows is None, "submitted rows (personal data) are cleared when the job finishes"


async def test_duplicates_fail_when_not_skipped_and_rows_are_rechecked_at_import_time(client, db, org):
    r = await client.post(BASE, json={"rows": [row(2, "LATE-1"), row(3, "LATE-2")], "skipDuplicates": False}, headers=importer())
    await create(client, org, "LATE-1")  # created by someone else after the preview
    await run_all(db)
    done = (await client.get(f"{BASE}/{r.json()['id']}", headers=importer())).json()
    assert done["summary"] == {"created": 1, "skipped": 0, "failed": 1}
    assert done["failures"] == [{"rowNumber": 2, "messages": ["Another employee uses this employee ID."]}]


async def test_jobs_are_visible_to_their_owner_only(client, org):
    job = (await client.post(BASE, json={"rows": [row(2, "A-1")]}, headers=importer())).json()
    assert (await client.get(f"{BASE}/{job['id']}", headers=importer(user_id="66666666-6666-6666-6666-666666666666"))).status_code == 404
    assert (await client.get(f"{BASE}/{job['id']}", headers=importer())).status_code == 200
    assert (await client.get(f"{BASE}/not-a-job", headers=importer())).status_code == 404


async def test_import_endpoints_need_the_import_permission(client, db, org):
    job = (await client.post(BASE, json={"rows": [row(2, "A-1")]}, headers=importer())).json()
    other = hr(["hr.employees:view", "hr.employees:create"], roles=[HR_ALL], user_id="77777777-7777-7777-7777-777777777777")
    for method, path, body in (("GET", f"{BASE}/fields", None), ("POST", f"{BASE}/validate", {"rows": [row(2, "A")]}), ("POST", BASE, {"rows": [row(2, "A")]}),
                               ("GET", f"{BASE}/{job['id']}", None), ("GET", f"{BASE}/template", None), ("GET", f"{BASE}/{job['id']}/failures.csv", None)):
        r = await client.request(method, path, json=body, headers=other)
        assert r.status_code == 403, path
        assert (await client.request(method, path, json=body)).status_code == 401, path
    assert await db.scalar(select(AuditLog).where(AuditLog.result == "denied", AuditLog.actor_user_id == "77777777-7777-7777-7777-777777777777")) is not None


async def test_failure_report_csv_neutralises_formulas(client, db, org):
    job = (await client.post(BASE, json={"rows": [row(2, "A-1", employment__department="=HYPERLINK(1)")]}, headers=importer())).json()
    await run_all(db)
    r = await client.get(f"{BASE}/{job['id']}/failures.csv", headers=importer())
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0] == "Row,Messages" and "2," in text and "=HYPERLINK" in text
    assert ",=" not in text and ",\"=" not in text, "no cell starts with a formula"


# --- Partial failure, resume, concurrency -----------------------------------------------------------------


async def test_unexpected_stop_is_reported_with_what_was_created(client, db, org, monkeypatch):
    from app.core.config import get_settings
    from app.services import import_job_runner

    monkeypatch.setattr(get_settings(), "import_batch_size", 2)
    original = import_job_runner._import_row
    calls = {"n": 0}

    async def flaky(session, job, checker, refs, r, failures):
        calls["n"] += 1
        if calls["n"] == 4:
            raise RuntimeError("worker lost the database")
        return await original(session, job, checker, refs, r, failures)

    monkeypatch.setattr(import_job_runner, "_import_row", flaky)
    job = (await client.post(BASE, json={"rows": [row(n, f"P-{n}") for n in range(2, 7)]}, headers=importer())).json()
    await run_all(db)
    done = (await client.get(f"{BASE}/{job['id']}", headers=importer())).json()
    assert done["status"] == "failed" and done["summary"] == {"created": 2, "skipped": 0, "failed": 0} and done["progress"] == {"processed": 2, "total": 5}
    assert done["error"] == "The import stopped unexpectedly after 2 of 5 rows. 2 employee(s) were created and are kept; the remaining 3 row(s) were not imported. Import them again in a new file."
    assert await count(db, Employee) == 2, "the committed batch stays; the interrupted batch was rolled back"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "employee_import.failed")) is not None


async def test_a_stale_job_is_resumed_after_its_last_committed_batch(client, db, org, monkeypatch):
    from datetime import timedelta

    from app.core.context import SYSTEM_PRINCIPAL
    from app.database.audit_listener import acting_as
    from app.database.base import utcnow

    job = (await client.post(BASE, json={"rows": [row(n, f"R-{n}") for n in range(2, 6)]}, headers=importer())).json()
    job_id = await claim_next_job(db, "worker-a")
    assert await claim_next_job(db, "worker-b") is None, "a running job with a fresh heartbeat is not taken"
    stored = await db.get(EmployeeImportJob, job_id)
    with acting_as(SYSTEM_PRINCIPAL):  # worker-a imported row 2 and committed, then died
        await create(client, org, "R-2")
        stored.processed, stored.created_count, stored.heartbeat_at = 1, 1, utcnow() - timedelta(hours=1)
        await db.commit()
    assert await claim_next_job(db, "worker-b") == job_id
    await run_job(db, job_id)
    done = (await client.get(f"{BASE}/{job['id']}", headers=importer())).json()
    assert done["status"] == "succeeded" and done["summary"] == {"created": 4, "skipped": 0, "failed": 0}, "row 2 was not imported twice"
    assert await count(db, Employee) == 4


async def test_database_constraint_race_fails_only_that_row(client, db, org, monkeypatch):
    from app.repositories.employee_repository import EmployeeRepository

    await create(client, org, "RACE-1")

    async def never_taken(self, code, exclude_id):
        return False  # as if another import saved the same code between the check and the insert

    monkeypatch.setattr(EmployeeRepository, "code_taken", never_taken)
    job = (await client.post(BASE, json={"rows": [row(2, "race-1"), row(3, "RACE-2")]}, headers=importer())).json()
    await run_all(db)
    done = (await client.get(f"{BASE}/{job['id']}", headers=importer())).json()
    assert done["summary"] == {"created": 1, "skipped": 0, "failed": 1}
    assert done["failures"][0]["rowNumber"] == 2 and "was saved while this import was running" in done["failures"][0]["messages"][0]
