"""Administration → Organization → Reporting lines (contract G4). Scoped like every employee read."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_model import Employee, EmployeeHistory, EmployeeReportingLine
from app.repositories.base_repository import paginate
from app.repositories.employee_repository import EmployeeRepository
from app.schemas.common import Page, PageParams
from app.schemas.employee_schema import EmployeeBriefOut, ManagerChangeIn, ReportingLineOut
from app.services.audit_service import AuditService
from app.services.employee_scope_service import EmployeeScopeService
from app.services.employee_service import EmployeeService
from app.services.employee_support import Caller, References, parse_date
from app.utils.ids import body_id
from app.utils.validation import FieldErrors


def _brief(e: Employee) -> EmployeeBriefOut:
    return EmployeeBriefOut(id=str(e.id), employee_code=e.employee_code, full_name=e.full_name)


class ReportingLineService:
    def __init__(self, session: AsyncSession, caller: Caller):
        self.session = session
        self.caller = caller
        self.repo = EmployeeRepository(session)
        self.scopes = EmployeeScopeService(session)
        self.audit = AuditService(session)
        self.scope_clause = EmployeeScopeService.clause(caller.scope)

    async def _lines(self, employees: list[Employee], refs: References) -> list[ReportingLineOut]:
        managers = await self.repo.get_many(e.reporting_manager_id for e in employees)
        reports = await self.repo.direct_report_counts(e.id for e in employees)
        dates = await self.repo.current_line_dates(employees)
        out = []
        for e in employees:
            manager = managers.get(e.reporting_manager_id)
            effective = dates.get(e.id)
            out.append(
                ReportingLineOut(
                    employee=_brief(e),
                    department=refs.named(refs.departments, e.department_id),
                    designation=refs.named(refs.designations, e.designation_id),
                    manager=_brief(manager) if manager else None,
                    effective_from=effective.isoformat() if effective and manager else None,
                    direct_reports=reports.get(e.id, 0),
                )
            )
        return out

    async def list(self, params: PageParams, *, department_id: str | None, manager_id: str | None) -> Page:
        stmt = self.repo.reporting_lines(self.scope_clause, q=params.q, department_id=body_id(department_id), manager_id=body_id(manager_id))
        result = await paginate(self.session, stmt, params.page, params.page_size)
        refs = await References.load(self.session)
        return Page.build(result, await self._lines(result.items, refs))

    async def change_manager(self, employee_id: uuid.UUID, data: ManagerChangeIn) -> ReportingLineOut:
        employee = await EmployeeService(self.session, self.caller)._visible(employee_id)
        err = FieldErrors()
        # The dialog shows managerId problems as its form message, so it is also the top-level message.
        manager_id = await EmployeeService(self.session, self.caller)._validate_manager(err, "managerId", data.manager_id, employee.id)
        if data.manager_id and manager_id is None and not err.has("managerId"):
            err.add("managerId", "Select an existing employee.")
        if not err.has("managerId") and manager_id == employee.reporting_manager_id:
            err.add("managerId", "This employee already reports to this manager." if manager_id else "This employee has no manager already.")
        if not err.has("managerId") and not await self.scopes.covers(self.caller.scope, employee_id=employee.id, department_id=employee.department_id, manager_id=manager_id):
            err.add("managerId", "You can only assign managers within your organizational scope.")
        effective = None
        try:
            effective = parse_date(data.effective_from)
        except ValueError:
            pass
        if effective is None:
            err.add("effectiveFrom", "Enter the effective date.")
        reason = data.reason.strip()
        if len(reason) < 3:
            err.add("reason", "Enter the reason.")
        elif len(reason) > 300:
            err.add("reason", "Keep the reason under 300 characters.")
        err.raise_if_any(use_first_message=True)

        before = employee.reporting_manager_id
        employee.reporting_manager_id = manager_id
        self.session.add(EmployeeReportingLine(employee_id=employee.id, manager_id=manager_id, effective_from=effective, reason=reason))
        self.session.add(EmployeeHistory(employee_id=employee.id, action="updated", summary="Reporting manager changed", changes=["Reporting line"], effective_date=effective, comment=reason))
        await self.session.flush()
        self.audit.record(
            module="Organization", action="reporting_line.changed", summary=f"Reporting manager of {employee.employee_code} changed", entity_type="employee",
            entity_id=employee.id, entity_label=employee.full_name, changes=[{"field": "managerId", "before": str(before) if before else None, "after": str(manager_id) if manager_id else None}],
        )
        await self.session.commit()
        refs = await References.load(self.session)
        return (await self._lines([employee], refs))[0]
