"""The setup YAML loader: loads the template, is create-only, audits as the system actor."""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.context import SYSTEM_PRINCIPAL
from app.models.audit_log_model import AuditLog
from app.models.department_model import Department
from app.models.shift_model import Shift
from app.scripts.load_reference_data import Loader, SetupFileError, read_file
from tests.conftest import auth

TEMPLATE = Path(__file__).resolve().parents[1] / "setup" / "reference_data.yaml"


async def test_template_loads_and_second_run_skips_everything(db, client):
    data = read_file(TEMPLATE)
    first = await Loader(db).run(data)
    assert first["departments"] == {"created": 15, "skipped": 0}
    assert first["document_types"] == {"created": 10, "skipped": 0}
    assert first["shifts"] == {"created": 4, "skipped": 0}
    second = await Loader(db).run(data)
    assert all(c["created"] == 0 for c in second.values())

    dep = await db.scalar(select(Department).where(Department.code == "PRD"))
    assert dep.created_by == SYSTEM_PRINCIPAL.actor_uuid
    assert await db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.actor_user_id == SYSTEM_PRINCIPAL.user_id)) > 50
    night = await db.scalar(select(Shift).where(Shift.code == "C"))
    assert night.overnight and len(night.department_links) == 6

    r = await client.get("/api/v1/hr/employee-statuses", headers=auth(["hr.employees:change-status"]))
    statuses = {s["code"]: s["transitions"] for s in r.json()}
    assert statuses["active"] == ["exited", "on_notice", "suspended"] and statuses["exited"] == []
    r = await client.get("/api/v1/hr/employees/payroll-fields", headers=auth(["hr.employees:view-sensitive"]))
    assert [f["key"] for f in r.json()] == ["payrollGroup", "paymentMode", "bankAccountNumber", "bankIfsc"]


async def test_dry_run_writes_nothing(db):
    summary = await Loader(db, dry_run=True).run(read_file(TEMPLATE))
    assert summary["designations"]["created"] == 11
    assert await db.scalar(select(func.count()).select_from(Department)) == 0


async def test_file_errors(tmp_path, db):
    bad = tmp_path / "bad.yaml"
    bad.write_text("holidays: []\n")
    with pytest.raises(SetupFileError):
        read_file(bad)
    with pytest.raises(SetupFileError):
        await Loader(db).run({"shifts": [{"code": "X", "name": "Shift X", "start": "09:00", "end": "17:00", "overnight": False, "break_minutes": 30, "grace_minutes": 5, "working_days": [1], "departments": ["NOPE"]}]})


def test_template_is_pending_hr_confirmation():
    from app.scripts.load_reference_data import hr_confirmed

    assert hr_confirmed(TEMPLATE) is False, "the shipped template must stay pending until HR signs it off"


def test_production_refuses_unconfirmed_file(tmp_path, monkeypatch, capsys):
    import asyncio

    from app.scripts import load_reference_data as loader

    class _Prod:
        environment = "production"

    monkeypatch.setattr(loader, "get_settings", lambda: _Prod())
    assert asyncio.run(loader._main(TEMPLATE, dry_run=False)) == 2
    assert "pending HR confirmation" in capsys.readouterr().out

    signed = tmp_path / "signed.yaml"
    signed.write_text("hr_confirmed: true\nhr_confirmed_by: HR Manager\nhr_confirmed_on: 2026-11-20\ndepartments: []\n")
    assert loader.hr_confirmed(signed) is True
