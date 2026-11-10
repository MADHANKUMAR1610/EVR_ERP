"""Departments (frontend `admin.service.ts`: Department, DepartmentInput)."""

from pydantic import Field

from app.schemas.common import CamelModel, ResponseModel


class EmployeeNameRef(ResponseModel):
    id: str
    full_name: str


class DepartmentRef(ResponseModel):
    id: str
    name: str


class DepartmentOut(ResponseModel):
    id: str
    code: str
    name: str
    head: EmployeeNameRef | None
    parent: DepartmentRef | None
    active: bool
    employee_count: int
    version: int


class DepartmentInput(CamelModel):
    code: str = Field(max_length=20)
    name: str = Field(max_length=120)
    head_employee_id: str | None = None
    parent_id: str | None = None
    active: bool = True
    version: int | None = None
