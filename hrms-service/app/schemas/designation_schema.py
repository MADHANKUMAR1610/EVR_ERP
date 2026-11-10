"""Designations (frontend `admin.service.ts`: Designation, DesignationInput)."""

from pydantic import Field

from app.schemas.common import CamelModel, ResponseModel
from app.schemas.department_schema import DepartmentRef


class DesignationOut(ResponseModel):
    id: str
    code: str
    name: str
    description: str
    departments: list[DepartmentRef]
    active: bool
    employee_count: int
    version: int


class DesignationInput(CamelModel):
    code: str = Field(max_length=20)
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=1000)
    department_ids: list[str] = Field(default_factory=list)
    active: bool = True
    version: int | None = None
