"""HR → Payroll (frontend payroll.http.ts, contracts E4 and H4), plus the HR setup additions (MODULE_7_DECISIONS.md).

Amounts are null without hr.payroll:view-amounts. Employee rows follow the caller's organizational scope.
"""

from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.permissions import P
from app.schemas.common import Page, PageParams, page_params
from app.schemas.payroll_schema import (
    AssignmentEndIn,
    AssignmentHistoryEntryOut,
    AssignmentImpactOut,
    EffectiveConfigurationOut,
    EmployeeSalaryDetailOut,
    EmployeeSalaryIn,
    EmployeeSalaryRowOut,
    PayrollAssignmentIn,
    PayrollAssignmentOut,
    PayrollConfigurationIn,
    PayrollConfigurationOptionsOut,
    PayrollConfigurationOut,
    PayrollInputRowOut,
    PayrollPeriodIn,
    PayrollPeriodOut,
    PayrollReportOut,
    PayrollResultDetailOut,
    PayslipOut,
    PeriodDecisionIn,
    PeriodSummaryOut,
    ResultsPageOut,
    SalaryComponentIn,
    SalaryComponentOut,
    SalaryComponentSetupOut,
    SalaryStructureIn,
    SalaryStructureOut,
    SubmissionIn,
    ValidationResultOut,
    ValidationWithPeriodOut,
    VersionIn,
)
from app.services.employee_support import caller_context, parse_date
from app.services.payroll.configuration_service import PayrollConfigurationService
from app.services.payroll.payslip_service import PayslipService
from app.services.payroll.period_service import PayrollPeriodService
from app.services.payroll.setup_service import PayrollSetupService
from app.utils.ids import path_id
from app.utils.validation import FieldErrors

router = APIRouter(prefix="/hr/payroll", tags=["Payroll"])
me_router = APIRouter(prefix="/hr/me", tags=["Payroll"])
setup_router = APIRouter(prefix="/hr/setup", tags=["HR setup"])
Params = Annotated[PageParams, Depends(page_params)]
Dept = Annotated[str | None, Query(alias="departmentId")]

VIEW = [Depends(require(P.PAYROLL_VIEW))]
PROCESS = [Depends(require(P.PAYROLL_PROCESS))]
APPROVE = [Depends(require(P.PAYROLL_APPROVE))]
AMOUNTS = [Depends(require(P.PAYROLL_VIEW_AMOUNTS))]
CONFIG = [Depends(require(P.PAYROLL_CONFIG_MANAGE))]
ASSIGN = [Depends(require(P.PAYROLL_ASSIGNMENTS_MANAGE))]
REGISTER = [Depends(require(P.REPORTS_PAYROLL_VIEW)), Depends(require(P.PAYROLL_VIEW_AMOUNTS))]
NO_STORE = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store, private"}


async def _periods(session, principal) -> PayrollPeriodService:
    return PayrollPeriodService(session, await caller_context(session, principal))


async def _payslips(session, principal) -> PayslipService:
    return PayslipService(session, await caller_context(session, principal))


def _date(value: str | None, field: str):
    try:
        return parse_date(value)
    except ValueError:
        err = FieldErrors()
        err.add(field, "Enter the date as YYYY-MM-DD.")
        err.raise_if_any()


# ---- Periods ------------------------------------------------------------------------------------------------


@router.get("/periods", response_model=list[PayrollPeriodOut], dependencies=VIEW, summary="Payroll periods, newest first")
async def periods(session: DbSession, principal: CurrentPrincipal):
    return await (await _periods(session, principal)).periods()


@router.get("/periods/{period_id}/summary", response_model=PeriodSummaryOut, dependencies=VIEW, summary="Period summary (totals null before calculation or without view-amounts)")
async def summary(period_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _periods(session, principal)).summary(path_id(period_id))


@router.get("/periods/{period_id}/validation", response_model=ValidationResultOut | None, dependencies=PROCESS, summary="The last validation result, or null")
async def validation(period_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _periods(session, principal)).validation(path_id(period_id))


@router.post("/periods/{period_id}/validation", response_model=ValidationWithPeriodOut, dependencies=PROCESS, summary="Run the checks; discards earlier results")
async def validate(period_id: str, data: VersionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _periods(session, principal)).validate(path_id(period_id), data)


