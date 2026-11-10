"""Module 3: checklist and completion across employees (contract B5, rules proposed in D23)."""

from datetime import timedelta

from sqlalchemy import select

from app.core.context import SYSTEM_PRINCIPAL
from app.database.audit_listener import acting_as
from app.models.employee_document_model import EmployeeDocument, EmployeeDocumentEvent
from app.services.employee_support import company_today
from tests.conftest import auth
from tests.document_fixtures import JPEG, PDF, upload
from tests.employee_fixtures import HR_QA, create, details, hr, org  # noqa: F401

VIEW = ["hr.documents:view", "hr.documents:upload"]
REQUIRED = ("DT-IDP", "DT-ADP", "DT-EDU", "DT-OFR", "DT-APT", "DT-BANK")  # template, pending HR


def docs(perms=None, roles=None):
    return hr(perms or VIEW, roles=roles)


async def decide(db, document_id: str, status: str, comment: str | None = None):
    """Stands in for the verification step, whose endpoint is not specified yet (contract D24)."""
    with acting_as(SYSTEM_PRINCIPAL):
        d = await db.get(EmployeeDocument, __import__("uuid").UUID(document_id))
        d.verification_status = status
        db.add(EmployeeDocumentEvent(document_id=d.id, status=status, comment=comment))
        await db.commit()


async def test_checklist_states_counts_and_order(client, db, org):
    e = await create(client, org)
    eid = e["id"]
    for code in ("DT-IDP", "DT-ADP", "DT-EDU", "DT-OFR"):
        await upload(client, eid, org.dtype[code], docs(), name="d.pdf")
    rejected = (await upload(client, eid, org.dtype["DT-APT"], docs(), name="d.pdf")).json()
    await decide(db, rejected["id"], "rejected", "Unsigned copy")
    verified = (await upload(client, eid, org.dtype["DT-IDP"], docs(), name="newer.jpg", content=JPEG)).json()
    await decide(db, verified["id"], "verified")
    today = company_today()
    await upload(client, eid, org.dtype["DT-PASS"], docs(), name="p.pdf", documentDate=(today - timedelta(days=3650)).isoformat(), expiryDate=(today + timedelta(days=10)).isoformat())
    await upload(client, eid, org.dtype["DT-MED"], docs(), name="m.pdf", documentDate=(today - timedelta(days=400)).isoformat(), expiryDate=(today - timedelta(days=1)).isoformat())

    c = (await client.get(f"/api/v1/hr/employees/{eid}/document-checklist", headers=docs())).json()
    assert set(c) == {"employeeId", "expiryWindowDays", "requiredCount", "completedCount", "verifiedCount", "awaitingVerificationCount", "expiringSoonCount", "status", "items"}
    assert c["expiryWindowDays"] == 30 and c["requiredCount"] == 6
    assert (c["completedCount"], c["verifiedCount"], c["awaitingVerificationCount"], c["expiringSoonCount"], c["status"]) == (4, 1, 3, 1, "documents_pending")
    states = {i["documentType"]["name"]: i["state"] for i in c["items"]}
    assert states["Identity proof"] == "verified", "the latest copy decides"
    assert states["Appointment letter"] == "rejected" and states["Bank account proof"] == "missing"
    assert states["Passport"] == "pending_verification" and states["Medical fitness certificate"] == "expired"
    assert [i["documentType"]["required"] for i in c["items"]] == [True] * 6 + [False] * 4, "required first"
    item = next(i for i in c["items"] if i["documentType"]["name"] == "Passport")
    assert item["expiresInDays"] == 10 and item["document"]["fileName"] == "p.pdf" and item["documentType"]["expiryRequired"] is True
    assert set(item["documentType"]) == {"id", "name", "category", "required", "expiryRequired"}
    appointment = next(i for i in c["items"] if i["documentType"]["name"] == "Appointment letter")
    v = appointment["document"]["verification"]
    assert v["reviewedBy"] == "system" and v["comment"] == "Unsigned copy" and [h["status"] for h in v["history"]] == ["pending", "rejected"]


