"""Event-loop lag watch (D130): proof, in the logs, of whether anything blocks the server.

A task sleeps for a fixed interval and measures how late it wakes up. When the
loop is late by more than EVENT_LOOP_LAG_WARNING_MS it logs `event_loop_lag`
with the lag, the assistant requests and document reads in progress and the
process memory: a freeze shows up as a burst of these lines, with what was
running at the time. Costs one wake-up per interval. Never logs content.
"""

import asyncio
import logging
import os
import time

from app.core.config import settings

logger = logging.getLogger("app.loop")

INTERVAL_SECONDS = 0.5
_task: asyncio.Task | None = None
state = {"max_lag_ms": 0.0}


def _rss_mb() -> float | None:
    try:  # Linux (Render): resident pages of this process, right now
        with open("/proc/self/statm") as f:
            return round(int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1_048_576, 1)
    except (OSError, ValueError, AttributeError, IndexError):
        return None


async def _watch() -> None:
    from app.services.ai import capacity, extraction_worker

    threshold = settings.event_loop_lag_warning_ms / 1000
    while True:
        before = time.perf_counter()
        await asyncio.sleep(INTERVAL_SECONDS)
        lag = time.perf_counter() - before - INTERVAL_SECONDS
        state["max_lag_ms"] = max(state["max_lag_ms"], lag * 1000)
        if lag > threshold:
            logger.warning(
                "event_loop_lag",
                extra={"lag_ms": round(lag * 1000), "ai_active": capacity.active(),
                       "extractions": extraction_worker.pending(), "rss_mb": _rss_mb()},
            )


def start() -> None:
    global _task
    if settings.event_loop_lag_warning_ms and _task is None:
        _task = asyncio.get_running_loop().create_task(_watch(), name="event-loop-lag")


async def stop() -> None:
    global _task
    task, _task = _task, None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
