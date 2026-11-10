"""Paging and sorting helpers shared by the concept repositories.

This is intentionally not a generic repository: each business concept has its own repository class
with its own queries. These helpers only implement the common `{items, meta}` mechanics.
"""

import math
from dataclasses import dataclass
from typing import Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import BadRequestError

T = TypeVar("T")


@dataclass
class PageResult(Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total_items: int

    @property
    def total_pages(self) -> int:
        return math.ceil(self.total_items / self.page_size) if self.page_size else 0


async def paginate(session: AsyncSession, stmt: Select, page: int, page_size: int, *, scalars: bool = True) -> PageResult:
    total = int(await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
    result = await session.execute(stmt.limit(page_size).offset((page - 1) * page_size))
    rows = list(result.scalars().unique().all()) if scalars else list(result.all())
    return PageResult(rows, page, page_size, total)


def parse_sort(sort: str | None, allowed: dict[str, ColumnElement], default: str) -> list[ColumnElement]:
    """'joiningDate:desc' -> [column.desc()]. Unknown fields or directions -> 400 (contract A5)."""
    value = (sort or default).strip()
    field, _, direction = value.partition(":")
    direction = (direction or "asc").lower()
    if field not in allowed:
        raise BadRequestError(f"Sorting by '{field}' is not supported.", details=[{"field": "sort", "message": f"Use one of: {', '.join(sorted(allowed))}."}])
    if direction not in ("asc", "desc"):
        raise BadRequestError("Sort direction must be asc or desc.", details=[{"field": "sort", "message": "Use asc or desc."}])
    column = allowed[field]
    return [column.desc() if direction == "desc" else column.asc()]