@router.get("/periods/{period_id}/inputs", response_model=Page[PayrollInputRowOut], dependencies=VIEW, summary="Inputs per employee: days, loss of pay, leave, approved overtime, issues")
async def inputs(period_id: str, session: DbSession, principal: CurrentPrincipal, params: Params, department_id: Dept = None,
                 exceptions_only: Annotated[bool, Query(alias="exceptionsOnly")] = False):
    return await (await _periods(session, principal)).inputs(path_id(period_id), q=params.q, department_id=department_id, exceptions_only=exceptions_only, sort=params.sort,
                                                             page=params.page, page_size=params.page_size)


@router.post("/periods/{period_id}/calculation", response_model=PayrollPeriodOut, dependencies=PROCESS, summary="Calculate the period (422 while a check is blocking)")
async def calculate(period_id: str, data: VersionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _periods(session, principal)).calculate(path_id(period_id), data)


@router.get("/periods/{period_id}/results", response_model=ResultsPageOut, dependencies=VIEW, summary="Calculated results with totals")
async def results(period_id: str, session: DbSession, principal: CurrentPrincipal, params: Params, department_id: Dept = None,
                  exceptions_only: Annotated[bool, Query(alias="exceptionsOnly")] = False):
    return await (await _periods(session, principal)).results(path_id(period_id), q=params.q, department_id=department_id, exceptions_only=exceptions_only, sort=params.sort,
                                                              page=params.page, page_size=params.page_size)


@router.get("/periods/{period_id}/results/{employee_id}", response_model=PayrollResultDetailOut, dependencies=VIEW, summary="One employee's result: component lines and previous net")
async def result(period_id: str, employee_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _periods(session, principal)).result(path_id(period_id), path_id(employee_id))


@router.post("/periods/{period_id}/submission", response_model=PayrollPeriodOut, dependencies=PROCESS, summary="Submit a calculated period for approval")
async def submit(period_id: str, data: SubmissionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _periods(session, principal)).submit(path_id(period_id), data)


@router.post("/periods/{period_id}/decision", response_model=PayrollPeriodOut, dependencies=APPROVE, summary="Approve (locks attendance) or reject (reason required)")
async def decide(period_id: str, data: PeriodDecisionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _periods(session, principal)).decide(path_id(period_id), data)


@router.post("/periods/{period_id}/payslips/publication", response_model=PayrollPeriodOut, dependencies=PROCESS, summary="Publish the payslips of an approved period")
async def publish(period_id: str, data: VersionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _periods(session, principal)).publish(path_id(period_id), data)


# ---- Components, structures, salaries ---------------------------------------------------------------------------


@router.get("/salary-components", response_model=list[SalaryComponentOut], dependencies=VIEW, summary="Salary components")
async def components(session: DbSession):
    return await PayrollSetupService(session).components()


@router.get("/salary-structures", response_model=list[SalaryStructureOut], dependencies=VIEW, summary="Salary structures")
async def structures(session: DbSession):
    return await PayrollSetupService(session).structures()


@router.get("/employee-salaries", response_model=Page[EmployeeSalaryRowOut], dependencies=AMOUNTS, summary="Employee salary records (organizational scope)")
async def salaries(session: DbSession, principal: CurrentPrincipal, params: Params, department_id: Dept = None, missing_only: Annotated[bool, Query(alias="missingOnly")] = False):
    service = PayrollSetupService(session)
    return await service.salaries(await caller_context(session, principal), q=params.q, department_id=department_id, missing_only=missing_only, sort=params.sort,
                                  page=params.page, page_size=params.page_size, currency=await service.latest_currency())


@router.get("/employee-salaries/{employee_id}", response_model=EmployeeSalaryDetailOut, dependencies=AMOUNTS, summary="One employee's salary record and history")
async def salary(employee_id: str, session: DbSession, principal: CurrentPrincipal):
    return await PayrollSetupService(session).salary(path_id(employee_id), await caller_context(session, principal))


# ---- Payslips and register ------------------------------------------------------------------------------------------


