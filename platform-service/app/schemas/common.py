"""Shared schema building blocks: camelCase models, paging, and the error envelope (for OpenAPI)."""

from datetime import UTC, date, datetime
from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel

from app.repositories.base_repository import PageResult

T = TypeVar("T")

ALLOWED_PAGE_SIZES = (10, 25, 50, 100)


def _iso_utc(value: datetime) -> str:
    """UTC with a 'Z' suffix, e.g. 2026-10-29T03:30:00Z (contract A2). Naive values are treated as UTC."""
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


UtcDateTime = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str)]
IsoDate = date


class CamelModel(BaseModel):
    """Base for every request and response schema: camelCase JSON, snake_case in Python."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra="forbid")


class ResponseModel(CamelModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra="ignore")


class PageMeta(ResponseModel):
    page: int
    page_size: int
    total_items: int
    total_pages: int


class Page(ResponseModel, Generic[T]):
    items: list[T]
    meta: PageMeta

    @classmethod
    def build(cls, result: PageResult, items: list) -> "Page":
        return cls(items=items, meta=PageMeta(page=result.page, page_size=result.page_size, total_items=result.total_items, total_pages=result.total_pages))


class PageParams(CamelModel):
    page: int
    page_size: int
    sort: str | None
    q: str | None


def page_params(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    page_size: Annotated[int, Query(alias="pageSize", description="10, 25, 50 or 100")] = 25,
    sort: Annotated[str | None, Query(description="field:asc or field:desc")] = None,
    q: Annotated[str | None, Query(max_length=200, description="Free-text search")] = None,
) -> PageParams:
    from app.core.errors import ValidationFailedError

    if page_size not in ALLOWED_PAGE_SIZES:
        raise ValidationFailedError(details=[{"field": "pageSize", "message": "Use 10, 25, 50 or 100."}])
    return PageParams(page=page, page_size=page_size, sort=sort, q=(q or "").strip() or None)


class ErrorDetail(CamelModel):
    field: str
    message: str


class ErrorBody(CamelModel):
    code: str
    message: str
    details: list[ErrorDetail]


class ErrorEnvelope(CamelModel):
    error: ErrorBody
