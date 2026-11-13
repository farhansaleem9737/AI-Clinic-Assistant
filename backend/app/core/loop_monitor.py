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
import sys
import threading
import time
import traceback

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
        _beat["at"] = time.monotonic()
        before = time.perf_counter()
        await asyncio.sleep(INTERVAL_SECONDS)
        _beat["at"] = time.monotonic()
        lag = time.perf_counter() - before - INTERVAL_SECONDS
        state["max_lag_ms"] = max(state["max_lag_ms"], lag * 1000)
        if lag > threshold:
            logger.warning(
                "event_loop_lag",
                extra={"lag_ms": round(lag * 1000), "ai_active": capacity.active(),
                       "extractions": extraction_worker.pending(), "rss_mb": _rss_mb()},
            )


# ---- stall watchdog (D132) ------------------------------------------------------------------
# The lag task above can only report once the loop runs again; a loop that never
# comes back (Render then restarts the process) leaves no trace. This *thread*
# notices the missing heartbeat and logs where the loop thread is stuck: file,
# line and function of each frame. Never local variables, arguments or content.

STALL_REPEAT_SECONDS = 10
_beat = {"at": time.monotonic()}
_watchdog: threading.Thread | None = None
_watchdog_stop = threading.Event()


def _where(frame) -> list[str]:
    stack = traceback.extract_stack(frame)[-30:]
    out = []
    for f in stack:
        name = f.filename.replace("\\", "/")
        for marker in ("/site-packages/", "/app/app/", "/backend/app/"):
            if marker in name:
                name = ("app/" if marker != "/site-packages/" else "") + name.split(marker, 1)[1]
                break
        out.append(f"{name}:{f.lineno} {f.name}")
    return out


def _watch_stalls(loop_thread_id: int, threshold: float) -> None:
    last_report = 0.0
    while not _watchdog_stop.wait(1.0):
        stalled = time.monotonic() - _beat["at"]
        if stalled < threshold:
            last_report = 0.0
            continue
        if last_report and time.monotonic() - last_report < STALL_REPEAT_SECONDS:
            continue
        last_report = time.monotonic()
        frame = sys._current_frames().get(loop_thread_id)
        logger.error("event_loop_stalled", extra={"stalled_s": round(stalled, 1), "rss_mb": _rss_mb(),
                                                  "stack": _where(frame) if frame is not None else []})


def start() -> None:
    global _task, _watchdog
    if settings.event_loop_lag_warning_ms and _task is None:
        _beat["at"] = time.monotonic()
        _task = asyncio.get_running_loop().create_task(_watch(), name="event-loop-lag")
        if settings.event_loop_stall_seconds and _watchdog is None:
            _watchdog_stop.clear()
            _watchdog = threading.Thread(
                target=_watch_stalls, args=(threading.get_ident(), settings.event_loop_stall_seconds),
                name="event-loop-watchdog", daemon=True,
            )
            _watchdog.start()


async def stop() -> None:
    global _task, _watchdog
    _watchdog_stop.set()
    _watchdog = None
    task, _task = _task, None
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
