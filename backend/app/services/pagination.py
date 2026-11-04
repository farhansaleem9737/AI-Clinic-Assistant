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

    The total rides along on each row as ``count(*) OVER ()`` (window functions
    run before LIMIT), so a page costs one round trip to the database, not two.
    Only an empty page past the first still needs a separate count.
    """
    if query._distinct:  # a window count would count the rows before DISTINCT
        total = await _count(db, query)
        rows = (await db.execute(query.limit(params.page_size).offset(params.offset))).all()
    else:
        counted = query.add_columns(func.count().over())
        rows = (await db.execute(counted.limit(params.page_size).offset(params.offset))).all()
        if rows:
            total = rows[0][-1]
            rows = [row[:-1] for row in rows]
        else:
            total = await _count(db, query) if params.offset else 0
    # Single-entity selects come back as 1-tuples; unwrap them.
    if rows and len(rows[0]) == 1:
        rows = [row[0] for row in rows]
    return rows, total or 0


async def _count(db: AsyncSession, query: Select) -> int:
    return await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
