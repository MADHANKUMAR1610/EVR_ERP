"""Module 3: upload, download, list (contract B5): file checks, private encrypted storage, access, audit."""

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core import storage
from app.core.config import get_settings
from app.models.audit_log_model import AuditLog
from app.models.employee_document_model import EmployeeDocument
from app.models.employee_model import EmployeeHistory
from tests.conftest import auth
from tests.document_fixtures import DOCS, EXE, HTML, JPEG, PDF, PNG, files, upload
from tests.employee_fixtures import HR_ALL, HR_QA, create, details, hr, org  # noqa: F401

DOC_PERMS = ["hr.documents:view", "hr.documents:upload"]


def docs(perms=None, roles=None, **kw):
    return hr(perms if perms is not None else DOC_PERMS, roles=roles if roles is not None else [HR_ALL], **kw)


async def test_upload_returns_contract_shape_and_stores_encrypted(client, db, org):
    e = await create(client, org)
    r = await upload(client, e["id"], org.dtype["DT-OFR"], docs(), remarks="Signed copy", documentDate="2020-01-10")
    assert r.status_code == 201, r.text
    d = r.json()
    assert set(d) == {"id", "employeeId", "documentType", "fileName", "contentType", "sizeBytes", "remarks", "documentDate", "expiryDate", "uploadedAt", "uploadedBy", "previewable", "verification"}
    assert d["documentType"] == {"id": org.dtype["DT-OFR"], "name": "Offer letter"} and d["fileName"] == "offer.pdf" and d["contentType"] == "application/pdf"
    assert d["sizeBytes"] == len(PDF) and d["remarks"] == "Signed copy" and d["documentDate"] == "2020-01-10" and d["previewable"] is True and d["uploadedBy"] == "Asha HR"
    v = d["verification"]
    assert v["status"] == "pending" and v["reviewedBy"] is None and [(h["status"], h["by"], h["comment"]) for h in v["history"]] == [("pending", "Asha HR", "Uploaded")]
    row = await db.scalar(select(EmployeeDocument))
    raw = storage.raw_path(row.storage_key)
    assert str(raw).startswith(str(get_settings().storage_dir)) and raw.stat().st_mode & 0o077 == 0, "private file, owner-only"
    assert b"%PDF" not in raw.read_bytes(), "encrypted at rest"
    assert row.storage_key not in r.text and "storage" not in r.text.lower(), "no storage location or URL is ever returned"
    h = await db.scalar(select(EmployeeHistory).where(EmployeeHistory.action == "document_uploaded"))
    assert h.summary == "Document uploaded: Offer letter" and "offer.pdf" not in h.summary
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "document.uploaded")) is not None


async def test_download_returns_the_file_with_safe_headers_and_is_audited(client, db, org):
    e = await create(client, org)
    d = (await upload(client, e["id"], org.dtype["DT-IDP"], docs(), name="Aadhaar card ü.png", content=PNG)).json()
    assert d["contentType"] == "image/png" and d["fileName"] == "Aadhaar card ü.png"
    r = await client.get(f"{DOCS.format(eid=e['id'])}/{d['id']}/content", headers=docs(["hr.documents:view"]))
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png" and r.headers["x-content-type-options"] == "nosniff" and "no-store" in r.headers["cache-control"]
    assert r.headers["content-disposition"].startswith("attachment;") and "filename*=UTF-8''Aadhaar%20card%20%C3%BC.png" in r.headers["content-disposition"]
    assert "sandbox" in r.headers["content-security-policy"]
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "document.downloaded")) is not None


async def test_list_is_newest_first_and_audited(client, db, org):
    e = await create(client, org)
    await upload(client, e["id"], org.dtype["DT-OFR"], docs(), name="first.pdf")
    await upload(client, e["id"], org.dtype["DT-IDP"], docs(), name="second.jpg", content=JPEG)
    r = await client.get(DOCS.format(eid=e["id"]), headers=docs(["hr.documents:view"]))
    assert [x["fileName"] for x in r.json()] == ["second.jpg", "first.pdf"] and r.json()[0]["contentType"] == "image/jpeg"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "document.list_viewed")) is not None


@pytest.mark.parametrize(
    ("name", "content", "type_code", "message"),
    [
        ("tool.exe", EXE, "DT-IDP", "This document type accepts .jpeg, .jpg, .pdf, .png files."),
        ("letter.jpg", PDF, "DT-OFR", "This document type accepts .pdf files."),
        ("fake.pdf", HTML, "DT-OFR", "The file content is not a valid .pdf file."),
        ("renamed.pdf", EXE, "DT-OFR", "The file content is not a valid .pdf file."),
        ("photo.jpg", PNG, "DT-IDP", "The file content is not a valid .jpg file."),
        ("cut.pdf", PDF[:30], "DT-OFR", "The file content is not a valid .pdf file."),
        ("empty.pdf", b"", "DT-OFR", "The file is empty."),
        ("noextension", PDF, "DT-OFR", "This document type accepts .pdf files."),
    ],
)
async def test_invalid_files_are_refused_and_nothing_is_stored(client, db, org, name, content, type_code, message):
    e = await create(client, org)
    r = await upload(client, e["id"], org.dtype[type_code], docs(), name=name, content=content)
    assert r.status_code == 422 and details(r) == {"file": message}
    assert await db.scalar(select(EmployeeDocument)) is None


