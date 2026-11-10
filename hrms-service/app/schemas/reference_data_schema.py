"""Reference lists (frontend `referenceData.service.ts`) and their setup inputs (/hr/setup)."""

from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import CamelModel, ResponseModel

Tone = Literal["neutral", "info", "success", "warning", "danger", "primary"]
FieldType = Literal["text", "select", "date", "number"]


# --- Responses (exact frontend shapes) ---------------------------------------------------------


class ReferenceItem(ResponseModel):
    id: str
    code: str
    name: str
    active: bool


class EmployeeStatusOption(ResponseModel):
    code: str
    label: str
    tone: Tone
    active: bool
    allowed_on_create: bool
    transitions: list[str]


class OptionItem(ResponseModel):
    id: str
    name: str
    description: str | None = None


class NamedRef(ResponseModel):
    id: str
    name: str


class DocumentTypeOption(ResponseModel):
    id: str
    name: str
    category: NamedRef
    required: bool
    expiry_required: bool
    allowed_extensions: list[str]
    max_size_bytes: int
    active: bool


class SelectOption(CamelModel):
    value: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=120)


class PayrollFieldDefinitionOut(ResponseModel):
    key: str
    label: str
    type: FieldType
    required: bool
    sensitive: bool
    max_length: int | None = None
    pattern: str | None = None
    pattern_message: str | None = None
    options: list[SelectOption] | None = None
    hint: str | None = None


# --- Setup inputs (HR configuration) ------------------------------------------------------------


def _strip(v: str) -> str:
    return v.strip()


class CodedItemInput(CamelModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    active: bool = True
    description: str | None = Field(default=None, max_length=500)
    version: int | None = None

    _trim = field_validator("code", "name")(_strip)


class EmployeeStatusInput(CamelModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=30)
    label: str = Field(min_length=2, max_length=80)
    tone: Tone
    active: bool = True
    allowed_on_create: bool = False
    transitions: list[str] = Field(default_factory=list)
    sort_order: int = 0
    # HR settings, off until HR confirms (docs/HR_CONFIRMATION_PENDING.md):
    employment_ended: bool = False  # employees in this status no longer work here
    reason_required: bool = False  # a reason is required when moving an employee into this status
    version: int | None = None


class DocumentTypeInput(CamelModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    category_id: str
    required: bool = False
    expiry_required: bool = False
    allowed_extensions: list[str] = Field(min_length=1)
    max_size_bytes: int = Field(gt=0, le=100 * 1024 * 1024)
    active: bool = True
    version: int | None = None

    @field_validator("allowed_extensions")
    @classmethod
    def _extensions(cls, v: list[str]) -> list[str]:
        out = []
        for ext in v:
            e = ext.strip().lower()
            e = e if e.startswith(".") else f".{e}"
            if not e[1:].isalnum() or len(e) > 10:
                raise ValueError("Use file extensions such as .pdf or .jpg.")
            out.append(e)
        return sorted(set(out))


class PayrollFieldInput(CamelModel):
    key: str = Field(pattern=r"^[a-z][A-Za-z0-9]*$", max_length=50)
    label: str = Field(min_length=2, max_length=120)
    type: FieldType
    required: bool = False
    sensitive: bool = False
    max_length: int | None = Field(default=None, gt=0, le=500)
    pattern: str | None = Field(default=None, max_length=200)
    pattern_message: str | None = Field(default=None, max_length=200)
    options: list[SelectOption] | None = None
    hint: str | None = Field(default=None, max_length=300)
    sort_order: int = 0
    active: bool = True
    version: int | None = None


# --- Setup responses (HR configuration screens / API clients) -------------------------------------


class CodedItemSetupOut(ResponseModel):
    id: str
    code: str
    name: str
    description: str | None = None
    active: bool
    version: int


class EmployeeStatusSetupOut(EmployeeStatusOption):
    id: str
    sort_order: int
    employment_ended: bool
    reason_required: bool
    version: int


class DocumentTypeSetupOut(DocumentTypeOption):
    code: str
    version: int


class PayrollFieldSetupOut(PayrollFieldDefinitionOut):
    id: str
    sort_order: int
    active: bool
    version: int
