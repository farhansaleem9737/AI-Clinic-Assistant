"""How many assistant requests this process answers at once (D130).

Each request holds a database connection and streams for many seconds, so
on a small instance they are bounded (AI_MAX_CONCURRENT_REQUESTS): one more
is told at once that the assistant is busy (503 AI_BUSY, or an `error` event
on the stream) instead of queueing and slowing everyone down. Nothing else
is limited: logins, bookings and health checks never wait for a slot.

A plain counter, not a lock: the event loop runs one task at a time, so
checking and taking a slot cannot interleave, and nothing is awaited while
holding it besides the request itself. The slot is returned however the
request ends, including when the user presses Stop (cancellation).
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from app.core.config import settings
from app.services.ai.provider import AiUnavailableError

logger = logging.getLogger(__name__)

BUSY = "The assistant is busy answering other people right now. Please try again in a moment."
_active = 0


def active() -> int:
    return _active


@contextmanager
def slot() -> Iterator[None]:
    global _active
    limit = settings.ai_max_concurrent_requests
    if limit and _active >= limit:
        logger.warning("ai_busy", extra={"active": _active, "limit": limit})
        raise AiUnavailableError(BUSY, code="AI_BUSY")
    _active += 1
    try:
        yield
    finally:
        _active -= 1