async def test_metadata_validation(client, db, org):
    e = await create(client, org)
    r = await upload(client, e["id"], org.dtype["DT-PASS"], docs(), documentDate="2020-13-01", remarks="x" * 201)
    assert details(r) == {"remarks": "Keep notes under 200 characters.", "documentDate": "Enter a valid date.", "expiryDate": "Enter the expiry date for the passport."}
    r = await upload(client, e["id"], org.dtype["DT-PASS"], docs(), documentDate="2024-01-01", expiryDate="2023-12-31")
    assert details(r) == {"expiryDate": "The expiry date must be after the document date."}
    r = await upload(client, e["id"], "00000000-0000-0000-0000-00000000abcd", docs())
    assert details(r) == {"documentTypeId": "Select an existing document type."}
    r = await client.post(DOCS.format(eid=e["id"]), data={}, headers=docs(), files={"other": ("a.txt", b"x")})
    assert r.status_code == 422 and details(r) == {"documentTypeId": "Select a document type.", "file": "Choose a file to upload."}
    manage = auth(["hr.settings:manage"])
    t = next(x for x in (await client.get("/api/v1/hr/setup/document-types", headers=manage)).json() if x["code"] == "DT-OTH")
    body = {k: t[k] for k in ("code", "name", "required", "expiryRequired", "allowedExtensions", "maxSizeBytes", "version")} | {"categoryId": t["category"]["id"], "active": False}
    assert (await client.put(f"/api/v1/hr/setup/document-types/{t['id']}", json=body, headers=manage)).status_code == 200
    r = await upload(client, e["id"], t["id"], docs())
    assert details(r) == {"documentTypeId": "This document type is no longer in use."}
    assert await db.scalar(select(EmployeeDocument)) is None


