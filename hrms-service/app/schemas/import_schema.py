"""Employee import (frontend employeeImport.service.ts, contract B6). Field names match exactly."""

from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import CamelModel, ResponseModel, UtcDateTime

RowStatus = Literal["valid", "warning", "duplicate", "error"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class ImportFieldOut(ResponseModel):
    key: str
    label: str
    required: bool
    type: Literal["text", "date", "email", "phone", "reference"]
    reference_type: Literal["department", "designation", "employmentType", "employeeStatus", "workLocation"] | None = None
    max_length: int | None = None
    aliases: list[str] = Field(default_factory=list)
    example: str | None = None
    unique: bool = False


class ImportRowIn(CamelModel):
    row_number: int = Field(ge=2, le=1_000_000)
    values: dict[str, str]

    @field_validator("values")
    @classmethod
    def _bounded(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 50:
            raise ValueError("Too many values in one row.")
        if any(len(k) > 60 or len(x) > 500 for k, x in v.items()):
            raise ValueError("A value is too long (at most 500 characters).")
        return v


class ImportRowsIn(CamelModel):
    rows: list[ImportRowIn]


class ImportStartIn(ImportRowsIn):
    skip_duplicates: bool = True


class ImportMessageOut(ResponseModel):
    field: str | None = None
    message: str
    severity: Literal["error", "warning"]


class ImportRowResultOut(ResponseModel):
    row_number: int
    status: RowStatus
    messages: list[ImportMessageOut]


class ValidationSummaryOut(ResponseModel):
    total: int
    valid: int
    warning: int
    duplicate: int
    error: int


class ImportValidationOut(ResponseModel):
    rows: list[ImportRowResultOut]
    # Addition to the contract (the frontend ignores it): totals for API clients and the preview.
    summary: ValidationSummaryOut


class ProgressOut(ResponseModel):
    processed: int
    total: int


class JobSummaryOut(ResponseModel):
    created: int
    skipped: int
    failed: int


class JobFailureOut(ResponseModel):
    row_number: int
    messages: list[str]


class ImportJobOut(ResponseModel):
    id: str
    status: JobStatus
    progress: ProgressOut
    summary: JobSummaryOut | None
    failures: list[JobFailureOut]
    created_at: UtcDateTime
    finished_at: UtcDateTime | None
    error: str | None


class ParsedFileOut(ResponseModel):
    """POST /hr/employee-imports/file-rows: a .xlsx/.csv file read on the server (nothing is stored)."""

    file_name: str
    headers: list[str]
    mapping: dict[str, int | None]
    unmapped_columns: list[str]
    missing_required_fields: list[str]
    blank_rows_ignored: int
    rows: list[ImportRowIn]
