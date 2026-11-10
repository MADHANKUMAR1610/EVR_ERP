"""/hr/setup: HR maintains the reference lists (employment types, locations, policies, document
categories and types, employee statuses, payroll fields). Read: hr.settings:view or manage. Write: manage.
"""

from fastapi import APIRouter, Depends, status

from app.api.dependencies import DbSession, require
from app.core.permissions import P
from app.schemas.reference_data_schema import (
    CodedItemInput,
    CodedItemSetupOut,
    DocumentTypeInput,
    DocumentTypeSetupOut,
    EmployeeStatusInput,
    EmployeeStatusSetupOut,
    PayrollFieldInput,
    PayrollFieldSetupOut,
)
from app.services.reference_data_service import ReferenceDataService
from app.utils.ids import path_id

router = APIRouter(prefix="/hr/setup", tags=["HR setup"])
view = [Depends(require(P.SETTINGS_VIEW, P.SETTINGS_MANAGE))]
manage = [Depends(require(P.SETTINGS_MANAGE))]

# Specific lists first, so they are not taken by the generic /{kind} routes below.


@router.get("/employee-statuses", response_model=list[EmployeeStatusSetupOut], dependencies=view)
async def list_statuses(session: DbSession):
    return await ReferenceDataService(session).setup_list_statuses()


@router.post("/employee-statuses", response_model=EmployeeStatusSetupOut, status_code=status.HTTP_201_CREATED, dependencies=manage)
async def create_status(data: EmployeeStatusInput, session: DbSession):
    return await ReferenceDataService(session).setup_create_status(data)


@router.put("/employee-statuses/{status_id}", response_model=EmployeeStatusSetupOut, dependencies=manage)
async def update_status(status_id: str, data: EmployeeStatusInput, session: DbSession):
    return await ReferenceDataService(session).setup_update_status(path_id(status_id), data)


@router.get("/document-types", response_model=list[DocumentTypeSetupOut], dependencies=view)
async def list_document_types(session: DbSession):
    return await ReferenceDataService(session).setup_list_document_types()


@router.post("/document-types", response_model=DocumentTypeSetupOut, status_code=status.HTTP_201_CREATED, dependencies=manage)
async def create_document_type(data: DocumentTypeInput, session: DbSession):
    return await ReferenceDataService(session).setup_create_document_type(data)


@router.put("/document-types/{type_id}", response_model=DocumentTypeSetupOut, dependencies=manage)
async def update_document_type(type_id: str, data: DocumentTypeInput, session: DbSession):
    return await ReferenceDataService(session).setup_update_document_type(path_id(type_id), data)


@router.get("/payroll-fields", response_model=list[PayrollFieldSetupOut], dependencies=view)
async def list_payroll_fields(session: DbSession):
    return await ReferenceDataService(session).setup_list_payroll_fields()


@router.post("/payroll-fields", response_model=PayrollFieldSetupOut, status_code=status.HTTP_201_CREATED, dependencies=manage)
async def create_payroll_field(data: PayrollFieldInput, session: DbSession):
    return await ReferenceDataService(session).setup_create_payroll_field(data)


@router.put("/payroll-fields/{field_id}", response_model=PayrollFieldSetupOut, dependencies=manage)
async def update_payroll_field(field_id: str, data: PayrollFieldInput, session: DbSession):
    return await ReferenceDataService(session).setup_update_payroll_field(path_id(field_id), data)


# employment-types, work-locations, attendance-policies, overtime-policies, document-categories


@router.get("/{kind}", response_model=list[CodedItemSetupOut], dependencies=view)
async def list_coded(kind: str, session: DbSession):
    return await ReferenceDataService(session).setup_list_coded(kind)


@router.post("/{kind}", response_model=CodedItemSetupOut, status_code=status.HTTP_201_CREATED, dependencies=manage)
async def create_coded(kind: str, data: CodedItemInput, session: DbSession):
    return await ReferenceDataService(session).setup_create_coded(kind, data)


@router.put("/{kind}/{item_id}", response_model=CodedItemSetupOut, dependencies=manage)
async def update_coded(kind: str, item_id: str, data: CodedItemInput, session: DbSession):
    return await ReferenceDataService(session).setup_update_coded(kind, path_id(item_id), data)
