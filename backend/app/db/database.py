import time

from sqlalchemy import event
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.util import await_only

from app.core.config import settings

# Managed Postgres (Neon) closes idle connections and suspends the database
# when idle, so a pooled connection can be dead when it is reused.
#
# SQLAlchemy's pool_pre_ping would check every checkout, but with asyncpg it
# sends BEGIN, ";" and ROLLBACK: three network round trips (~300 ms to Neon
# Singapore) on every request. Instead only a connection that has sat idle is
# checked, with a single simple-protocol ";" (safe through PgBouncer). A dead one
# raises DisconnectionError, which makes the pool discard it and connect afresh,
# so the request still succeeds. pool_recycle retires connections before Neon's
# 5-minute auto-suspend could have closed them.
engine = create_async_engine(
    settings.database_url,
    echo=settings.sql_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle_seconds,
)


@event.listens_for(engine.sync_engine, "checkin")
def _mark_idle(dbapi_connection, record):
    record.info["idle_since"] = time.monotonic()


@event.listens_for(engine.sync_engine, "checkout")
def _ping_if_idle(dbapi_connection, record, proxy):
    idle_since = record.info.pop("idle_since", None)
    if idle_since is None or time.monotonic() - idle_since < settings.db_ping_after_idle_seconds:
        return  # new, or in recent use
    try:
        await_only(record.driver_connection.execute(";"))
    except Exception as exc:
        raise DisconnectionError("Pooled connection was closed while idle") from exc


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
