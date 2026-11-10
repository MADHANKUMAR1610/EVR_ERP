"""HR → Shift Management: shift master data (frontend attendance.http.ts). Assignments come later."""

from fastapi import APIRouter, Depends, status

from app.api.dependencies import DbSession, require
from app.core.permissions import P
from app.schemas.shift_schema import ShiftInput, ShiftOut
from app.services.shift_service import ShiftService
from app.utils.ids import path_id

router = APIRouter(prefix="/hr/shifts", tags=["Shifts"])


@router.get("", response_model=list[ShiftOut], dependencies=[Depends(require(P.SHIFTS_VIEW, P.SHIFTS_MANAGE))])
async def list_shifts(session: DbSession):
    return await ShiftService(session).list()


@router.post("", response_model=ShiftOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(P.SHIFTS_MANAGE))])
async def create_shift(data: ShiftInput, session: DbSession):
    return await ShiftService(session).create(data)


@router.put("/{shift_id}", response_model=ShiftOut, dependencies=[Depends(require(P.SHIFTS_MANAGE))])
async def update_shift(shift_id: str, data: ShiftInput, session: DbSession):
    return await ShiftService(session).update(path_id(shift_id), data)
