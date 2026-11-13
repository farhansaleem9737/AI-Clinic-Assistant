"""Document reading off the web server's event loop, bounded (D130).

PDF parsing (pypdf, pure Python) is CPU-bound and holds the GIL. In a thread
it still competes with the event loop for the one interpreter lock, so on a
0.1-CPU instance a long document starved every other request, health checks
included. Here it runs in ONE worker process with a lower OS priority, so
the web process keeps the CPU it needs:

- at most one document is read at a time, and at most
  AI_EXTRACTION_QUEUE_LIMIT wait or run; more are refused (ExtractionBusy);
- each read is capped at AI_EXTRACTION_TIMEOUT_SECONDS: past it the worker
  is killed (ExtractionTimeout), and the next read starts a fresh one;
- a worker that dies (e.g. out of memory) is replaced (ExtractionFailed);
- the worker is recycled after a number of documents, so memory cannot creep.

Development and tests use one dedicated thread instead
(AI_EXTRACTION_ISOLATION, settings.extraction_in_process): same bounds,
no process start. Only module-level functions of medical_reports /
document_processor are sent, so the worker imports neither the app nor the
database. Document content is never logged.
"""

import asyncio
import logging
import multiprocessing
import os
import sys
import time
from collections.abc import Callable
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from typing import Any, TypeVar

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")
TASKS_PER_WORKER = 25
WORKER_NICENESS = 10


class ExtractionBusy(Exception):
    """Too many documents are being read right now."""


class ExtractionTimeout(Exception):
    """The document took longer than the limit."""


class ExtractionFailed(Exception):
    """The worker died while reading (memory, crash)."""


_executor: Executor | None = None
_in_process = False
_pending = 0


def _lower_priority() -> None:
    try:
        os.nice(WORKER_NICENESS)  # the web process wins the CPU whenever both want it
    except (AttributeError, OSError):
        pass


def _context():
    methods = multiprocessing.get_all_start_methods()
    return multiprocessing.get_context("forkserver" if sys.platform != "win32" and "forkserver" in methods else "spawn")


def _get_executor() -> Executor:
    global _executor, _in_process
    if _executor is None:
        _in_process = settings.extraction_in_process
        if _in_process:
            _executor = ProcessPoolExecutor(
                max_workers=1, mp_context=_context(), initializer=_lower_priority, max_tasks_per_child=TASKS_PER_WORKER
            )
        else:
            _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="extract")
    return _executor


def _discard(kill: bool) -> None:
    """Drop the executor; with kill, stop a running worker process now."""
    global _executor
    executor, _executor = _executor, None
    if executor is None:
        return
    if kill and isinstance(executor, ProcessPoolExecutor):
        killer = getattr(executor, "kill_workers", None)  # Python 3.14
        if killer is not None:
            killer()
        else:  # pragma: no cover - older Pythons
            for process in list(getattr(executor, "_processes", {}).values()):
                process.kill()
    executor.shutdown(wait=False, cancel_futures=True)


def pending() -> int:
    """Documents waiting or being read (for logs)."""
    return _pending


async def run(fn: Callable[..., T], *args: Any) -> T:
    """fn(*args) in the worker, bounded in count and time. The caller's
    cancellation (the user pressed Stop) withdraws a read that has not started."""
    global _pending
    if _pending >= settings.ai_extraction_queue_limit:
        logger.warning("ai_extraction_busy", extra={"pending": _pending})
        raise ExtractionBusy
    _pending += 1
    started = time.perf_counter()
    try:
        future = asyncio.get_running_loop().run_in_executor(_get_executor(), fn, *args)
        try:
            return await asyncio.wait_for(future, settings.ai_extraction_timeout_seconds)
        except TimeoutError:
            logger.warning("ai_extraction_timeout", extra={"seconds": settings.ai_extraction_timeout_seconds, "isolated": _in_process})
            _discard(kill=True)
            raise ExtractionTimeout from None
        except BrokenProcessPool:
            logger.warning("ai_extraction_worker_died")
            _discard(kill=True)
            raise ExtractionFailed from None
    finally:
        _pending -= 1
        logger.debug("ai_extraction_run", extra={"ms": round((time.perf_counter() - started) * 1000, 1)})


def shutdown() -> None:
    """Application shutdown: stop the worker without waiting for it."""
    _discard(kill=True)
