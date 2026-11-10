"""Is the database on the same migration as this code?

A deploy whose migrations were not applied fails on the first query that names a
new column (`UndefinedColumnError`), far from the cause. This compares the
database's `alembic_version` with the code's head once at startup and logs a
loud, specific error when they differ; `/health` reports it. It never changes the
database: applying migrations stays a deliberate step (`alembic upgrade head`).
"""

import logging
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

_ALEMBIC_DIR = Path(__file__).resolve().parents[2] / "alembic"

# Postgres SQLSTATEs for "the schema is not what the code expects".
SCHEMA_MISMATCH_SQLSTATES = {"42703", "42P01"}  # undefined_column, undefined_table

state: dict = {"status": "unknown"}


def code_heads() -> set[str]:
    config = Config()
    config.set_main_option("script_location", str(_ALEMBIC_DIR))
    return set(ScriptDirectory.from_config(config).get_heads())


async def check(engine: AsyncEngine) -> dict:
    """Record and return {"status": "current" | "behind" | "unknown", ...}."""
    try:
        heads = code_heads()
        async with engine.connect() as conn:
            applied = set((await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars().all())
    except Exception as exc:  # the database may be unreachable at startup; requests will say so
        logger.warning("schema_check_skipped", extra={"reason": type(exc).__name__})
        state.update(status="unknown")
        return state
    if applied == heads:
        state.update(status="current", database=sorted(applied), code=sorted(heads))
    else:
        state.update(status="behind", database=sorted(applied), code=sorted(heads))
        logger.error(
            "database_schema_behind",
            extra={
                "database_revision": sorted(applied),
                "code_revision": sorted(heads),
                "fix": "run `alembic upgrade head` in backend/ against this DATABASE_URL",
            },
        )
    return state


def sqlstate_of(exc: BaseException) -> str | None:
    """The Postgres SQLSTATE behind a SQLAlchemy DBAPIError (asyncpg), if any."""
    orig = getattr(exc, "orig", None)
    for candidate in (getattr(orig, "__cause__", None), orig):
        code = getattr(candidate, "sqlstate", None)
        if code:
            return code
    return None
