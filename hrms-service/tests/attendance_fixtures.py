"""Shared setup for the attendance tests: a registered device with an API key, working days, punches."""

from datetime import datetime, time, timedelta

import pytest

from app.services.attendance.attendance_data import company_tz
from app.services.employee_support import company_today
from tests.conftest import auth

BASE = "/api/v1/hr/attendance"
ATT = ["hr.attendance:view"]


def past_workday(back: int = 3):
    """A finished Monday–Saturday (the template shifts' working days), `back` or more days ago."""
    d = company_today() - timedelta(days=back)
    while d.isoweekday() == 7:
        d -= timedelta(days=1)
    return d


def local(d, h, m=0) -> str:
    return datetime.combine(d, time(h, m), company_tz()).isoformat()


@pytest.fixture
async def device(client, org):
    manage = auth(["hr.devices:manage"])
    d = (await client.post("/api/v1/hr/setup/attendance-devices", json={"name": "Gate 1", "serialNumber": "SN-001", "workLocationId": org.loc["PLANT1"]}, headers=manage)).json()
    key = (await client.post(f"/api/v1/hr/setup/attendance-devices/{d['id']}/key", headers=manage)).json()["apiKey"]
    return {"id": d["id"], "key": key}


async def ingest(client, device, *events):
    """events: (attendanceId, iso time, direction[, reference])."""
    body = {"events": [{"attendanceId": e[0], "at": e[1], "direction": e[2], **({"reference": e[3]} if len(e) > 3 else {})} for e in events]}
    r = await client.post(f"{BASE}/events/ingest", json=body, headers={"X-Device-Key": device["key"]})
    assert r.status_code == 201, r.text
    return r.json()
