"""Module 9: the report catalogue, every report running on real module data, totals over all rows, exports,
access (catalogue, payroll amounts, scope), the dashboard and report activity."""

from datetime import timedelta

from app.services.employee_support import company_today
from app.services.report_service import REPORTS
from tests.conftest import auth
from tests.employee_fixtures import create, details, org  # noqa: F401
from tests.leave_fixtures import apply, credit, leave_type
from tests.test_attendance_corrections_workflow import as_employee
from tests.test_payroll import last_month, open_period, payroll_policy, salary, standard_structure, step

REP = "/api/v1/hr/reports"
EVERYTHING = ["hr.reports:view", "hr.reports-payroll:view", "hr.employees:view", "hr.documents:view", "hr.attendance:view", "hr.overtime:view", "hr.leave:view",
              "hr.leave-balances:view", "hr.payroll:view", "hr.payroll:view-amounts"]


def hr(perms=EVERYTHING, roles=("test-hr-all",)):
    return auth(list(perms), roles=list(roles), name="Report Reader")


async def calculated_period(client, employee):
    structure, comps = await standard_structure(client)
    await salary(client, employee, structure, comps)
    await payroll_policy(client, {"prorationBasis": "calendar_days"})
    month, _, _ = last_month()
    period = await open_period(client, month)
    period = (await step(client, period, "validation")).json()["period"]
    return (await step(client, period, "calculation")).json()


async def test_every_report_runs_on_module_data(client, org):
    e1 = await create(client, org, "EVR-1")
    await create(client, org, "EVR-2", dept="PRD")
    lt = await leave_type(client)
    await credit(client, e1, lt, 10)
    d = company_today() + timedelta(days=7)
    assert (await apply(client, as_employee(e1), lt, d)).status_code == 201
    period = await calculated_period(client, e1)

    catalog = (await client.get(REP, headers=hr())).json()
    assert {r["id"] for r in catalog} == set(REPORTS) and len(catalog) == 25 and all(r["formats"] == ["csv", "xlsx"] for r in catalog)
    for r in catalog:
        res = await client.get(f"{REP}/{r['id']}", headers=hr())
        assert res.status_code == 200, (r["id"], res.text)
        body = res.json()
        assert body["report"]["id"] == r["id"] and body["columns"] and body["meta"]["page"] == 1
        keys = {c["key"] for c in body["columns"]}
        assert all(set(row) <= keys for row in body["rows"]), r["id"]
    directory = (await client.get(f"{REP}/employee_directory", headers=hr())).json()
    assert directory["meta"]["totalItems"] == 2 and directory["totals"] == {"employee": 2}
    summary = (await client.get(f"{REP}/payroll_summary", headers=hr())).json()
    assert summary["currency"] == "INR" and summary["totals"]["net"] == 48000.0 and "payroll results" in summary["notes"][0]
    assert (await client.get(f"{REP}/payroll_summary", params={"periodId": period["id"]}, headers=hr())).json()["rows"][0]["employeeCode"] == "EVR-1"
    upcoming = (await client.get(f"{REP}/leave_history", params={"status": "pending"}, headers=hr())).json()
    assert upcoming["meta"]["totalItems"] == 1 and upcoming["rows"][0]["status"] == "Pending"
    balance = (await client.get(f"{REP}/leave_balance", params={"leaveTypeId": lt["id"]}, headers=hr())).json()
    row = next(x for x in balance["rows"] if x["employeeCode"] == "EVR-1")
    assert row["allocated"] == 10 and row["pending"] == 1
    head = (await client.get(f"{REP}/headcount_by_department", headers=hr())).json()
    assert head["totals"] == {"employees": 2}


