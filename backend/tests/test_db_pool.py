"""The pool checks a connection that sat idle and replaces it if the server
closed it meanwhile (Neon suspends and drops idle connections), without
paying that check on connections in recent use."""

import time

import pytest
from sqlalchemy import text

from app.db.database import AsyncSessionLocal, engine


async def _query():
    async with AsyncSessionLocal() as session:
        return await session.scalar(text("SELECT 1"))


def _pooled():
    return list(engine.pool._pool._queue._queue)  # idle connection records


@pytest.fixture(autouse=True)
async def fresh_pool():
    # The app engine's pool outlives each test's event loop: start and end empty.
    await engine.dispose()
    yield
    await engine.dispose()


async def test_a_connection_closed_while_idle_is_replaced_and_the_request_succeeds():
    assert await _query() == 1
    assert _pooled()
    for record in _pooled():
        await record.driver_connection.close()  # as if Neon dropped it
        record.info["idle_since"] = time.monotonic() - 3600
    assert await _query() == 1


async def test_a_connection_in_recent_use_is_reused_without_a_check():
    assert await _query() == 1
    before = [id(r.driver_connection) for r in _pooled()]
    assert await _query() == 1
    assert [id(r.driver_connection) for r in _pooled()] == before