@router.get("/payslips", response_model=Page[PayslipOut], dependencies=[Depends(require(P.PAYSLIPS_VIEW))], summary="Published payslips (organizational scope)")
async def payslips(session: DbSession, principal: CurrentPrincipal, params: Params, period_id: Annotated[str | None, Query(alias="periodId")] = None, department_id: Dept = None):
    return await (await _payslips(session, principal)).list(period_id=period_id, department_id=department_id, q=params.q, page=params.page, page_size=params.page_size)


@me_router.get("/payslips", response_model=Page[PayslipOut], dependencies=[Depends(require(P.SELF_VIEW_PAYSLIPS))], summary="The signed-in employee's own payslips")
async def my_payslips(session: DbSession, principal: CurrentPrincipal, params: Params, period_id: Annotated[str | None, Query(alias="periodId")] = None):
    return await (await _payslips(session, principal)).mine(period_id=period_id, page=params.page, page_size=params.page_size)


@router.get("/payslips/{payslip_id}/document", dependencies=[Depends(require(P.PAYSLIPS_VIEW, P.SELF_VIEW_PAYSLIPS))], summary="Payslip PDF (own payslip, or hr.payslips:view)",
            responses={200: {"content": {"application/pdf": {}}, "description": "The payslip"}})
async def payslip_document(payslip_id: str, session: DbSession, principal: CurrentPrincipal) -> Response:
    content, name = await (await _payslips(session, principal)).document(path_id(payslip_id))
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}", **NO_STORE})


@router.get("/reports/register", response_model=PayrollReportOut, dependencies=REGISTER, summary="Payroll register: by department, component totals, grand totals")
async def register(session: DbSession, principal: CurrentPrincipal, period_id: Annotated[str, Query(alias="periodId")], department_id: Dept = None):
    return await (await _payslips(session, principal)).register(period_id=period_id, department_id=department_id)


