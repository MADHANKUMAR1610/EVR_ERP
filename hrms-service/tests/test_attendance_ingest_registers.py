"""Module 5: device ingestion, events, registers, summary, calendar, export and access."""

from datetime import timedelta

from sqlalchemy import select

from app.models.attendance_model import AttendanceEvent
from app.models.audit_log_model import AuditLog
from app.services.employee_support import company_today
from tests.attendance_fixtures import ATT, BASE, device, ingest, local, past_workday  # noqa: F401
from tests.conftest import auth
from tests.employee_fixtures import HR_ALL, HR_QA, create, details, hr, org  # noqa: F401


def att(perms=None, roles=None, **kw):
    return hr(perms or ATT, roles=roles if roles is not None else [HR_ALL], **kw)


async def test_ingest_classifies_punches_and_is_idempotent(client, db, org, device):
    e = await create(client, org, "EVR-1001")  # attendance ID "1001", shift GEN
    d = past_workday()
    r = await ingest(client, device, ("1001", local(d, 9, 2), "in", "log-1"), ("1001", local(d, 17, 40), "out", "log-2"), ("9999", local(d, 9), "in", "log-3"))
    assert (r["accepted"], r["rejected"], r["alreadyReceived"], r["result"]) == (2, 1, 0, "partial")
    again = await ingest(client, device, ("1001", local(d, 9, 2), "in", "log-1"))
    assert again["alreadyReceived"] == 1 and again["accepted"] == 0, "a resend is recognised and stored once"
    unknown = await db.scalar(select(AttendanceEvent).where(AttendanceEvent.reported_attendance_id == "9999"))
    assert unknown.processing_status == "rejected" and unknown.exception == "Unknown attendance ID." and unknown.warnings == ["rejected_event"]
    future = await ingest(client, device, ("1001", local(company_today() + timedelta(days=2), 9), "in", "log-4"))
    assert future["rejected"] == 1
    before_joining = await ingest(client, device, ("1001", local(e and __import__("datetime").date(2019, 1, 7), 9), "in", "log-5"))
    assert before_joining["rejected"] == 1
    assert (await client.post(f"{BASE}/events/ingest", json={"events": []}, headers={"X-Device-Key": device["key"]})).status_code == 422
    assert (await client.post(f"{BASE}/events/ingest", json={"events": [{"attendanceId": "1", "at": "2026-01-01T09:00:00", "direction": "in"}]}, headers={"X-Device-Key": device["key"]})).status_code == 422, "an offset is required"
    assert (await client.post(f"{BASE}/events/ingest", json={"events": []}, headers={"X-Device-Key": "wrong"})).status_code == 401
    assert (await client.post(f"{BASE}/events/ingest", json={"events": []}, headers=att())).status_code == 401, "user tokens cannot ingest"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "attendance_device.synced")) is not None


async def test_duplicate_and_delayed_rules_need_hr_settings(client, org, device):
    await create(client, org, "EVR-1001")
    d = past_workday(4)
    first = await ingest(client, device, ("1001", local(d, 9), "in", "a"), ("1001", local(d, 9, 0) .replace(":00+", ":40+", 1), "in", "b"))
    assert first["duplicates"] == 0, "no duplicate window set: only exact resends are duplicates"
    manage = auth(["admin:policies.payroll-manage"])
    doc = (await client.get("/api/v1/admin/policies/attendance", headers=manage)).json()
    assert all(v is None for v in doc["values"].values()), "every setting starts empty"
    r = await client.put("/api/v1/admin/policies/attendance", json={"values": {"duplicateWindowSeconds": 120, "delayedSyncMinutes": 60}, "effectiveFrom": company_today().isoformat(), "version": doc["version"]}, headers=manage)
    assert r.status_code == 200, r.text
    second = await ingest(client, device, ("1001", local(d, 17, 30), "out", "c"), ("1001", local(d, 17, 31), "out", "d"))
    assert second["duplicates"] == 1 and second["accepted"] == 1
    events = (await client.get(f"{BASE}/events", params={"date": d.isoformat()}, headers=att())).json()["items"]
    dup = next(x for x in events if x["processingStatus"] == "duplicate")
    assert dup["warnings"] == ["duplicate_event", "delayed_sync"] and dup["originalEventId"] and dup["syncStatus"] == "delayed"
    assert dup["location"] == "Main Plant" and dup["deviceName"] == "Gate 1" and dup["mobileValidation"] is None
    detail = (await client.get(f"{BASE}/events/{dup['id']}", headers=att())).json()
    assert detail["record"]["status"] in ("present", "late")