async def test_paging_totals_sorting_validation_and_export(client, org):
    for i in range(1, 13):
        await create(client, org, f"EVR-{i}")
    page = (await client.get(f"{REP}/employee_directory", params={"page": 2, "pageSize": 10, "sort": "employeeCode:desc"}, headers=hr())).json()
    assert page["meta"] == {"page": 2, "pageSize": 10, "totalItems": 12, "totalPages": 2} and len(page["rows"]) == 2 and page["totals"] == {"employee": 12}, "totals cover all rows"
    assert page["rows"][-1]["employeeCode"] == "EVR-1"
    assert (await client.get(f"{REP}/employee_directory", headers=hr())).status_code == 200  # page 1: recorded as generated
    assert (await client.get(f"{REP}/employee_directory", params={"sort": "salary:asc"}, headers=hr())).status_code == 400
    today = company_today()
    long = await client.get(f"{REP}/late_early", params={"from": (today - timedelta(days=120)).isoformat(), "to": today.isoformat()}, headers=hr())
    assert long.status_code == 422 and "92 days" in details(long)["to"]
    backwards = await client.get(f"{REP}/joiners_exits", params={"from": today.isoformat(), "to": (today - timedelta(days=1)).isoformat()}, headers=hr())
    assert backwards.status_code == 422
    assert (await client.get(f"{REP}/nope", headers=hr())).status_code == 404

    csv_ = await client.get(f"{REP}/employee_directory/export", params={"format": "csv"}, headers=hr())
    assert csv_.status_code == 200 and csv_.text.count("EVR-") == 12 and "Total" in csv_.text, "the export holds every row and the totals"
    xlsx = await client.get(f"{REP}/employee_directory/export", params={"format": "xlsx"}, headers=hr())
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    activity = (await client.get(f"{REP}/activity", params={"limit": 5}, headers=hr())).json()
    assert [a["action"] for a in activity[:2]] == ["exported", "exported"] and activity[0]["format"] == "xlsx" and activity[0]["reportTitle"] == "Employee directory"
    assert any(a["action"] == "generated" for a in activity), "a run of page 1 is recorded"


async def test_access_catalogue_amounts_and_scope(client, org):
    e1 = await create(client, org, "EVR-1")
    await create(client, org, "EVR-2", dept="PRD")
    await calculated_period(client, e1)
    hr_only = hr(["hr.reports:view", "hr.employees:view"])
    assert {r["category"] for r in (await client.get(REP, headers=hr_only)).json()} == {"hr"}
    assert (await client.get(f"{REP}/document_completion", headers=hr_only)).status_code == 403
    no_amounts = hr(["hr.reports-payroll:view", "hr.payroll:view"])
    ids = {r["id"] for r in (await client.get(REP, headers=no_amounts)).json()}
    assert ids == {"lop_summary", "processing_status"}, "amount reports need hr.payroll:view-amounts"
    assert (await client.get(f"{REP}/payroll_summary", headers=no_amounts)).status_code == 403
    assert (await client.get(f"{REP}/payroll_summary/export", headers=no_amounts)).status_code == 403
    assert (await client.get(f"{REP}/lop_summary", headers=no_amounts)).status_code == 200
    qa = hr(roles=("test-hr-qa",))
    rows = (await client.get(f"{REP}/employee_directory", headers=qa)).json()["rows"]
    assert [r["employeeCode"] for r in rows] == ["EVR-1"], "organizational scope"
    assert (await client.get(REP, headers=auth(["hr.self:view"]))).status_code == 403

    dash = (await client.get(f"{REP}/dashboard", headers=hr())).json()
    assert dash["totalEmployees"]["value"] == 2 and dash["payrollCost"]["value"] == 51800.0 and dash["payrollCost"]["currency"] == "INR"
    assert len(dash["attendanceTrend"]) == 6 and dash["pendingPayrollApprovals"]["value"] == 0 and len(dash["payrollCostTrend"]) == 1
    limited = (await client.get(f"{REP}/dashboard", headers=hr(["hr.reports:view"]))).json()
    assert limited["payrollCost"]["value"] is None and limited["payrollCost"]["unavailableReason"] and limited["totalEmployees"]["value"] is None and limited["payrollCostTrend"][0]["cost"] is None
