"""Administration → Organization: departments (frontend admin.http.ts)."""

from fastapi import APIRouter, Depends, status

from app.api.dependencies import DbSession, require
from app.core.permissions import A
from app.schemas.department_schema import DepartmentInput, DepartmentOut
from app.services.department_service import DepartmentService
from app.utils.ids import path_id

router = APIRouter(prefix="/admin/departments", tags=["Organization"])


@router.get("", response_model=list[DepartmentOut], dependencies=[Depends(require(A.ORGANIZATION_VIEW, A.ORGANIZATION_MANAGE))])
async def list_departments(session: DbSession):
    return await DepartmentService(session).list()


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(A.ORGANIZATION_MANAGE))])
async def create_department(data: DepartmentInput, session: DbSession):
    return await DepartmentService(session).create(data)


@router.put("/{department_id}", response_model=DepartmentOut, dependencies=[Depends(require(A.ORGANIZATION_MANAGE))])
async def update_department(department_id: str, data: DepartmentInput, session: DbSession):
    return await DepartmentService(session).update(path_id(department_id), data)
