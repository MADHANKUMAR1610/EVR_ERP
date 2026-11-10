"""Administration → Organization: designations (frontend admin.http.ts)."""

from fastapi import APIRouter, Depends, status

from app.api.dependencies import DbSession, require
from app.core.permissions import A
from app.schemas.designation_schema import DesignationInput, DesignationOut
from app.services.designation_service import DesignationService
from app.utils.ids import path_id

router = APIRouter(prefix="/admin/designations", tags=["Organization"])


@router.get("", response_model=list[DesignationOut], dependencies=[Depends(require(A.ORGANIZATION_VIEW, A.ORGANIZATION_MANAGE))])
async def list_designations(session: DbSession):
    return await DesignationService(session).list()


@router.post("", response_model=DesignationOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(A.ORGANIZATION_MANAGE))])
async def create_designation(data: DesignationInput, session: DbSession):
    return await DesignationService(session).create(data)


@router.put("/{designation_id}", response_model=DesignationOut, dependencies=[Depends(require(A.ORGANIZATION_MANAGE))])
async def update_designation(designation_id: str, data: DesignationInput, session: DbSession):
    return await DesignationService(session).update(path_id(designation_id), data)