@router.get("/reports/register/export", dependencies=REGISTER, summary="Payroll register as CSV (default) or XLSX",
            responses={200: {"content": {"text/csv": {}, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
async def register_export(session: DbSession, principal: CurrentPrincipal, period_id: Annotated[str, Query(alias="periodId")], department_id: Dept = None,
                          format: Annotated[Literal["csv", "xlsx"], Query()] = "csv") -> Response:
    content, media_type, name = await (await _payslips(session, principal)).export(period_id=period_id, department_id=department_id, fmt=format)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"', **NO_STORE})


# ---- Configurations and assignments (H4) -------------------------------------------------------------------------------


@router.get("/configurations", response_model=list[PayrollConfigurationOut], dependencies=VIEW, summary="Payroll configurations")
async def configurations(session: DbSession):
    return await PayrollConfigurationService(session).configurations()


@router.get("/configurations/options", response_model=PayrollConfigurationOptionsOut, dependencies=VIEW, summary="Choices for the configuration form")
async def configuration_options(session: DbSession):
    return await PayrollConfigurationService(session).options()


@router.post("/configurations", response_model=PayrollConfigurationOut, status_code=status.HTTP_201_CREATED, dependencies=CONFIG, summary="Create a configuration")
async def create_configuration(data: PayrollConfigurationIn, session: DbSession):
    return await PayrollConfigurationService(session).save_configuration(None, data)


@router.put("/configurations/{config_id}", response_model=PayrollConfigurationOut, dependencies=CONFIG, summary="Update a configuration (version required)")
async def update_configuration(config_id: str, data: PayrollConfigurationIn, session: DbSession):
    return await PayrollConfigurationService(session).save_configuration(path_id(config_id), data)


@router.get("/configuration-assignments", response_model=Page[PayrollAssignmentOut], dependencies=VIEW, summary="Configuration assignments")
async def assignments(
    session: DbSession, params: Params, scope: Annotated[Literal["company", "department", "employee"] | None, Query()] = None,
    configuration_id: Annotated[str | None, Query(alias="configurationId")] = None, department_id: Dept = None, employee_id: Annotated[str | None, Query(alias="employeeId")] = None,
    status_: Annotated[Literal["active", "scheduled", "ended"] | None, Query(alias="status")] = None, conflicts_only: Annotated[bool, Query(alias="conflictsOnly")] = False,
):
    return await PayrollConfigurationService(session).assignments(scope=scope, configuration_id=configuration_id, department_id=department_id, employee_id=employee_id, status=status_,
                                                                  conflicts_only=conflicts_only, page=params.page, page_size=params.page_size)


@router.get("/configuration-assignments/history", response_model=Page[AssignmentHistoryEntryOut], dependencies=VIEW, summary="Assignment history")
async def assignment_history(session: DbSession, params: Params, employee_id: Annotated[str | None, Query(alias="employeeId")] = None, department_id: Dept = None,
                             scope: Annotated[Literal["company", "department", "employee"] | None, Query()] = None):
    return await PayrollConfigurationService(session).history(employee_id=employee_id, department_id=department_id, scope=scope, page=params.page, page_size=params.page_size)


@router.post("/configuration-assignments/preview", response_model=AssignmentImpactOut, dependencies=ASSIGN, summary="Dry run of an assignment")
async def preview_assignment(data: PayrollAssignmentIn, session: DbSession):
    return await PayrollConfigurationService(session).preview(data)


@router.post("/configuration-assignments", response_model=PayrollAssignmentOut, status_code=status.HTTP_201_CREATED, dependencies=ASSIGN, summary="Create an assignment")
async def create_assignment(data: PayrollAssignmentIn, session: DbSession):
    return await PayrollConfigurationService(session).create(data)


@router.post("/configuration-assignments/{assignment_id}/end", response_model=PayrollAssignmentOut, dependencies=ASSIGN, summary="End an assignment")
async def end_assignment(assignment_id: str, data: AssignmentEndIn, session: DbSession):
    return await PayrollConfigurationService(session).end(path_id(assignment_id), data)


@router.get("/employees/{employee_id}/effective-configuration", response_model=EffectiveConfigurationOut, dependencies=VIEW, summary="The configuration that applies to an employee on a date")
async def effective_configuration(employee_id: str, session: DbSession, date: Annotated[str | None, Query()] = None):
    return await PayrollConfigurationService(session).effective(path_id(employee_id), _date(date, "date"))


# ---- HR setup (additions) ----------------------------------------------------------------------------------------------


@setup_router.get("/salary-components", response_model=list[SalaryComponentSetupOut], dependencies=CONFIG, summary="Salary components with their formula settings")
async def setup_components(session: DbSession):
    return await PayrollSetupService(session).components(setup=True)


@setup_router.post("/salary-components", response_model=SalaryComponentSetupOut, status_code=status.HTTP_201_CREATED, dependencies=CONFIG, summary="Create a salary component")
async def create_component(data: SalaryComponentIn, session: DbSession):
    return await PayrollSetupService(session).save_component(None, data)


@setup_router.put("/salary-components/{component_id}", response_model=SalaryComponentSetupOut, dependencies=CONFIG, summary="Update a salary component (code never changes)")
async def update_component(component_id: str, data: SalaryComponentIn, session: DbSession):
    return await PayrollSetupService(session).save_component(path_id(component_id), data)


@setup_router.post("/salary-structures", response_model=SalaryStructureOut, status_code=status.HTTP_201_CREATED, dependencies=CONFIG, summary="Create a salary structure")
async def create_structure(data: SalaryStructureIn, session: DbSession):
    return await PayrollSetupService(session).save_structure(None, data)


@setup_router.put("/salary-structures/{structure_id}", response_model=SalaryStructureOut, dependencies=CONFIG, summary="Update a salary structure")
async def update_structure(structure_id: str, data: SalaryStructureIn, session: DbSession):
    return await PayrollSetupService(session).save_structure(path_id(structure_id), data)


@setup_router.post("/employee-salaries", response_model=EmployeeSalaryDetailOut, status_code=status.HTTP_201_CREATED, dependencies=[*CONFIG, *AMOUNTS],
                   summary="Record an employee's salary from a date (append-only)")
async def add_salary(data: EmployeeSalaryIn, session: DbSession, principal: CurrentPrincipal):
    caller = await caller_context(session, principal)
    return await PayrollSetupService(session, caller).add_salary(data, caller)


@setup_router.post("/payroll-periods", response_model=PayrollPeriodOut, status_code=status.HTTP_201_CREATED, dependencies=PROCESS, summary="Open a payroll period (month and currency)")
async def create_period(data: PayrollPeriodIn, session: DbSession):
    return await PayrollSetupService(session).create_period(data)