async def test_oversized_files_get_413(client, db, org):
    e = await create(client, org)
    big = PDF[:-7] + b" " * (2 * 1024 * 1024) + b"\n%%EOF\n"  # over the 2 MB limit of identity proof
    r = await upload(client, e["id"], org.dtype["DT-IDP"], docs(), name="big.pdf", content=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE" and details(r) == {"file": "The file is larger than allowed for this document type (2 MB)."}
    huge = b"%PDF-" + b" " * (get_settings().max_upload_bytes + 70 * 1024)
    r = await upload(client, e["id"], org.dtype["DT-OTH"], docs(), name="huge.pdf", content=huge)
    assert r.status_code == 413, "refused from Content-Length before the body is read"
    async def chunked():
        yield b"--x\r\n"

    r = await client.post(DOCS.format(eid=e["id"]), content=chunked(), headers={**docs(), "content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 411 and r.json()["error"]["code"] == "LENGTH_REQUIRED"
    assert await db.scalar(select(EmployeeDocument)) is None


async def test_unauthorized_and_missing(client, db, org):
    qa = await create(client, org, "EVR-1")
    hr_dept = await create(client, org, "EVR-2", dept="HR")
    d = (await upload(client, qa["id"], org.dtype["DT-OFR"], docs())).json()
    content = f"{DOCS.format(eid=qa['id'])}/{d['id']}/content"
    assert (await client.get(content)).status_code == 401
    no_view = docs(["hr.employees:view"], user_id="55555555-5555-5555-5555-555555555555")
    for path in (DOCS.format(eid=qa["id"]), content, f"/api/v1/hr/employees/{qa['id']}/document-checklist", "/api/v1/hr/document-compliance", "/api/v1/hr/document-compliance/summary"):
        assert (await client.get(path, headers=no_view)).status_code == 403, path
    assert await db.scalar(select(AuditLog).where(AuditLog.result == "denied", AuditLog.actor_user_id == "55555555-5555-5555-5555-555555555555")) is not None
    assert (await upload(client, qa["id"], org.dtype["DT-OFR"], docs(["hr.documents:view"]))).status_code == 403
    # Organizational scope: an HR user scoped to HR department cannot see or add QA documents.
    hr_scoped = docs(roles=["test-hr-hr"])
    from app.core.context import SYSTEM_PRINCIPAL
    from app.database.audit_listener import acting_as
    from app.models.employee_access_scope_model import EmployeeAccessScope
    import uuid as _uuid

    with acting_as(SYSTEM_PRINCIPAL):
        db.add(EmployeeAccessScope(role_code="test-hr-hr", scope_type="departments", department_ids=[_uuid.UUID(org.dept["HR"])]))
        await db.commit()
    assert (await client.get(DOCS.format(eid=qa["id"]), headers=hr_scoped)).status_code == 404
    assert (await client.get(content, headers=hr_scoped)).status_code == 404
    assert (await upload(client, qa["id"], org.dtype["DT-OFR"], hr_scoped)).status_code == 404
    assert (await client.get(DOCS.format(eid=hr_dept["id"]), headers=hr_scoped)).status_code == 200
    # A document is reachable only through its own employee; missing documents and employees are 404.
    assert (await client.get(f"{DOCS.format(eid=hr_dept['id'])}/{d['id']}/content", headers=docs())).status_code == 404
    assert (await client.get(f"{DOCS.format(eid=qa['id'])}/00000000-0000-0000-0000-00000000abcd/content", headers=docs())).status_code == 404
    assert (await client.get(f"{DOCS.format(eid=qa['id'])}/not-an-id/content", headers=docs())).status_code == 404
    assert (await client.get(DOCS.format(eid="00000000-0000-0000-0000-00000000abcd"), headers=docs())).status_code == 404
    assert (await upload(client, "00000000-0000-0000-0000-00000000abcd", org.dtype["DT-OFR"], docs())).status_code == 404


async def test_cookie_uploads_need_an_allowed_origin(client, org):
    from tests.conftest import ORIGIN, make_token

    e = await create(client, org)
    client.cookies.set("evr_session", make_token(DOC_PERMS, roles=[HR_ALL]))
    r = await client.post(DOCS.format(eid=e["id"]), data={"documentTypeId": org.dtype["DT-OFR"]}, files=files("a.pdf", PDF))
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_REJECTED"
    r = await client.post(DOCS.format(eid=e["id"]), data={"documentTypeId": org.dtype["DT-OFR"]}, files=files("a.pdf", PDF), headers={"Origin": ORIGIN})
    assert r.status_code == 201


async def test_tampered_or_missing_storage_is_refused(client, db, org):
    e = await create(client, org)
    d = (await upload(client, e["id"], org.dtype["DT-OFR"], docs())).json()
    row = await db.scalar(select(EmployeeDocument))
    path = storage.raw_path(row.storage_key)
    path.write_bytes(path.read_bytes()[:-5] + b"xxxxx")
    r = await client.get(f"{DOCS.format(eid=e['id'])}/{d['id']}/content", headers=docs())
    assert r.status_code == 503 and "%PDF" not in r.text
    path.unlink()
    assert (await client.get(f"{DOCS.format(eid=e['id'])}/{d['id']}/content", headers=docs())).status_code == 503


async def test_verification_history_is_append_only(client, db, org):
    e = await create(client, org)
    await upload(client, e["id"], org.dtype["DT-OFR"], docs())
    for sql in ("UPDATE employee_document_event SET comment = 'x'", "DELETE FROM employee_document_event"):
        nested = await db.begin_nested()
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(text(sql))
        await nested.rollback()


# --- Malware scanning (clamd protocol, with a local stand-in server) --------------------------------


@pytest.fixture
async def clamd(monkeypatch):
    """A tiny clamd stand-in: answers FOUND for content containing EICAR-TEST, OK otherwise."""

    async def handle(reader, writer):
        assert await reader.readexactly(10) == b"zINSTREAM\0"
        data = b""
        while True:
            size = int.from_bytes(await reader.readexactly(4), "big")
            if size == 0:
                break
            data += await reader.readexactly(size)
        writer.write(b"stream: Eicar-Test-Signature FOUND\0" if b"EICAR-TEST" in data else b"stream: OK\0")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    settings = get_settings()
    monkeypatch.setattr(settings, "malware_scanner", "clamav")
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", port)
    yield server
    server.close()
    await server.wait_closed()


async def test_malware_scan(client, db, org, clamd):
    e = await create(client, org)
    assert (await upload(client, e["id"], org.dtype["DT-OFR"], docs())).status_code == 201
    infected = PDF.replace(b"trailer", b"EICAR-TEST trailer")
    r = await upload(client, e["id"], org.dtype["DT-OFR"], docs(), name="bad.pdf", content=infected)
    assert r.status_code == 422 and details(r) == {"file": "The file was rejected by the virus scan."}
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "document.rejected_malware")) is not None
    assert len((await db.scalars(select(EmployeeDocument))).all()) == 1, "the infected file was not stored"


async def test_scanner_unavailable_fails_closed(client, db, org, monkeypatch):
    e = await create(client, org)
    settings = get_settings()
    monkeypatch.setattr(settings, "malware_scanner", "clamav")
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", 1)  # nothing listens there
    r = await upload(client, e["id"], org.dtype["DT-OFR"], docs())
    assert r.status_code == 503 and await db.scalar(select(EmployeeDocument)) is None


def test_production_requires_document_keys_and_a_scanner():
    from app.core.config import Settings

    base = dict(environment="production", auth_dev_mode=False, auth_jwt_public_key="k", allowed_origins=["https://erp.example.com"], docs_enabled=False,
                database_url="postgresql+asyncpg://x/y", payroll_encryption_keys=["k"])
    with pytest.raises(ValueError, match="DOCUMENT_ENCRYPTION_KEYS"):
        Settings(**base, document_encryption_keys=[], malware_scanner="clamav")
    with pytest.raises(ValueError, match="MALWARE_SCANNER"):
        Settings(**base, document_encryption_keys=["k"], malware_scanner="none")
