"""HR setup for leave (additions without a frontend screen; hr.leave-policies:manage):
leave types, leave policies, holidays, balance allocations and adjustments, the balance ledger,
and the notification outbox status."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.permissions import P
from app.repositories.base_repository import PageResult
from app.schemas.common import Page, PageParams, page_params
from app.schemas.leave_schema import HolidayIn, HolidaySetupOut, LeavePolicyIn, LeavePolicySetupOut, LeaveTypeIn, LeaveTypeOut, LedgerEntryIn, LedgerEntryOut, NotificationOutboxOut
from app.services.employee_support import caller_context
from app.services.leave.notifications import outbox_status
from app.services.leave.setup_service import LeaveSetupService
from app.utils.ids import path_id

router = APIRouter(prefix="/hr/setup", tags=["HR setup"])
MANAGE = [Depends(require(P.LEAVE_POLICIES_MANAGE))]
Params = Annotated[PageParams, Depends(page_params)]


@router.get("/leave-types", response_model=list[LeaveTypeOut], dependencies=MANAGE)
async def leave_types(session: DbSession):
    return await LeaveSetupService(session).leave_types()


@router.post("/leave-types", response_model=LeaveTypeOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
async def create_leave_type(data: LeaveTypeIn, session: DbSession):
    return await LeaveSetupService(session).save_type(None, data)


@router.put("/leave-types/{type_id}", response_model=LeaveTypeOut, dependencies=MANAGE)
async def update_leave_type(type_id: str, data: LeaveTypeIn, session: DbSession):
    return await LeaveSetupService(session).save_type(path_id(type_id), data)


@router.get("/leave-policies", response_model=list[LeavePolicySetupOut], dependencies=MANAGE)
async def leave_policies(session: DbSession):
    return await LeaveSetupService(session).policies(setup=True)


@router.post("/leave-policies", response_model=LeavePolicySetupOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
async def create_leave_policy(data: LeavePolicyIn, session: DbSession):
    return await LeaveSetupService(session).save_policy(None, data)


@router.put("/leave-policies/{policy_id}", response_model=LeavePolicySetupOut, dependencies=MANAGE)
async def update_leave_policy(policy_id: str, data: LeavePolicyIn, session: DbSession):
    return await LeaveSetupService(session).save_policy(path_id(policy_id), data)


@router.get("/holidays", response_model=list[HolidaySetupOut], dependencies=MANAGE)
async def holidays(session: DbSession, year: Annotated[int | None, Query(ge=2000, le=2100)] = None):
    return await LeaveSetupService(session).holidays_setup(year)


@router.post("/holidays", response_model=HolidaySetupOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE)
async def create_holiday(data: HolidayIn, session: DbSession):
    return await LeaveSetupService(session).save_holiday(None, data)


@router.put("/holidays/{holiday_id}", response_model=HolidaySetupOut, dependencies=MANAGE)
async def update_holiday(holiday_id: str, data: HolidayIn, session: DbSession):
    return await LeaveSetupService(session).save_holiday(path_id(holiday_id), data)


@router.delete("/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=MANAGE)
async def delete_holiday(holiday_id: str, session: DbSession) -> Response:
    await LeaveSetupService(session).delete_holiday(path_id(holiday_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/leave-allocations", response_model=LedgerEntryOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE, summary="Credit days to an employee's balance (with a reason)")
async def allocate(data: LedgerEntryIn, session: DbSession, principal: CurrentPrincipal):
    return await LeaveSetupService(session).add_entry("allocation", data, await caller_context(session, principal))


@router.post("/leave-adjustments", response_model=LedgerEntryOut, status_code=status.HTTP_201_CREATED, dependencies=MANAGE, summary="Correct a balance (+/- days, with a reason)")
async def adjust(data: LedgerEntryIn, session: DbSession, principal: CurrentPrincipal):
    return await LeaveSetupService(session).add_entry("adjustment", data, await caller_context(session, principal))


@router.get("/leave-ledger", response_model=Page[LedgerEntryOut], dependencies=MANAGE, summary="Balance transactions (append-only), newest first")
async def ledger(session: DbSession, principal: CurrentPrincipal, params: Params, employee_id: Annotated[str | None, Query(alias="employeeId")] = None,
                 leave_type_id: Annotated[str | None, Query(alias="leaveTypeId")] = None, year: Annotated[int | None, Query(ge=2000, le=2100)] = None):
    total, items = await LeaveSetupService(session).ledger(await caller_context(session, principal), employee_id=employee_id, leave_type_id=leave_type_id, year=year, page=params.page, page_size=params.page_size)
    return Page.build(PageResult(items, params.page, params.page_size, total), items)


@router.get("/notification-outbox", response_model=NotificationOutboxOut, dependencies=[Depends(require(P.LEAVE_POLICIES_MANAGE, P.INTEGRATIONS_MANAGE))], summary="Notification queue status")
async def notification_outbox(session: DbSession):
    return await outbox_status(session)
