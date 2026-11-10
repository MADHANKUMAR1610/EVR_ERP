"""Module 6: large data: 1,000 employees, a monthly accrual run, 1,000 pending requests, the balance
register, the requests register, the summary and the approval inbox (timings reported)."""

import time
import uuid

from sqlalchemy import func, select

from app.core.context import SYSTEM_PRINCIPAL
from app.database.audit_listener import acting_as
from app.models.employee_model import Employee
from app.models.leave_model import LeaveLedgerEntry, LeaveRequest
from app.services.employee_support import company_today
from app.services.leave.balance_service import run_accrual
from tests.employee_fixtures import org  # noqa: F401
from tests.leave_fixtures import LEAVE, SETUP, hr_leave, leave_type, monday, set_leave_policy, setup_headers
from tests.test_employee_import import importer, row, run_all


async def test_one_thousand_employees_balances_requests_and_inbox(client, db, org):
    rows = [row(n, f"L-{n:04d}", work__attendanceId=f"L{n}", employment__joiningDate="2024-01-01") for n in range(2, 1002)]
    await client.post("/api/v1/hr/employee-imports", json={"rows": rows}, headers=importer())
    await run_all(db)
    lt = await leave_type(client)
    year = company_today().year
    r = await client.post(f"{SETUP}/leave-policies", json={"leaveTypeId": lt["id"], "accrualMethod": "monthly", "accrualDays": 1, "effectiveFrom": f"{year}-01-01"}, headers=setup_headers())
    assert r.status_code == 201
    t0 = time.perf_counter()
    with acting_as(SYSTEM_PRINCIPAL):
        result = await run_accrual(db)
    t_accrual = time.perf_counter() - t0
    month = company_today().month
    assert result["credited"] == 1000 * month
    assert await db.scalar(select(func.count()).select_from(LeaveLedgerEntry)) == 1000 * month

    start = monday()
    employees = (await db.scalars(select(Employee))).all()
    with acting_as(SYSTEM_PRINCIPAL):
        db.add_all([LeaveRequest(employee_id=e.id, leave_type_id=uuid.UUID(lt["id"]), from_date=start, to_date=start, portion="full", days=1, days_by_year={str(start.year): 1.0},
                                 charged_dates=[start], reason="Bulk test", status="pending", stage="first_level") for e in employees])
        await db.commit()
    await set_leave_policy(client, {"lowBalanceThreshold": month, "upcomingWindowDays": 30})
    hr = hr_leave()
    t0 = time.perf_counter()
    bal = (await client.get(f"{LEAVE}/balances", params={"year": year, "pageSize": 100}, headers=hr)).json()
    t_bal = time.perf_counter() - t0
    assert bal["meta"]["totalItems"] == 1000 and bal["items"][0]["balances"][0]["available"] == month - 1
    t0 = time.perf_counter()
    reqs = (await client.get(f"{LEAVE}/requests", params={"pageSize": 100, "status": "pending"}, headers=hr)).json()
    t_req = time.perf_counter() - t0
    assert reqs["meta"]["totalItems"] == 1000 and len(reqs["items"]) == 100
    t0 = time.perf_counter()
    summary = (await client.get(f"{LEAVE}/summary", headers=hr)).json()
    t_sum = time.perf_counter() - t0
    assert summary["pendingRequests"] == 1000 and summary["awaitingMyAction"] == 1000 and len(summary["lowBalances"]) == 50
    t0 = time.perf_counter()
    inbox = (await client.get("/api/v1/hr/approvals", params={"pageSize": 100}, headers=hr)).json()
    t_inbox = time.perf_counter() - t0
    assert inbox["counts"]["leave"] == 1000 and len(inbox["items"]) == 100
    print(f"\nLEAVE LARGE: accrual {1000 * month} credits {t_accrual:.1f}s; balances page {t_bal:.2f}s; requests page {t_req:.2f}s; summary {t_sum:.2f}s; inbox {t_inbox:.2f}s")