async def test_daily_register_detail_and_summary(client, org, device):
    a = await create(client, org, "EVR-1001")
    b = await create(client, org, "EVR-1002")  # absent
    c = await create(client, org, "EVR-1003", dept="HR")  # late, only an in-punch (missing out)
    d = past_workday()
    await ingest(client, device, ("1001", local(d, 9, 5), "in"), ("1001", local(d, 17, 45), "out"), ("1003", local(d, 9, 40), "in"))
    page = (await client.get(f"{BASE}/daily", params={"date": d.isoformat(), "sort": "employee:asc"}, headers=att())).json()
    rows = {r["employee"]["employeeCode"]: r for r in page["items"]}
    assert rows["EVR-1001"]["status"] == "present" and rows["EVR-1001"]["workedMinutes"] == 520 and rows["EVR-1001"]["inSource"] == "fingerprint"
    assert rows["EVR-1002"]["status"] == "absent" and rows["EVR-1002"]["exceptions"] == ["absent"]
    assert rows["EVR-1003"]["status"] == "missing_punch" and rows["EVR-1003"]["exceptions"][0] == "missing_out" and "late_arrival" in rows["EVR-1003"]["exceptions"]
    assert set(rows["EVR-1001"]) >= {"id", "employee", "date", "shift", "status", "firstIn", "lastOut", "workedMinutes", "lateMinutes", "earlyExitMinutes", "overtimeMinutes", "exceptions", "corrected"}
    filtered = (await client.get(f"{BASE}/daily", params={"date": d.isoformat(), "exceptionsOnly": "true"}, headers=att())).json()
    assert {r["employee"]["employeeCode"] for r in filtered["items"]} == {"EVR-1002", "EVR-1003"}
    assert (await client.get(f"{BASE}/daily", params={"date": d.isoformat(), "sort": "salary:asc"}, headers=att())).status_code == 400
    assert (await client.get(f"{BASE}/daily", params={"date": (company_today() + timedelta(days=1)).isoformat()}, headers=att())).status_code == 422
    detail = (await client.get(f"{BASE}/daily/{a['id']}", params={"date": d.isoformat()}, headers=att())).json()
    assert [p["direction"] for p in detail["punches"]] == ["in", "out"] and detail["punches"][0]["deviceName"] == "Gate 1" and len(detail["events"]) == 2
    s = (await client.get(f"{BASE}/summary", params={"date": d.isoformat()}, headers=att())).json()
    assert (s["activeEmployees"], s["present"], s["absent"], s["late"], s["missingPunches"]) == (3, 2, 1, 0, 1)
    assert [x["employee"]["employeeCode"] for x in s["exceptions"]] == ["EVR-1003", "EVR-1002"], "most serious first"
    assert {x["department"]["name"]: x["expected"] for x in s["byDepartment"]} == {"Human Resources": 1, "Quality Assurance": 2}
    scoped = (await client.get(f"{BASE}/daily", params={"date": d.isoformat()}, headers=att(roles=[HR_QA]))).json()
    assert {r["employee"]["employeeCode"] for r in scoped["items"]} == {"EVR-1001", "EVR-1002"}, "organizational scope"


async def test_monthly_calendar_export_and_access(client, org, device):
    a = await create(client, org, "EVR-1001")
    other = await create(client, org, "EVR-1002", dept="HR")
    d = past_workday()
    await ingest(client, device, ("1001", local(d, 9), "in"), ("1001", local(d, 17, 30), "out"))
    month = d.strftime("%Y-%m")
    row = next(r for r in (await client.get(f"{BASE}/monthly", params={"month": month}, headers=att())).json()["items"] if r["employee"]["id"] == a["id"])
    assert row["present"] >= 1 and row["workedMinutes"] >= 510 and row["leave"] == 0
    detail = (await client.get(f"{BASE}/monthly/{a['id']}", params={"month": month}, headers=att())).json()
    assert any(x["date"] == d.isoformat() and x["status"] == "present" for x in detail["days"])
    cal = (await client.get(f"{BASE}/employees/{a['id']}/calendar", params={"month": month}, headers=att())).json()
    assert cal["employee"]["designation"] == "Engineer" and cal["summary"]["presentDays"] >= 1 and cal["summary"]["approvedLeaveDays"] == 0
    assert all(x["date"] <= company_today().isoformat() for x in cal["days"]), "no future dates"
    future = (company_today().replace(day=1) + timedelta(days=40)).strftime("%Y-%m")
    assert (await client.get(f"{BASE}/employees/{a['id']}/calendar", params={"month": future}, headers=att())).status_code == 422
    assert (await client.get(f"{BASE}/employees/{other['id']}/calendar", params={"month": month}, headers=att(roles=[HR_QA]))).status_code == 403, "H1: outside scope is 403"
    own = auth(["hr.self:view"], employee_id=a["id"])
    assert (await client.get(f"{BASE}/employees/{a['id']}/calendar", params={"month": month}, headers=own)).status_code == 200, "own record"
    assert (await client.get(f"{BASE}/employees/{other['id']}/calendar", params={"month": month}, headers=own)).status_code == 403
    csv = await client.get(f"{BASE}/monthly/export", params={"month": month}, headers=att())
    assert csv.status_code == 200 and "attendance-" in csv.headers["content-disposition"] and "EVR-1001" in csv.content.decode("utf-8-sig")
    xlsx = await client.get(f"{BASE}/monthly/export", params={"month": month, "format": "xlsx"}, headers=att())
    assert xlsx.content[:2] == b"PK"
    for path in ("/summary", "/daily", "/monthly", "/events", "/monthly/export"):
        assert (await client.get(f"{BASE}{path}", params={"date": d.isoformat(), "month": month}, headers=hr(["hr.employees:view"]))).status_code == 403, path


async def test_devices_list_and_sync_history(client, org, device):
    await create(client, org, "EVR-1001")
    assert (await client.get("/api/v1/hr/attendance-devices", headers=att(["hr.devices:view"]))).json()["items"][0]["connection"] == "not_connected"
    await ingest(client, device, ("1001", local(past_workday(), 9), "in"))
    listing = (await client.get("/api/v1/hr/attendance-devices", headers=att(["hr.devices:view"]))).json()
    item = listing["items"][0]
    assert listing["integrationConfigured"] is True and item["connection"] == "online" and item["location"] == "Main Plant" and item["recordsLastSync"] == 1
    runs = (await client.get(f"/api/v1/hr/attendance-devices/{device['id']}/sync-history", headers=att(["hr.devices:view"]))).json()
    assert runs[0]["result"] == "success" and runs[0]["eventsReceived"] == 1
    assert (await client.get("/api/v1/hr/attendance-devices", headers=att())).status_code == 403
    setup = (await client.get("/api/v1/hr/setup/attendance-devices", headers=auth(["hr.devices:manage"]))).json()
    assert setup[0]["keyIssued"] is True and "apiKey" not in setup[0] and "keyHash" not in str(setup)
