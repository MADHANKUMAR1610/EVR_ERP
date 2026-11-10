"""Module 5: large data: 1,000 employees, 10,000 punches, monthly register and export (timings reported)."""

import time
from datetime import timedelta

from sqlalchemy import func, select

from app.models.attendance_model import AttendanceEvent
from app.services.employee_support import company_today
from tests.attendance_fixtures import BASE, device, local  # noqa: F401
from tests.employee_fixtures import hr, org  # noqa: F401
from tests.test_employee_import import importer, row, run_all


async def test_one_thousand_employees_ten_thousand_punches(client, db, org, device):
    rows = [row(n, f"L-{n:04d}", work__attendanceId=f"L{n}", employment__joiningDate="2024-01-01") for n in range(2, 1002)]
    await client.post("/api/v1/hr/employee-imports", json={"rows": rows}, headers=importer())
    await run_all(db)
    # 5 finished working days x 1,000 employees x in + out = 10,000 punches, in pushes of 1,000.
    days, d = [], company_today() - timedelta(days=2)
    while len(days) < 5:
        if d.isoweekday() != 7:
            days.append(d)
        d -= timedelta(days=1)
    punches = [{"attendanceId": f"L{n}", "at": local(day, 9, n % 20), "direction": "in", "reference": f"{day}-{n}-in"} for day in days for n in range(2, 1002)]
    punches += [{"attendanceId": f"L{n}", "at": local(day, 17, 30 + n % 20), "direction": "out", "reference": f"{day}-{n}-out"} for day in days for n in range(2, 1002)]
    t0 = time.perf_counter()
    for i in range(0, len(punches), 1000):
        r = await client.post(f"{BASE}/events/ingest", json={"events": punches[i : i + 1000]}, headers={"X-Device-Key": device["key"]})
        assert r.status_code == 201 and r.json()["accepted"] == 1000, r.text
    t_ingest = time.perf_counter() - t0
    assert await db.scalar(select(func.count()).select_from(AttendanceEvent)) == 10_000

    month = days[0].strftime("%Y-%m")
    att = hr(["hr.attendance:view"])
    t0 = time.perf_counter()
    page = (await client.get(f"{BASE}/monthly", params={"month": month, "pageSize": 100}, headers=att)).json()
    t_monthly = time.perf_counter() - t0
    assert page["meta"]["totalItems"] == 1000 and len(page["items"]) == 100
    t0 = time.perf_counter()
    export = await client.get(f"{BASE}/monthly/export", params={"month": month}, headers=att)
    t_export = time.perf_counter() - t0
    assert export.status_code == 200 and export.content.decode("utf-8-sig").count("\n") == 1001
    t0 = time.perf_counter()
    daily = (await client.get(f"{BASE}/daily", params={"date": days[0].isoformat(), "pageSize": 100}, headers=att)).json()
    t_daily = time.perf_counter() - t0
    assert daily["meta"]["totalItems"] == 1000
    print(f"\nATTENDANCE LARGE: ingest 10,000 punches {t_ingest:.1f}s; monthly register {t_monthly:.1f}s; export {t_export:.1f}s; daily register {t_daily:.1f}s")
