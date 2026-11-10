"""HR → Time & Attendance (frontend attendance.http.ts, contract E1 / H1 / H2)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.api.dependencies import CurrentPrincipal, DbSession, require
from app.core.errors import LengthRequiredError, PayloadTooLargeError
from app.core.permissions import P
from app.models.attendance_model import AttendanceDevice
from app.schemas.attendance_schema import (
    AttendanceEventDetailOut,
    AttendanceEventOut,
    CalendarOut,
    CorrectionIn,
    CorrectionOut,
    DailyDetailOut,
    DailyRecordOut,
    DecisionIn,
    DeviceListOut,
    DeviceSyncRunOut,
    IngestIn,
    IngestOut,
    MonthlyDetailOut,
    MonthlyRowOut,
    ShiftAssignmentIn,
    ShiftAssignmentOut,
    SummaryOut,
)
from app.schemas.common import Page, PageParams, page_params
from app.services.attendance.attendance_read_service import AttendanceReadService
from app.services.attendance.correction_service import CorrectionService
from app.services.attendance.device_service import DeviceService
from app.services.attendance.shift_assignment_service import ShiftAssignmentService
from app.services.employee_support import caller_context
from app.utils.ids import path_id

router = APIRouter(prefix="/hr/attendance", tags=["Attendance"])
shifts_router = APIRouter(prefix="/hr/shifts", tags=["Shifts"])
devices_router = APIRouter(prefix="/hr/attendance-devices", tags=["Attendance devices"])
Params = Annotated[PageParams, Depends(page_params)]
VIEW = [Depends(require(P.ATTENDANCE_VIEW))]


async def _read(session, principal) -> AttendanceReadService:
    return AttendanceReadService(session, await caller_context(session, principal))


async def _corrections(session, principal) -> CorrectionService:
    return CorrectionService(session, await caller_context(session, principal))


# ---- Registers -----------------------------------------------------------------------------------------


@router.get("/summary", response_model=SummaryOut, dependencies=VIEW, summary="Attendance overview for a day")
async def summary(session: DbSession, principal: CurrentPrincipal, date: Annotated[str | None, Query()] = None):
    return await (await _read(session, principal)).summary(date)


@router.get("/daily", response_model=Page[DailyRecordOut], dependencies=VIEW, summary="Daily register")
async def daily(
    session: DbSession, principal: CurrentPrincipal, params: Params, date: Annotated[str | None, Query()] = None,
    department_id: Annotated[str | None, Query(alias="departmentId")] = None, shift_id: Annotated[str | None, Query(alias="shiftId")] = None,
    status_: Annotated[str | None, Query(alias="status")] = None, exceptions_only: Annotated[bool, Query(alias="exceptionsOnly")] = False,
    source: Annotated[Literal["fingerprint", "mobile_app", "correction"] | None, Query()] = None, warnings_only: Annotated[bool, Query(alias="warningsOnly")] = False,
):
    return await (await _read(session, principal)).daily(params, day=date, department_id=department_id, shift_id=shift_id, status=status_, exceptions_only=exceptions_only, source=source, warnings_only=warnings_only)


@router.get("/daily/{employee_id}", response_model=DailyDetailOut, summary="One employee's day (attendance view in scope, own record, or direct report)")
async def daily_detail(employee_id: str, session: DbSession, principal: CurrentPrincipal, date: Annotated[str | None, Query()] = None):
    return await (await _read(session, principal)).daily_detail(path_id(employee_id), date)


@router.get("/monthly", response_model=Page[MonthlyRowOut], dependencies=VIEW, summary="Monthly register")
async def monthly(session: DbSession, principal: CurrentPrincipal, params: Params, month: Annotated[str | None, Query()] = None, department_id: Annotated[str | None, Query(alias="departmentId")] = None):
    return await (await _read(session, principal)).monthly(params, month=month, department_id=department_id)


@router.get("/monthly/export", dependencies=VIEW, summary="Monthly register as CSV (default) or XLSX", responses={200: {"content": {"text/csv": {}, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
async def monthly_export(
    session: DbSession, principal: CurrentPrincipal, month: Annotated[str | None, Query()] = None, department_id: Annotated[str | None, Query(alias="departmentId")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None, employee_id: Annotated[str | None, Query(alias="employeeId")] = None, format: Annotated[Literal["csv", "xlsx"], Query()] = "csv",
) -> Response:
    content, media_type, name = await (await _read(session, principal)).export(month=month, department_id=department_id, q=q, employee_id=employee_id, fmt=format)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.get("/monthly/{employee_id}", response_model=MonthlyDetailOut, summary="One employee's month")
async def monthly_detail(employee_id: str, session: DbSession, principal: CurrentPrincipal, month: Annotated[str | None, Query()] = None):
    return await (await _read(session, principal)).monthly_detail(path_id(employee_id), month)


@router.get("/employees/{employee_id}/calendar", response_model=CalendarOut, summary="One employee's attendance calendar (H1)")
async def calendar(employee_id: str, session: DbSession, principal: CurrentPrincipal, month: Annotated[str | None, Query()] = None):
    return await (await _read(session, principal)).calendar(path_id(employee_id), month)


# ---- Events -----------------------------------------------------------------------------------------------


async def authenticated_device(request: Request, session: DbSession, x_device_key: Annotated[str | None, Header(alias="X-Device-Key")] = None) -> AttendanceDevice:
    """Runs before the body is read: no key, a wrong key or a revoked key is 401 whatever the body holds."""
    device = await DeviceService(session).authenticate(x_device_key)
    length = request.headers.get("content-length", "")
    if not length.isdigit():
        raise LengthRequiredError()
    if int(length) > 1024 * 1024:
        raise PayloadTooLargeError("Send at most 1 MB (1,000 punches) per request.")
    return device


@router.post("/events/ingest", response_model=IngestOut, status_code=status.HTTP_201_CREATED, summary="Devices push punches (X-Device-Key; not for user tokens)")
async def ingest(device: Annotated[AttendanceDevice, Depends(authenticated_device)], data: IngestIn, session: DbSession):
    return await DeviceService(session).ingest(device, data)


@router.get("/events", response_model=Page[AttendanceEventOut], dependencies=VIEW, summary="Raw punches received for a date")
async def events(
    session: DbSession, principal: CurrentPrincipal, params: Params, date: Annotated[str | None, Query()] = None, department_id: Annotated[str | None, Query(alias="departmentId")] = None,
    employee_id: Annotated[str | None, Query(alias="employeeId")] = None, source: Annotated[Literal["fingerprint", "mobile_app"] | None, Query()] = None,
    sync_status: Annotated[Literal["synced", "pending", "delayed", "failed"] | None, Query(alias="syncStatus")] = None, exceptions: Annotated[Literal["with", "without"] | None, Query()] = None,
):
    return await (await _read(session, principal)).events(params, day=date, department_id=department_id, employee_id=employee_id, source=source, sync_status=sync_status, exceptions=exceptions)


@router.get("/events/{event_id}", response_model=AttendanceEventDetailOut, dependencies=VIEW, summary="One punch and its day record")
async def event(event_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _read(session, principal)).event(path_id(event_id))


# ---- Corrections --------------------------------------------------------------------------------------------


@router.get("/corrections", response_model=Page[CorrectionOut], dependencies=[Depends(require(P.ATTENDANCE_CORRECTIONS_VIEW))], summary="Correction requests (scoped)")
async def corrections(session: DbSession, principal: CurrentPrincipal, params: Params, status_: Annotated[Literal["pending", "approved", "rejected", "cancelled"] | None, Query(alias="status")] = None, department_id: Annotated[str | None, Query(alias="departmentId")] = None):
    return await (await _corrections(session, principal)).list(params, status=status_, department_id=department_id)


@router.get("/corrections/{correction_id}", response_model=CorrectionOut, summary="One correction request and its history")
async def correction(correction_id: str, session: DbSession, principal: CurrentPrincipal):
    return await (await _corrections(session, principal)).get(path_id(correction_id))


@router.post("/corrections", response_model=CorrectionOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(P.ATTENDANCE_CORRECTIONS_SUBMIT, P.SELF_SUBMIT_REQUESTS))], summary="Request a correction")
async def submit_correction(data: CorrectionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _corrections(session, principal)).submit(data)


@router.post("/corrections/{correction_id}/decision", response_model=CorrectionOut, dependencies=[Depends(require(P.ATTENDANCE_CORRECTIONS_APPROVE, P.APPROVALS_ACT))], summary="Approve or reject (workflow step approver, or HR oversight)")
async def decide_correction(correction_id: str, data: DecisionIn, session: DbSession, principal: CurrentPrincipal):
    return await (await _corrections(session, principal)).decide(path_id(correction_id), data)


# ---- Shift assignments and devices ----------------------------------------------------------------------------


@shifts_router.post("/{shift_id}/assignments", response_model=ShiftAssignmentOut, dependencies=[Depends(require(P.SHIFTS_ASSIGN))], summary="Assign a shift from a date (dated history)")
async def assign_shift(shift_id: str, data: ShiftAssignmentIn, session: DbSession, principal: CurrentPrincipal):
    return await ShiftAssignmentService(session, await caller_context(session, principal)).assign(path_id(shift_id), data)


@devices_router.get("", response_model=DeviceListOut, dependencies=[Depends(require(P.DEVICES_VIEW))], summary="Attendance devices (read-only)")
async def devices(session: DbSession):
    return await DeviceService(session).list()


@devices_router.get("/{device_id}/sync-history", response_model=list[DeviceSyncRunOut], dependencies=[Depends(require(P.DEVICES_VIEW))], summary="Recent synchronization runs")
async def sync_history(device_id: str, session: DbSession):
    return await DeviceService(session).sync_history(path_id(device_id))
