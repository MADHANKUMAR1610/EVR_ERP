"""Module 7: payroll engine, HR setup, the period workflow, amount masking, payslips, the register,
configurations and assignments. Every rate, slab and policy value below is a test value entered as HR would."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.models.attendance_model import AttendanceLockPeriod
from app.services.employee_support import company_today
from app.services.payroll.engine import ComponentDef, calculate, describe
from tests.conftest import auth
from tests.employee_fixtures import create, details, org  # noqa: F401

PAY = "/api/v1/hr/payroll"
SETUP = "/api/v1/hr/setup"
ALL = ["hr.payroll:view", "hr.payroll:view-amounts", "hr.payroll:process", "hr.payroll:approve", "hr.payroll-config:manage", "hr.payroll-assignments:manage",
       "hr.payslips:view", "hr.reports-payroll:view"]
SUBMITTER = "11111111-1111-1111-1111-111111111111"
APPROVER_ID = "22222222-2222-2222-2222-222222222222"


def hr(perms=ALL, user_id=SUBMITTER, roles=("test-hr-all",)):
    return auth(list(perms), user_id=user_id, roles=list(roles), name="Priya Payroll")


def last_month() -> tuple[str, date, date]:
    end = company_today().replace(day=1) - timedelta(days=1)
    return end.strftime("%Y-%m"), end.replace(day=1), end


# ---- Engine (pure) -----------------------------------------------------------------------------------------------


def C(code, type_, formula, **kw):
    return ComponentDef(id=code, code=code, name=code.title(), type=type_, formula=formula, **kw)


def test_engine_formulas_caps_slabs_and_proration():
    comps = [
        C("BASIC", "earning", "fixed", prorate=True),
        C("HRA", "earning", "percent", rate=Decimal("40"), base=("BASIC",)),
        C("SPECIAL", "earning", "balance_of_gross", prorate=True),
        C("OT", "earning", "overtime_rate", rate=Decimal("150")),
        C("PF", "deduction", "percent", rate=Decimal("12"), base=("BASIC",), base_cap=Decimal("15000")),
        C("PT", "deduction", "slab", base=("GROSS",), slabs=({"from": 0, "to": 20999.99, "amount": 0}, {"from": 21000, "to": None, "amount": 200})),
        C("EPF", "employer_contribution", "percent", rate=Decimal("12"), base=("BASIC",), base_cap=Decimal("15000")),
    ]
    values = {"BASIC": {"amount": 20000}}
    full = calculate(comps, values, monthly_gross=Decimal("50000"), factor=Decimal("1"), overtime_hours=Decimal("2"), overtime_payable=True)
    amounts = {line.component.code: line.amount for line in full.lines}
    assert amounts == {"BASIC": Decimal("20000.00"), "HRA": Decimal("8000.00"), "SPECIAL": Decimal("22000.00"), "OT": Decimal("300.00"), "PF": Decimal("1800.00"),
                       "PT": Decimal("200.00"), "EPF": Decimal("1800.00")}
    assert full.gross == Decimal("50300.00") and full.deductions == Decimal("2000.00") and full.net == Decimal("48300.00") and full.employer_contributions == Decimal("1800.00")
    assert [line.component.code for line in full.lines] == ["BASIC", "HRA", "SPECIAL", "OT", "PF", "PT", "EPF"], "structure order"

    half = calculate(comps, values, monthly_gross=Decimal("50000"), factor=Decimal("15") / Decimal("30"), overtime_hours=Decimal("0"), overtime_payable=False)
    amounts = {line.component.code: line.amount for line in half.lines}
    assert amounts["BASIC"] == Decimal("10000.00") and amounts["HRA"] == Decimal("4000.00") and amounts["SPECIAL"] == Decimal("11000.00") and amounts["OT"] == Decimal("0.00")
    assert amounts["PF"] == Decimal("1200.00") and amounts["PT"] == Decimal("200.00")
    assert describe(comps[4]) == "12% of BASIC, base capped at 15,000.00"


def test_engine_rounds_half_up_and_reports_incomplete_components():
    comps = [C("BASIC", "earning", "fixed", prorate=True), C("BAD", "deduction", "percent", base=("BASIC",))]
    out = calculate(comps, {"BASIC": {"amount": 1000}}, monthly_gross=None, factor=Decimal("1") / Decimal("3"), overtime_hours=Decimal("0"), overtime_payable=False)
    assert out.lines[0].amount == Decimal("333.33") and out.issues == ["BAD: a percentage component needs a rate and a base"]
    out = calculate([C("A", "earning", "fixed", max_amount=Decimal("100"))], {"A": {"amount": "100.005"}}, monthly_gross=None, factor=Decimal("1"), overtime_hours=Decimal("0"), overtime_payable=False)
    assert out.gross == Decimal("100.00")


# ---- Setup helpers ----------------------------------------------------------------------------------------------------


async def component(client, code, type_, formula, **kw):
    r = await client.post(f"{SETUP}/salary-components", json={"code": code, "name": kw.pop("name", code.title()), "type": type_, "formula": formula, **kw}, headers=hr())
    assert r.status_code == 201, r.text
    return r.json()


async def standard_structure(client):
    comps = [
        await component(client, "BASIC", "earning", "fixed", prorate=True),
        await component(client, "HRA", "earning", "percent", rate=40, base=["BASIC"]),
        await component(client, "SPECIAL", "earning", "balance_of_gross", prorate=True),
        await component(client, "PF", "deduction", "percent", rate=12, base=["BASIC"], baseCap=15000, statutory=True),
        await component(client, "PT", "deduction", "slab", base=["GROSS"], slabs=[{"from": 0, "to": 20999.99, "amount": 0}, {"from": 21000, "to": None, "amount": 200}], statutory=True),
        await component(client, "EPF", "employer_contribution", "percent", rate=12, base=["BASIC"], baseCap=15000, statutory=True),
    ]
    r = await client.post(f"{SETUP}/salary-structures", json={"code": "STAFF", "name": "Staff", "componentIds": [c["id"] for c in comps], "effectiveFrom": "2024-01-01"}, headers=hr())
    assert r.status_code == 201, r.text
    return r.json(), {c["code"]: c for c in comps}


async def salary(client, employee, structure, comps, gross=50000, basic=20000):
    r = await client.post(f"{SETUP}/employee-salaries", json={"employeeId": employee["id"], "structureId": structure["id"], "effectiveFrom": "2024-01-01", "monthlyGross": gross,
                                                             "values": [{"componentId": comps["BASIC"]["id"], "amount": basic}], "reason": "Appointment letter (test)"}, headers=hr())
    assert r.status_code == 201, r.text
    return r.json()


async def payroll_policy(client, values: dict):
    headers = auth(["admin:policies.payroll-manage", "admin:policies.view"])
    current = (await client.get("/api/v1/admin/policies/payroll", headers=headers)).json()
    r = await client.put("/api/v1/admin/policies/payroll", json={"values": {**current["values"], **values}, "effectiveFrom": company_today().isoformat(), "version": current["version"]}, headers=headers)
    assert r.status_code == 200, r.text


async def open_period(client, month):
    r = await client.post(f"{SETUP}/payroll-periods", json={"month": month, "currency": "INR"}, headers=hr())
    assert r.status_code == 201, r.text
    return r.json()


async def step(client, period, path, headers=None, **body):
    r = await client.post(f"{PAY}/periods/{period['id']}/{path}", json={"version": period["version"], **body}, headers=headers or hr())
    return r


# ---- Setup validation ---------------------------------------------------------------------------------------------------


async def test_setup_rejects_incomplete_or_out_of_order_configuration(client, org):
    r = await client.post(f"{SETUP}/salary-components", json={"code": "GROSS", "name": "Gross", "type": "earning", "formula": "percent", "base": ["NOPE"]}, headers=hr())
    assert r.status_code == 422 and {"code", "base", "rate"} <= set(details(r))
    basic = await component(client, "BASIC", "earning", "fixed")
    hra = await component(client, "HRA", "earning", "percent", rate=40, base=["BASIC"])
    r = await client.post(f"{SETUP}/salary-structures", json={"code": "S1", "name": "Wrong order", "componentIds": [hra["id"], basic["id"]], "effectiveFrom": "2024-01-01"}, headers=hr())
    assert r.status_code == 422 and "must come before it" in details(r)["componentIds"]
    r = await client.post(f"{SETUP}/salary-components", json={"code": "PT", "name": "PT", "type": "deduction", "formula": "slab", "base": ["GROSS"],
                                                              "slabs": [{"from": 0, "to": 100, "amount": 0}, {"from": 50, "to": None, "amount": 1}]}, headers=hr())
    assert r.status_code == 422 and details(r)["slabs"] == "Slabs must not overlap."
    upd = await client.put(f"{SETUP}/salary-components/{basic['id']}", json={"code": "BASIC2", "name": "Basic", "type": "earning", "formula": "fixed", "version": basic["version"]}, headers=hr())
    assert upd.status_code == 422, "codes never change"
    assert (await client.get(f"{PAY}/salary-components", headers=auth(["hr.payroll:view"]))).status_code == 200
    assert (await client.post(f"{SETUP}/salary-components", json={"code": "X", "name": "Xx", "type": "earning", "formula": "fixed"}, headers=auth(["hr.payroll:view"]))).status_code == 403


# ---- Full workflow ---------------------------------------------------------------------------------------------------------


async def test_period_workflow_from_validation_to_payslips(client, db, org):
    e = await create(client, org, "EVR-1")
    other = await create(client, org, "EVR-2")
    structure, comps = await standard_structure(client)
    await salary(client, e, structure, comps)
    month, start, end = last_month()
    period = await open_period(client, month)
    assert period["status"] == "open" and period["from"] == start.isoformat() and period["label"] == f"{calendar.month_name[start.month]} {start.year}"

    # Without the payroll policy the basis is unknown: blocking, never guessed.
    r = await step(client, period, "validation")
    assert r.status_code == 200, r.text
    checks = {c["code"]: c for c in r.json()["checks"]}
    assert checks["payroll_policy"]["status"] == "blocking" and r.json()["canCalculate"] is False and r.json()["period"]["status"] == "open"
    assert checks["missing_salary"]["status"] == "warning" and checks["missing_salary"]["count"] == 1 and checks["missing_salary"]["link"] == "/hr/payroll/salaries"
    period = r.json()["period"]
    assert (await step(client, period, "calculation")).status_code == 409, "calculation needs a validated period"

    await payroll_policy(client, {"prorationBasis": "calendar_days"})
    r = await step(client, period, "validation")
    assert r.json()["canCalculate"] is True and r.json()["period"]["status"] == "validated"
    period = r.json()["period"]
    assert (await client.get(f"{PAY}/periods/{period['id']}/validation", headers=hr())).json()["canCalculate"] is True
    inputs = (await client.get(f"{PAY}/periods/{period['id']}/inputs", headers=hr())).json()
    row = next(x for x in inputs["items"] if x["employee"]["id"] == e["id"])
    days = (end - start).days + 1
    assert row["daysInPeriod"] == days and row["paidDays"] == days and row["lossOfPayDays"] == 0 and row["salaryAssigned"] is True

    r = await step(client, period, "calculation")
    assert r.status_code == 200, r.text
    period = r.json()
    assert period["status"] == "calculated" and period["employeesIncluded"] == 2
    res = (await client.get(f"{PAY}/periods/{period['id']}/results", params={"sort": "employeeCode:asc"}, headers=hr())).json()
    assert res["currency"] == "INR" and res["totals"] == {"gross": 50000.0, "deductions": 2000.0, "net": 48000.0}
    mine, missing = res["items"]
    assert mine["net"] == 48000.0 and "attendance_exceptions" in mine["exceptions"] and missing["employee"]["id"] == other["id"] and missing["gross"] is None and "missing_salary" in missing["exceptions"]
    detail = (await client.get(f"{PAY}/periods/{period['id']}/results/{e['id']}", headers=hr())).json()
    assert {x["component"]["code"]: x["amount"] for x in detail["lines"]} == {"BASIC": 20000.0, "HRA": 8000.0, "SPECIAL": 22000.0, "PF": 1800.0, "PT": 200.0, "EPF": 1800.0}
    assert detail["previousNet"] is None

    # Amounts are null without view-amounts (backend, not UI).
    view_only = hr(["hr.payroll:view"])
    masked = (await client.get(f"{PAY}/periods/{period['id']}/results", headers=view_only)).json()
    assert masked["totals"] == {"gross": None, "deductions": None, "net": None} and all(i["net"] is None for i in masked["items"])
    assert all(x["amount"] is None for x in (await client.get(f"{PAY}/periods/{period['id']}/results/{e['id']}", headers=view_only)).json()["lines"])
    assert (await client.get(f"{PAY}/periods/{period['id']}/summary", headers=view_only)).json()["totals"] is None
    assert (await client.get(f"{PAY}/employee-salaries", headers=view_only)).status_code == 403
    summary = (await client.get(f"{PAY}/periods/{period['id']}/summary", headers=hr())).json()
    assert summary["employeesIncluded"] == 2 and summary["missingSalary"] == 1 and summary["totals"]["net"] == 48000.0

    # Submit, then segregation of duties: the submitter cannot approve; rejection needs a reason.
    r = await step(client, period, "submission", comment="Ready")
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    period = r.json()
    assert (await step(client, period, "decision", decision="approve")).status_code == 403
    assert details(await step(client, period, "decision", headers=hr(user_id=APPROVER_ID), decision="reject"))["comment"]
    r = await step(client, period, "decision", headers=hr(user_id=APPROVER_ID), decision="reject", comment="Check overtime")
    assert r.json()["status"] == "rejected"
    period = r.json()
    for path in ("validation", "calculation"):
        r = await step(client, period, path)
        assert r.status_code == 200, r.text
        period = r.json().get("period", r.json())
    period = (await step(client, period, "submission")).json()
    r = await step(client, period, "decision", headers=hr(user_id=APPROVER_ID), decision="approve", comment="OK")
    assert r.status_code == 200, r.text
    period = r.json()
    assert period["status"] == "approved" and [h["action"] for h in period["history"]].count("approved") == 1
    lock = await db.scalar(select(AttendanceLockPeriod).where(AttendanceLockPeriod.from_date == start))
    assert lock is not None and lock.to_date == end, "approval locks the period's attendance"
    assert (await step(client, period, "validation")).status_code == 409, "an approved period never changes"
    assert (await step(client, period, "validation")).json()["error"]["code"] == "PERIOD_LOCKED"

    r = await step(client, period, "payslips/publication")
    assert r.status_code == 200 and r.json()["status"] == "payslips_published"
    slips = (await client.get(f"{PAY}/payslips", headers=hr())).json()
    assert slips["meta"]["totalItems"] == 1 and slips["items"][0]["netPay"] == 48000.0
    assert (await client.get(f"{PAY}/payslips", headers=hr(["hr.payslips:view"]))).json()["items"][0]["netPay"] is None
    me = auth(["hr.self:view-payslips"], employee_id=e["id"], user_id=e["id"])
    own = (await client.get("/api/v1/hr/me/payslips", headers=me)).json()
    assert own["meta"]["totalItems"] == 1 and own["items"][0]["netPay"] == 48000.0
    doc = await client.get(f"{PAY}/payslips/{own['items'][0]['id']}/document", headers=me)
    assert doc.status_code == 200 and doc.content.startswith(b"%PDF-") and doc.headers["content-type"] == "application/pdf"
    stranger = auth(["hr.self:view-payslips"], employee_id=other["id"], user_id=other["id"])
    assert (await client.get(f"{PAY}/payslips/{own['items'][0]['id']}/document", headers=stranger)).status_code == 404

    report = (await client.get(f"{PAY}/reports/register", params={"periodId": period["id"]}, headers=hr())).json()
    assert report["totals"] == {"employees": 1, "gross": 50000.0, "deductions": 2000.0, "net": 48000.0}
    assert [c["component"]["code"] for c in report["componentTotals"]] == ["BASIC", "HRA", "SPECIAL", "PF", "PT", "EPF"]
    assert (await client.get(f"{PAY}/reports/register", params={"periodId": period["id"]}, headers=hr(["hr.reports-payroll:view"]))).status_code == 403
    csv_ = await client.get(f"{PAY}/reports/register/export", params={"periodId": period["id"]}, headers=hr())
    assert csv_.status_code == 200 and "EVR-1" in csv_.text and "Net" in csv_.text
    xlsx = await client.get(f"{PAY}/reports/register/export", params={"periodId": period["id"], "format": "xlsx"}, headers=hr())
    assert xlsx.content[:2] == b"PK"


async def test_absences_are_loss_of_pay_only_when_hr_says_so(client, org):
    e = await create(client, org, "EVR-1")
    structure, comps = await standard_structure(client)
    await salary(client, e, structure, comps, gross=30000, basic=15000)
    month, start, end = last_month()
    await payroll_policy(client, {"prorationBasis": "calendar_days", "absenceIsLossOfPay": True})
    period = await open_period(client, month)
    period = (await step(client, period, "validation")).json()["period"]
    period = (await step(client, period, "calculation")).json()
    days = (end - start).days + 1
    working = sum(1 for i in range(days) if (start + timedelta(days=i)).isoweekday() != 7)  # template GEN shift: Monday-Saturday, no punches
    detail = (await client.get(f"{PAY}/periods/{period['id']}/results/{e['id']}", headers=hr())).json()
    assert detail["paidDays"] == days - working
    basic = next(x["amount"] for x in detail["lines"] if x["component"]["code"] == "BASIC")
    expected = (Decimal(15000) * (days - working) / days).quantize(Decimal("0.01"))
    assert Decimal(str(basic)) == expected


# ---- Configurations and assignments --------------------------------------------------------------------------------------------


async def test_configuration_assignment_and_effective_configuration(client, org):
    e = await create(client, org, "EVR-1")
    structure, comps = await standard_structure(client)
    await salary(client, e, structure, comps)
    body = {"code": "STD", "name": "Standard", "description": "", "frequency": "monthly", "structureId": structure["id"], "componentIds": [c["id"] for c in comps.values()],
            "overtimeEligible": False, "effectiveFrom": "2024-01-01", "status": "active"}
    r = await client.post(f"{PAY}/configurations", json=body, headers=hr())
    assert r.status_code == 201, r.text
    config = r.json()
    assert [x["code"] for x in config["earnings"]] == ["BASIC", "HRA", "SPECIAL"]
    a = {"configurationId": config["id"], "scope": "company", "effectiveFrom": "2024-01-01", "reason": "Company default"}
    r = await client.post(f"{PAY}/configuration-assignments/preview", json=a, headers=hr())
    assert r.status_code == 200 and r.json()["blockedBy"] is None
    r = await client.post(f"{PAY}/configuration-assignments", json=a, headers=hr())
    assert r.status_code == 201, r.text
    assert (await client.post(f"{PAY}/configuration-assignments", json=a, headers=hr())).status_code == 422, "overlaps for the same target are refused"
    eff = (await client.get(f"{PAY}/employees/{e['id']}/effective-configuration", headers=hr())).json()
    assert eff["status"] == "resolved" and eff["source"] == "company" and eff["configuration"]["code"] == "STD"
    hist = (await client.get(f"{PAY}/configuration-assignments/history", headers=hr())).json()
    assert hist["meta"]["totalItems"] == 1 and hist["items"][0]["action"] == "assigned"
    assert (await client.post(f"{PAY}/configuration-assignments", json=a, headers=hr(["hr.payroll:view"]))).status_code == 403


async def test_periods_need_permission_and_unique_months(client, org):
    month, _, _ = last_month()
    await open_period(client, month)
    r = await client.post(f"{SETUP}/payroll-periods", json={"month": month, "currency": "inr"}, headers=hr())
    assert r.status_code == 422 and "already exists" in details(r)["month"]
    assert (await client.get(f"{PAY}/periods", headers=auth(["hr.self:view"]))).status_code == 403
    assert len((await client.get(f"{PAY}/periods", headers=hr(["hr.payroll:view"]))).json()) == 1
    assert (await client.get(f"{PAY}/payslips", headers=auth(["hr.self:view-payslips"]))).status_code == 403
