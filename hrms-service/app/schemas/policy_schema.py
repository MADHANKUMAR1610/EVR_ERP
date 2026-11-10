"""HR policies (frontend admin.service.ts PolicyDocument, contract G6)."""

from typing import Literal

from pydantic import Field

from app.schemas.common import CamelModel, ResponseModel, UtcDateTime

PolicyValue = float | int | bool | str | None


class PolicyOptionOut(ResponseModel):
    value: str
    label: str


class PolicyFieldOut(ResponseModel):
    key: str
    label: str
    help: str
    type: Literal["number", "boolean", "select"]
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    options: list[PolicyOptionOut] | None = None
    optional: bool | None = None


class PolicyDocumentOut(ResponseModel):
    area: str
    fields: list[PolicyFieldOut]
    values: dict[str, PolicyValue]
    effective_from: str | None
    version: int
    updated_at: UtcDateTime | None
    updated_by: str | None


class PolicySaveIn(CamelModel):
    values: dict[str, PolicyValue] = Field(default_factory=dict)
    effective_from: str
    version: int
