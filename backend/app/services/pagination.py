from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class PageParams:
    page: int = 1
    page_size: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


async def paginate(db: AsyncSession, query: Select, params: PageParams) -> tuple[Sequence[Any], int]:
    """Run `query` for one page and count all matches — both in SQL.

    Returns ``(rows, total)``. Rows are whatever the query selects (entities or
    tuples). The query must have a deterministic ORDER BY.
    """
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    result = await db.execute(query.limit(params.page_size).offset(params.offset))
    rows = result.all()
    # Single-entity selects come back as 1-tuples; unwrap them.
    if rows and len(rows[0]) == 1:
        rows = [row[0] for row in rows]
    return rows, total or 0
