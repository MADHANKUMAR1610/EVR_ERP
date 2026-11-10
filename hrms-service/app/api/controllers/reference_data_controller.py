"""Reference lists for the HR forms (frontend referenceData.http.ts). Plain arrays, not paged.

Each list is limited to the permissions of the screens that use it (app/core/reference_access.py),
and returns only the fields those screens need.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import CurrentPrincipal, DbSession, get_audit_session_factory, require
from app.core import reference_access as RA
from app.core.errors import ForbiddenError
from app.core.permissions import has_any
from app.models.reference_data_model import AttendancePolicyOption, EmploymentType, OvertimePolicyOption, WorkLocation
from app.schemas.reference_data_schema import DocumentTypeOption, EmployeeStatusOption, OptionItem, PayrollFieldDefinitionOut, ReferenceItem
from app.services.audit_service import record_denial
from app.services.reference_data_service import ReferenceDataService
from app.services.employee_scope_service import caller_employee_id
from app.services.shift_service import ShiftService

router = APIRouter(prefix="/hr", tags=["Reference data"])


def _needs(codes: frozenset[str]) -> list:
    return [Depends(require(*sorted(codes)))]


async def department_access(request: Request, principal: CurrentPrincipal, factory=Depends(get_audit_session_factory)) -> str:
    """'all' for the screens that use the full list, 'self' for self-service callers; otherwise an audited 403."""
    if has_any(principal.permissions, RA.DEPARTMENTS):
        return "all"
    if has_any(principal.permissions, RA.DEPARTMENTS_SELF):
        return "self"
    await record_denial(factory, principal, " or ".join(sorted(RA.DEPARTMENTS | RA.DEPARTMENTS_SELF)), request.url.path)
    raise ForbiddenError()


@router.get("/departments", response_model=list[ReferenceItem], summary="Departments (including inactive)")
async def departments(access: Annotated[str, Depends(department_access)], session: DbSession, principal: CurrentPrincipal):
    if access == "all":
        return await ReferenceDataService(session).departments()
    # Self-service: only the caller's own department (from their employee record).
    return await ReferenceDataService(session).own_department(caller_employee_id(principal))


@router.get("/designations", response_model=list[ReferenceItem], dependencies=_needs(RA.DESIGNATIONS), summary="Designations (including inactive)")
async def designations(session: DbSession):
    return await ReferenceDataService(session).designations()


@router.get("/employment-types", response_model=list[ReferenceItem], dependencies=_needs(RA.EMPLOYMENT_TYPES), summary="Employment types")
async def employment_types(session: DbSession):
    return await ReferenceDataService(session).coded_items(EmploymentType)


@router.get("/work-locations", response_model=list[ReferenceItem], dependencies=_needs(RA.WORK_LOCATIONS), summary="Work locations")
async def work_locations(session: DbSession):
    return await ReferenceDataService(session).coded_items(WorkLocation)


@router.get("/employee-statuses", response_model=list[EmployeeStatusOption], dependencies=_needs(RA.EMPLOYEE_STATUSES), summary="Employee statuses (transitions only for status changers)")
async def employee_statuses(session: DbSession, principal: CurrentPrincipal):
    return await ReferenceDataService(session).employee_statuses(include_transitions=has_any(principal.permissions, RA.EMPLOYEE_STATUS_TRANSITIONS))


@router.get("/shifts/options", response_model=list[OptionItem], dependencies=_needs(RA.SHIFT_OPTIONS), summary="Active shifts for the employee form")
async def shift_options(session: DbSession):
    return await ShiftService(session).options()


@router.get("/attendance-policies/options", response_model=list[OptionItem], dependencies=_needs(RA.ATTENDANCE_POLICY_OPTIONS), summary="Active attendance policies")
async def attendance_policy_options(session: DbSession):
    return await ReferenceDataService(session).policy_options(AttendancePolicyOption)


@router.get("/overtime-policies/options", response_model=list[OptionItem], dependencies=_needs(RA.OVERTIME_POLICY_OPTIONS), summary="Active overtime policies")
async def overtime_policy_options(session: DbSession):
    return await ReferenceDataService(session).policy_options(OvertimePolicyOption)


@router.get("/document-types", response_model=list[DocumentTypeOption], dependencies=_needs(RA.DOCUMENT_TYPES), summary="Employee document types and upload rules")
async def document_types(session: DbSession):
    return await ReferenceDataService(session).document_types()


@router.get("/employees/payroll-fields", response_model=list[PayrollFieldDefinitionOut], dependencies=_needs(RA.PAYROLL_FIELDS), summary="Payroll field definitions for the employee form")
async def payroll_fields(session: DbSession):
    return await ReferenceDataService(session).payroll_fields()
