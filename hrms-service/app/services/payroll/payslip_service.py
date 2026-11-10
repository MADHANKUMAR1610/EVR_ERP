"""Payslips and the payroll register (contract E4).

- Payslips exist once a period is published. HR with hr.payslips:view sees those in their organizational
  scope (net pay null without hr.payroll:view-amounts); an employee sees their own (/hr/me/payslips).
- The payslip document is a PDF: for the payslip's own employee, or for hr.payslips:view with view-amounts
  in scope. Its layout is minimal (company name, period, employee, component lines, totals); the final
  layout is pending HR (HR_CONFIRMATION_PENDING.md).
- The register (by department, component totals, grand totals) needs hr.reports-payroll:view and
  hr.payroll:view-amounts; it covers calculated periods, in scope. Export: CSV (default) or XLSX.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections import defaultdict
from decimal import Decimal

from openpyxl import Workbook
from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ForbiddenError, NotFoundError, ValidationFailedError
from app.core.permissions import P
from app.models.employee_model import Employee
from app.models.payroll_model import PayrollPeriod, PayrollResult, Payslip
from app.repositories.base_repository import PageResult
from app.repositories.employee_repository import text_match
from app.schemas.common import Page
from app.schemas.employee_schema import NamedRefOut
from app.schemas.payroll_schema import ComponentRefOut, ComponentTotalOut, DepartmentTotalsOut, PayrollReportOut, PayslipOut, PayslipPeriodOut, ReportTotalsOut
from app.services.attendance.attendance_read_service import employee_ref
from app.services.audit_service import AuditService
from app.services.employee_import_service import safe_cell
from app.services.employee_scope_service import EmployeeScopeService, caller_employee_id
from app.services.employee_support import Caller
from app.services.payroll.common import MODULE, amt, can_amounts, departments, month_label, period_out
from app.utils.ids import body_id

TYPE_ORDER = {"earning": 0, "deduction": 1, "employer_contribution": 2}


def _f(v) -> float:
    return float(Decimal(str(v)))


def _money_text(v, currency: str) -> str:
    return f"{currency} {Decimal(str(v)):,.2f}"


def _pdf_escape(text: str) -> str:
    text = text.encode("latin-1", "replace").decode("latin-1")
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def simple_pdf(lines: list[tuple[str, int, bool]]) -> bytes:
    """A one-page A4 PDF of text lines (text, font size, bold), top to bottom. Standard fonts only."""
    y, ops = 800, []
    for text, size, bold in lines:
        ops.append(f"BT /{'F2' if bold else 'F1'} {size} Tf 50 {y} Td ({_pdf_escape(text)}) Tj ET")
        y -= size + 8
        if y < 40:
            break
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


class PayslipService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.audit = AuditService(session)

    async def _page(self, stmt, page: int, page_size: int, *, show_amounts: bool) -> Page:
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = (await self.session.execute(stmt.order_by(PayrollPeriod.month.desc(), func.lower(Employee.full_name), Payslip.id).limit(page_size).offset((page - 1) * page_size))).all()
        depts = await departments(self.session)
        items = [PayslipOut(id=str(s.id), employee=employee_ref(e, depts), period=PayslipPeriodOut(id=str(p.id), label=month_label(p.month), month=p.month),
                            net_pay=amt(s.net_pay, show_amounts), currency=s.currency, published_at=s.published_at) for s, e, p in rows]
        return Page.build(PageResult(items, page, page_size, total), items)

    @staticmethod
    def _base():
        return select(Payslip, Employee, PayrollPeriod).join(Employee, Employee.id == Payslip.employee_id).join(PayrollPeriod, PayrollPeriod.id == Payslip.period_id)

    async def list(self, *, period_id: str | None, department_id: str | None, q: str | None, page: int, page_size: int) -> Page:
        stmt = self._base().where(EmployeeScopeService.clause(self.caller.scope))
        if period_id:
            stmt = stmt.where(Payslip.period_id == body_id(period_id)) if body_id(period_id) else stmt.where(false())
        if department_id:
            stmt = stmt.where(Employee.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        if q:
            stmt = stmt.where(text_match(q))
        return await self._page(stmt, page, page_size, show_amounts=can_amounts(self.caller))

    async def mine(self, *, period_id: str | None, page: int, page_size: int) -> Page:
        own = caller_employee_id(self.caller.principal)
        stmt = self._base().where(Payslip.employee_id == own) if own else self._base().where(false())
        if period_id:
            stmt = stmt.where(Payslip.period_id == body_id(period_id)) if body_id(period_id) else stmt.where(false())
        return await self._page(stmt, page, page_size, show_amounts=True)

    async def document(self, payslip_id: uuid.UUID) -> tuple[bytes, str]:
        slip = await self.session.get(Payslip, payslip_id)
        if slip is None:
            raise NotFoundError()
        own = caller_employee_id(self.caller.principal) == slip.employee_id and self.caller.has(P.SELF_VIEW_PAYSLIPS)
        if not own:
            in_scope = self.caller.has(P.PAYSLIPS_VIEW) and await self.session.scalar(select(Employee.id).where(Employee.id == slip.employee_id, EmployeeScopeService.clause(self.caller.scope)))
            if not in_scope:
                raise NotFoundError()
            if not can_amounts(self.caller):
                raise ForbiddenError("Opening another employee's payslip needs permission to see payroll amounts.")
        e = await self.session.get(Employee, slip.employee_id)
        p = await self.session.get(PayrollPeriod, slip.period_id)
        r = await self.session.get(PayrollResult, slip.result_id)
        depts = await departments(self.session)
        cur = slip.currency
        lines: list[tuple[str, int, bool]] = [
            *([(get_settings().payslip_company_name, 16, True)] if get_settings().payslip_company_name else []),
            (f"Payslip - {month_label(p.month)}", 13, True),
            ("", 6, False),
            (f"Employee: {e.full_name} ({e.employee_code})", 10, False),
            (f"Department: {depts.get(e.department_id, '')}", 10, False),
            (f"Period: {p.from_date.isoformat()} to {p.to_date.isoformat()}", 10, False),
            (f"Days in period: {_f(r.days_in_period):g}   Paid days: {_f(r.paid_days):g}   Loss of pay days: {_f(r.loss_of_pay_days):g}", 10, False),
            ("", 6, False),
        ]
        titles = {"earning": "Earnings", "deduction": "Deductions", "employer_contribution": "Employer contributions (not deducted)"}
        for kind in ("earning", "deduction", "employer_contribution"):
            items = [x for x in r.lines if x["type"] == kind]
            if not items:
                continue
            lines.append((titles[kind], 11, True))
            for x in items:
                lines.append((f"    {x['name']} ({x['code']}): {_money_text(x['amount'], cur)}", 10, False))
            lines.append(("", 4, False))
        lines += [
            (f"Gross earnings: {_money_text(r.gross, cur)}", 11, True),
            (f"Total deductions: {_money_text(r.deductions, cur)}", 11, True),
            (f"Net pay: {_money_text(slip.net_pay, cur)}", 12, True),
            ("", 6, False),
            (f"Published {slip.published_at.date().isoformat()}. Generated by the HRMS; no signature required.", 8, False),
        ]
        if not own:
            self.audit.record(module=MODULE, action="payslip.downloaded", summary=f"Payslip {p.month} of {e.employee_code} downloaded", entity_type="payslip", entity_id=slip.id, entity_label=e.full_name)
            await self.session.commit()
        return simple_pdf(lines), f"payslip-{p.month}-{e.employee_code}.pdf"

    # ---- Register -------------------------------------------------------------------------------------------------

    async def _register_rows(self, period_id: str, department_id: str | None) -> tuple[PayrollPeriod, list[tuple[PayrollResult, Employee]]]:
        pid = body_id(period_id)
        p = await self.session.get(PayrollPeriod, pid) if pid else None
        if p is None:
            raise ValidationFailedError(details=[{"field": "periodId", "message": "Choose an existing payroll period."}])
        stmt = select(PayrollResult, Employee).join(Employee, Employee.id == PayrollResult.employee_id).where(PayrollResult.period_id == p.id, EmployeeScopeService.clause(self.caller.scope))
        if department_id:
            stmt = stmt.where(Employee.department_id == body_id(department_id)) if body_id(department_id) else stmt.where(false())
        rows = [(r, e) for r, e in (await self.session.execute(stmt.order_by(Employee.employee_code))).all() if "missing_salary" not in r.exceptions]
        return p, rows

    async def register(self, *, period_id: str, department_id: str | None) -> PayrollReportOut:
        p, rows = await self._register_rows(period_id, department_id)
        depts = await departments(self.session)
        by_dept: dict[uuid.UUID, list[PayrollResult]] = defaultdict(list)
        components: dict[str, dict] = {}
        for r, e in rows:
            by_dept[e.department_id].append(r)
            for x in r.lines:
                c = components.setdefault(x["code"], {"name": x["name"], "type": x["type"], "amount": Decimal("0")})
                c["amount"] += Decimal(str(x["amount"]))

        def money(items):
            return dict(gross=_f(sum((i.gross for i in items), Decimal("0"))), deductions=_f(sum((i.deductions for i in items), Decimal("0"))), net=_f(sum((i.net for i in items), Decimal("0"))))

        dept_rows = sorted(
            (DepartmentTotalsOut(department=NamedRefOut(id=str(d), name=depts.get(d, "")), employees=len(items), **money(items)) for d, items in by_dept.items()),
            key=lambda x: x.department.name.lower())
        comp_rows = [ComponentTotalOut(component=ComponentRefOut(code=code, name=c["name"], type=c["type"]), amount=_f(c["amount"]))
                     for code, c in sorted(components.items(), key=lambda kv: (TYPE_ORDER.get(kv[1]["type"], 3), kv[0]))]
        results = [r for r, _ in rows]
        return PayrollReportOut(period=await period_out(self.session, p), currency=p.currency, by_department=dept_rows, component_totals=comp_rows,
                                totals=ReportTotalsOut(employees=len(results), **money(results)))

    async def export(self, *, period_id: str, department_id: str | None, fmt: str) -> tuple[bytes, str, str]:
        p, rows = await self._register_rows(period_id, department_id)
        depts = await departments(self.session)
        codes: dict[str, tuple[str, str]] = {}
        for r, _ in rows:
            for x in r.lines:
                codes.setdefault(x["code"], (x["name"], x["type"]))
        ordered = sorted(codes, key=lambda c: (TYPE_ORDER.get(codes[c][1], 3), c))
        header = ["Employee ID", "Name", "Department", "Days in period", "Paid days", "Loss of pay days", *[f"{codes[c][0]} ({c})" for c in ordered], "Gross", "Deductions", "Net", "Employer contributions", "Currency"]
        lines = []
        for r, e in rows:
            amounts = {x["code"]: _f(x["amount"]) for x in r.lines}
            lines.append([e.employee_code, e.full_name, depts.get(e.department_id, ""), _f(r.days_in_period), _f(r.paid_days), _f(r.loss_of_pay_days),
                          *[amounts.get(c, 0.0) for c in ordered], _f(r.gross), _f(r.deductions), _f(r.net), _f(r.employer_contributions), p.currency])
        self.audit.record(module=MODULE, action="payroll_register.exported", summary=f"Payroll register {p.month} exported ({len(lines)} employee(s))", entity_type="payroll_period", entity_id=p.id, entity_label=p.month)
        await self.session.commit()
        name = f"payroll-register-{p.month}"
        if fmt == "xlsx":
            wb = Workbook()
            wb.active.title = p.month
            wb.active.append(header)
            for line in lines:
                wb.active.append([safe_cell(v) if isinstance(v, str) else v for v in line])
            out = io.BytesIO()
            wb.save(out)
            return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{name}.xlsx"
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(header)
        for line in lines:
            writer.writerow([safe_cell(v) if isinstance(v, str) else v for v in line])
        return ("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"{name}.csv"
