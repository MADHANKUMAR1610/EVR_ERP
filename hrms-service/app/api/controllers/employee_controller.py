"""HR → Employees (frontend employees.http.ts, contract B4)."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import CurrentPrincipal, DbSession, get_audit_session_factory, require
from app.core import reference_access as RA
from app.core.context import Principal
from app.core.errors import ForbiddenError
from app.core.permissions import P
from app.schemas.common import Page, PageParams, page_params
from app.schemas.employee_schema import EmployeeListItemOut, EmployeeLookupItemOut, EmployeeOut, EmployeeUpsertIn, HistoryEntryOut, StatusChangeIn
from app.services.audit_service import record_denial
from app.services.employee_service import EmployeeService
from app.services.employee_support import caller_context
from app.utils.ids import path_id

router = APIRouter(prefix="/hr/employees", tags=["Employees"])
AuditFactory = Annotated[async_sessionmaker[AsyncSession], Depends(get_audit_session_factory)]


def _deny(request: Request, principal: Principal, factory: async_sessionmaker[AsyncSession]) -> Callable[[str], Awaitable[None]]:
    """For permission checks that depend on the request body or the record (audited like require())."""

    async def deny(required: str) -> None:
        await record_denial(factory, principal, required, request.url.path)
        raise ForbiddenError()

    return deny


async def _service(session, principal) -> EmployeeService:
    return EmployeeService(session, await caller_context(session, principal))


@router.get("", response_model=Page[EmployeeListItemOut], dependencies=[Depends(require(P.EMPLOYEES_VIEW))], summary="Employee directory (scoped)")
async def directory(
    session: DbSession,
    principal: CurrentPrincipal,
    params: Annotated[PageParams, Depends(page_params)],
    department_id: Annotated[str | None, Query(alias="departmentId")] = None,
    designation_id: Annotated[str | None, Query(alias="designationId")] = None,
    employment_type_id: Annotated[str | None, Query(alias="employmentTypeId")] = None,
    status_code: Annotated[str | None, Query(alias="status", max_length=30)] = None,
):
    return await (await _service(session, principal)).directory(params, department_id=department_id, designation_id=designation_id, employment_type_id=employment_type_id, status=status_code)


@router.get("/lookup", response_model=list[EmployeeLookupItemOut], dependencies=[Depends(require(*sorted(RA.EMPLOYEE_LOOKUP)))], summary="Employee picker search (scoped, 4 fields)")
async def lookup(
    session: DbSession,
    principal: CurrentPrincipal,
    q: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 10,
    exclude_id: Annotated[str | None, Query(alias="excludeId")] = None,
):
    return await (await _service(session, principal)).lookup(q, limit, exclude_id)


@router.post("", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(P.EMPLOYEES_CREATE))], summary="Add an employee")
async def create(data: EmployeeUpsertIn, request: Request, session: DbSession, principal: CurrentPrincipal, factory: AuditFactory):
    return await (await _service(session, principal)).create(data, _deny(request, principal, factory))


@router.get("/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require(P.EMPLOYEES_VIEW))], summary="Employee record (scoped; contact and payroll by permission)")
async def get(employee_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).get(path_id(employee_id))


@router.patch("/{employee_id}", response_model=EmployeeOut, dependencies=[Depends(require(P.EMPLOYEES_EDIT))], summary="Update an employee")
async def update(employee_id: str, data: EmployeeUpsertIn, request: Request, session: DbSession, principal: CurrentPrincipal, factory: AuditFactory):
    return await (await _service(session, principal)).update(path_id(employee_id), data, _deny(request, principal, factory))


@router.post("/{employee_id}/status-changes", response_model=EmployeeOut, dependencies=[Depends(require(P.EMPLOYEES_CHANGE_STATUS))], summary="Record a status change")
async def change_status(employee_id: str, data: StatusChangeIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _service(session, principal)).change_status(path_id(employee_id), data)


@router.get("/{employee_id}/history", response_model=Page[HistoryEntryOut], dependencies=[Depends(require(P.EMPLOYEES_VIEW))], summary="Employee history (section names only)")
async def history(employee_id: str, session: DbSession, principal: CurrentPrincipal, params: Annotated[PageParams, Depends(page_params)]):
    return await (await _service(session, principal)).history(path_id(employee_id), params.page, params.page_size)