async def test_compliance_list_summary_and_attention_are_scoped(client, db, org):
    a = await create(client, org, "EVR-1")  # QA
    b = await create(client, org, "EVR-2", dept="HR")
    gone = await create(client, org, "EVR-3")
    for code in REQUIRED:
        await upload(client, a["id"], org.dtype[code], docs(), name="x.pdf")
    await upload(client, b["id"], org.dtype["DT-IDP"], docs(), name="x.pdf")
    await client.post(f"/api/v1/hr/employees/{gone['id']}/status-changes", json={"toStatus": "exited", "effectiveDate": "2026-11-01", "version": gone["version"]}, headers=hr())

    r = (await client.get("/api/v1/hr/document-compliance", params={"sort": "completion:desc"}, headers=docs())).json()
    rows = {x["employee"]["employeeCode"]: x for x in r["items"]}
    assert list(rows) == ["EVR-1", "EVR-2"], "employees whose status is marked employmentEnded are excluded (D23, pending)"
    assert rows["EVR-1"]["status"] == "awaiting_verification" and rows["EVR-1"]["completedCount"] == 6 and rows["EVR-1"]["pendingDocuments"] == []
    assert rows["EVR-2"]["status"] == "documents_pending" and [p["name"] for p in rows["EVR-2"]["pendingDocuments"]] == ["Bank account proof", "Educational certificate", "Appointment letter", "Offer letter", "Address proof"]
    assert set(rows["EVR-2"]["employee"]) == {"id", "employeeCode", "fullName", "department", "designation"}
    q = lambda **p: client.get("/api/v1/hr/document-compliance", params=p, headers=docs())  # noqa: E731
    assert [x["employee"]["employeeCode"] for x in (await q(status="documents_pending")).json()["items"]] == ["EVR-2"]
    assert [x["employee"]["employeeCode"] for x in (await q(departmentId=org.dept["HR"])).json()["items"]] == ["EVR-2"]
    assert [x["requiredCount"] for x in (await q(categoryId=org.dcat["DC-ID"])).json()["items"]] == [2, 2], "counts limited to one category"
    assert (await q(verification="verified")).json()["items"] == []
    assert (await q(sort="salary:asc")).status_code == 400 and (await q(status="unknown")).status_code == 422

    scoped = (await client.get("/api/v1/hr/document-compliance", headers=docs(roles=[HR_QA]))).json()
    assert [x["employee"]["employeeCode"] for x in scoped["items"]] == ["EVR-1"]
    assert (await client.get("/api/v1/hr/document-compliance", headers=docs(roles=[]))).json()["items"] == []

    s = (await client.get("/api/v1/hr/document-compliance/summary", headers=docs())).json()
    assert {k: s[k] for k in s if k != "asOf"} == {
        "requiredDocumentsTotal": 12, "requiredDocumentsProvided": 7, "missingRequiredDocuments": 5, "employeesComplete": 0, "employeesWithPendingDocuments": 1,
        "documentsAwaitingVerification": 7, "documentsExpiringSoon": 0, "expiryWindowDays": 30,
    }
    att = (await client.get("/api/v1/hr/document-compliance/attention", params={"limit": 2}, headers=docs())).json()
    assert att["awaitingVerification"]["total"] == 7 and len(att["awaitingVerification"]["items"]) == 2
    assert att["missingRequired"]["total"] == 1 and att["missingRequired"]["items"][0]["employee"]["employeeCode"] == "EVR-2"
    assert att["expiringSoon"] == {"total": 0, "items": []}
    assert (await client.get("/api/v1/hr/document-compliance/attention", params={"limit": 50}, headers=docs())).status_code == 422


async def test_expiry_window_is_hr_configuration(client, org):
    e = await create(client, org)
    today = company_today()
    await upload(client, e["id"], org.dtype["DT-PASS"], docs(), name="p.pdf", expiryDate=(today + timedelta(days=45)).isoformat())
    assert (await client.get(f"/api/v1/hr/employees/{e['id']}/document-checklist", headers=docs())).json()["expiringSoonCount"] == 0
    manage = auth(["hr.settings:manage"])
    s = (await client.get("/api/v1/hr/setup/document-settings", headers=auth(["hr.settings:view"]))).json()
    assert s["expiryWindowDays"] == 30 and s["version"] == 1
    assert (await client.put("/api/v1/hr/setup/document-settings", json={"expiryWindowDays": 60}, headers=auth(["hr.settings:view"]))).status_code == 403
    assert (await client.put("/api/v1/hr/setup/document-settings", json={"expiryWindowDays": 0}, headers=manage)).status_code == 422
    r = await client.put("/api/v1/hr/setup/document-settings", json={"expiryWindowDays": 60, "version": 1}, headers=manage)
    assert r.status_code == 200 and r.json()["version"] == 2
    assert (await client.put("/api/v1/hr/setup/document-settings", json={"expiryWindowDays": 90, "version": 1}, headers=manage)).status_code == 409
    c = (await client.get(f"/api/v1/hr/employees/{e['id']}/document-checklist", headers=docs())).json()
    assert c["expiryWindowDays"] == 60 and c["expiringSoonCount"] == 1


async def test_document_types_only_allow_formats_the_service_can_verify(client, org):
    manage = auth(["hr.settings:manage"])
    body = {"code": "DT-CV", "name": "Curriculum vitae", "categoryId": org.dcat["DC-EMP"], "allowedExtensions": [".docx"], "maxSizeBytes": 1024}
    r = await client.post("/api/v1/hr/setup/document-types", json=body, headers=manage)
    assert details(r) == {"allowedExtensions": "Supported file types: .jpeg, .jpg, .pdf, .png."}
    r = await client.post("/api/v1/hr/setup/document-types", json={**body, "allowedExtensions": [".pdf"], "maxSizeBytes": 50 * 1024 * 1024}, headers=manage)
    assert "maxSizeBytes" in details(r)
    assert (await client.post("/api/v1/hr/setup/document-types", json={**body, "allowedExtensions": [".pdf"]}, headers=manage)).status_code == 201


async def test_no_document_endpoint_returns_a_storage_location(client, db, org):
    e = await create(client, org)
    await upload(client, e["id"], org.dtype["DT-OFR"], docs())
    row = await db.scalar(select(EmployeeDocument))
    for path in (f"/api/v1/hr/employees/{e['id']}/documents", f"/api/v1/hr/employees/{e['id']}/document-checklist", "/api/v1/hr/document-compliance", "/api/v1/hr/document-compliance/attention"):
        body = (await client.get(path, headers=docs())).text
        assert row.storage_key not in body and row.sha256 not in body and "http" not in body, path
