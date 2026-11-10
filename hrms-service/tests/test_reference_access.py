"""Reference-list access: each list only for the screens that use it, minimal fields, field-level rules."""

from pathlib import Path

import pytest
from sqlalchemy import select

from app.models.audit_log_model import AuditLog
from app.scripts.load_reference_data import Loader, read_file
from tests.conftest import auth

TEMPLATE = Path(__file__).resolve().parents[1] / "setup" / "reference_data.yaml"

# (path, a permission of a screen that uses the list, a permission of a screen that does not, exact fields)
CASES = [
    ("/hr/designations", "hr.employees:view", "hr.leave:view", {"id", "code", "name", "active"}),
    ("/hr/employment-types", "hr.employees:import", "hr.payroll:view", {"id", "code", "name", "active"}),
    ("/hr/work-locations", "hr.employees:edit", "hr.employees:view", {"id", "code", "name", "active"}),
    ("/hr/employee-statuses", "hr.approvals:view", "hr.attendance:view", {"code", "label", "tone", "active", "allowedOnCreate", "transitions"}),
    ("/hr/shifts/options", "hr.employees:create", "hr.shifts:assign", {"id", "name", "description"}),
    ("/hr/attendance-policies/options", "hr.employees:edit", "hr.attendance:view", {"id", "name", "description"}),
    ("/hr/overtime-policies/options", "hr.employees:create", "hr.overtime:view", {"id", "name", "description"}),
    ("/hr/document-types", "hr.documents:upload", "hr.employees:view", {"id", "name", "category", "required", "expiryRequired", "allowedExtensions", "maxSizeBytes", "active"}),
    ("/hr/employees/payroll-fields", "hr.employees:view-sensitive", "hr.payroll:view-amounts", {"key", "label", "type", "required", "sensitive", "maxLength", "pattern", "patternMessage", "options", "hint"}),
    ("/hr/departments", "hr.reports:view", "hr.devices:view", {"id", "code", "name", "active"}),
]


@pytest.fixture
async def loaded(db):
    await Loader(db).run(read_file(TEMPLATE))


@pytest.mark.parametrize(("path", "allowed", "other", "fields"), CASES, ids=[c[0] for c in CASES])
async def test_each_list_is_limited_to_its_screens(client, db, loaded, path, allowed, other, fields):
    r = await client.get(f"/api/v1{path}", headers=auth([allowed]))
    assert r.status_code == 200, r.text
    assert r.json() and all(set(item) == fields for item in r.json()), "only the fields the screens need"

    r = await client.get(f"/api/v1{path}", headers=auth([other], user_id="22222222-2222-2222-2222-222222222222"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"
    denial = await db.scalar(select(AuditLog).where(AuditLog.result == "denied", AuditLog.actor_user_id == "22222222-2222-2222-2222-222222222222"))
    assert denial is not None and path in denial.summary

    assert (await client.get(f"/api/v1{path}")).status_code == 401


async def test_wildcard_permissions_are_honoured(client, loaded):
    assert (await client.get("/api/v1/hr/document-types", headers=auth(["hr.documents:*"]))).status_code == 200
    assert (await client.get("/api/v1/hr/designations", headers=auth(["*"]))).status_code == 200


async def test_self_service_gets_only_own_departments(client, loaded):
    # My Leave / My Payslips request the list but do not show it; they must not receive the company list.
    r = await client.get("/api/v1/hr/departments", headers=auth(["hr.self:view"]))
    assert r.status_code == 200 and r.json() == []
    assert (await client.get("/api/v1/hr/departments", headers=auth([]))).status_code == 403


async def test_status_transitions_only_for_status_changers(client, loaded):
    viewer = (await client.get("/api/v1/hr/employee-statuses", headers=auth(["hr.employees:view"]))).json()
    assert all(s["transitions"] == [] for s in viewer)
    changer = (await client.get("/api/v1/hr/employee-statuses", headers=auth(["hr.employees:change-status"]))).json()
    assert {s["code"]: s["transitions"] for s in changer}["active"] == ["exited", "on_notice", "suspended"]


async def test_no_reference_list_contains_employee_or_audit_data(client, loaded):
    banned = {"createdBy", "updatedBy", "createdByName", "updatedByName", "version", "sortOrder", "head", "employeeCount", "fullName"}
    for path, allowed, _, _ in CASES:
        body = (await client.get(f"/api/v1{path}", headers=auth([allowed]))).json()
        assert not any(banned & set(item) for item in body), path
