"""Configuration for Module 5:
- HR policies `attendance`, `shifts`, `overtime` (contract G6, /admin/policies/{area});
- approval workflows (contract G5, /admin/workflow-processes, /admin/workflows);
- attendance device setup and API keys (/hr/setup/attendance-devices, hr.devices:manage);
- attendance period locks (/hr/setup/attendance-period-locks, hr.payroll:approve, until payroll exists).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import CurrentPrincipal, DbSession, get_audit_session_factory, require
from app.core.errors import ForbiddenError
from app.core.permissions import A, P, has_permission
from app.schemas.attendance_schema import DeviceKeyOut, DeviceSetupIn, DeviceSetupOut, LockIn, LockOut
from app.schemas.policy_schema import PolicyDocumentOut, PolicySaveIn
from app.schemas.workflow_schema import ProcessDefinitionOut, WorkflowActionIn, WorkflowIn, WorkflowOut
from app.services.attendance.device_service import DeviceService
from app.services.attendance.lock_service import LockService
from app.services.attendance.policy_service import MANAGE_PERMISSION, PolicyService
from app.services.attendance.workflow_service import WorkflowService
from app.services.audit_service import record_denial
from app.utils.ids import path_id

policies_router = APIRouter(prefix="/admin/policies", tags=["HR policies"])
workflows_router = APIRouter(prefix="/admin", tags=["Approval workflows"])
setup_router = APIRouter(prefix="/hr/setup", tags=["HR setup"])


@policies_router.get("/{area}", response_model=PolicyDocumentOut, dependencies=[Depends(require(A.POLICIES_VIEW, A.POLICIES_MANAGE, A.POLICIES_PAYROLL_MANAGE))])
async def get_policy(area: str, session: DbSession):
    return await PolicyService(session).get(area)


@policies_router.put("/{area}", response_model=PolicyDocumentOut, dependencies=[Depends(require(A.POLICIES_MANAGE, A.POLICIES_PAYROLL_MANAGE))])
async def save_policy(area: str, data: PolicySaveIn, request: Request, session: DbSession, principal: CurrentPrincipal,
                      factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_audit_session_factory)]):
    required = MANAGE_PERMISSION.get(area)
    if required and not has_permission(principal.permissions, required):
        # G6: pay-affecting areas (attendance) need admin:policies.payroll-manage.
        await record_denial(factory, principal, required, request.url.path)
        raise ForbiddenError()
    return await PolicyService(session).save(area, data)


@workflows_router.get("/workflow-processes", response_model=list[ProcessDefinitionOut], dependencies=[Depends(require(A.WORKFLOWS_VIEW, A.WORKFLOWS_MANAGE))])
async def processes():
    return WorkflowService.processes()


@workflows_router.get("/workflows", response_model=list[WorkflowOut], dependencies=[Depends(require(A.WORKFLOWS_VIEW, A.WORKFLOWS_MANAGE))])
async def workflows(session: DbSession):
    return await WorkflowService(session).list()


@workflows_router.get("/workflows/{workflow_id}", response_model=WorkflowOut, dependencies=[Depends(require(A.WORKFLOWS_VIEW, A.WORKFLOWS_MANAGE))])
async def workflow(workflow_id: str, session: DbSession):
    return await WorkflowService(session).get(path_id(workflow_id))


@workflows_router.post("/workflows", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(A.WORKFLOWS_MANAGE))])
async def create_workflow(data: WorkflowIn, session: DbSession):
    return await WorkflowService(session).save(None, data)


@workflows_router.put("/workflows/{workflow_id}", response_model=WorkflowOut, dependencies=[Depends(require(A.WORKFLOWS_MANAGE))])
async def update_workflow(workflow_id: str, data: WorkflowIn, session: DbSession):
    return await WorkflowService(session).save(path_id(workflow_id), data)


@workflows_router.post("/workflows/{workflow_id}/publication", response_model=WorkflowOut, dependencies=[Depends(require(A.WORKFLOWS_PUBLISH))])
async def publish_workflow(workflow_id: str, data: WorkflowActionIn, session: DbSession):
    return await WorkflowService(session).publish(path_id(workflow_id), data.version, data.note)


@workflows_router.post("/workflows/{workflow_id}/archive", response_model=WorkflowOut, dependencies=[Depends(require(A.WORKFLOWS_PUBLISH))])
async def archive_workflow(workflow_id: str, data: WorkflowActionIn, session: DbSession):
    return await WorkflowService(session).archive(path_id(workflow_id), data.version, data.note)


@setup_router.get("/attendance-devices", response_model=list[DeviceSetupOut], dependencies=[Depends(require(P.DEVICES_MANAGE))])
async def setup_devices(session: DbSession):
    return await DeviceService(session).setup_list()


@setup_router.post("/attendance-devices", response_model=DeviceSetupOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(P.DEVICES_MANAGE))])
async def create_device(data: DeviceSetupIn, session: DbSession):
    return await DeviceService(session).save(None, data)


@setup_router.put("/attendance-devices/{device_id}", response_model=DeviceSetupOut, dependencies=[Depends(require(P.DEVICES_MANAGE))])
async def update_device(device_id: str, data: DeviceSetupIn, session: DbSession):
    return await DeviceService(session).save(path_id(device_id), data)


@setup_router.post("/attendance-devices/{device_id}/key", response_model=DeviceKeyOut, dependencies=[Depends(require(P.DEVICES_MANAGE))], summary="Issue a new device API key (shown once)")
async def issue_device_key(device_id: str, session: DbSession):
    return await DeviceService(session).issue_key(path_id(device_id))


@setup_router.get("/attendance-period-locks", response_model=list[LockOut], dependencies=[Depends(require(P.PAYROLL_APPROVE, P.ATTENDANCE_VIEW))])
async def locks(session: DbSession):
    return await LockService(session).list()


@setup_router.post("/attendance-period-locks", response_model=LockOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require(P.PAYROLL_APPROVE))], summary="Lock finished dates (finalized payroll)")
async def create_lock(data: LockIn, session: DbSession):
    return await LockService(session).create(data)
