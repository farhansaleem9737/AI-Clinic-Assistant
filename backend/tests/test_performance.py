"""Responsiveness on a small instance (D130): health checks during AI work,
the bounded extraction worker, kept extractions, request capacity and the
Gemini stream's timeouts. Synthetic data, mocked model and storage only.

    python -m pytest tests/test_performance.py -q -k "not stored"   # everything but the one database test
"""

import asyncio
import io
import time
import uuid

import httpx
import pytest
from pypdf import PdfReader, PdfWriter

from app.core.config import settings
from app.services.ai import capacity, extraction_worker, medical_reports
from app.services.ai.provider import AiUnavailableError
from tests.test_ai_agent import provider  # noqa: F401  (fixture)
from tests.test_documents import cast  # noqa: F401  (fixture)

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures" / "medical"


def big_pdf(pages: int = 50) -> bytes:
    """The read limit's worth of real report pages."""
    writer, sources = PdfWriter(), [PdfReader(p) for p in sorted(FIXTURES.glob("*.pdf"))]
    while len(writer.pages) < pages:
        for reader in sources:
            for page in reader.pages:
                if len(writer.pages) < pages:
                    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def worker(monkeypatch):
    """A fresh worker per test, with the mode under test."""
    def use(mode: str, **limits):
        monkeypatch.setattr(settings, "ai_extraction_isolation", mode)
        for name, value in limits.items():
            monkeypatch.setattr(settings, name, value)
        extraction_worker.shutdown()

    yield use
    extraction_worker.shutdown()


def health_client():
    from app.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def probe_health(client, stop: asyncio.Event) -> list[float]:
    latencies = []
    while not stop.is_set():
        started = time.perf_counter()
        response = await client.get("/health")
        assert response.status_code == 200
        latencies.append(time.perf_counter() - started)
        await asyncio.sleep(0.02)
    return latencies


# ---- health -------------------------------------------------------------------------------------


async def test_health_and_root_answer_get_and_head():
    async with health_client() as client:
        assert (await client.get("/health")).json()["status"] == "healthy"
        assert (await client.head("/health")).status_code == 200
        assert (await client.head("/")).status_code == 200  # was 405
        assert (await client.get("/")).status_code == 200


async def test_health_stays_fast_while_a_large_pdf_is_read_in_the_worker_process(worker):
    worker("process")
    data = big_pdf()
    await extraction_worker.run(sum, [1])  # start the worker (process start is not what is measured)
    async with health_client() as client:
        stop = asyncio.Event()
        probe = asyncio.create_task(probe_health(client, stop))
        extraction = await extraction_worker.run(medical_reports.extract_document, data, "application/pdf")
        stop.set()
        latencies = await probe
    assert extraction.status in ("ok", "partial") and len(extraction.pages) == 50
    assert len(latencies) >= 3 and max(latencies) < 0.25, latencies


async def test_health_stays_fast_while_the_model_streams_slowly():
    """An answer streaming for seconds (awaiting the network) never holds the loop."""
    async def slow_stream():
        for _ in range(10):
            await asyncio.sleep(0.05)
            yield "chunk"

    async with health_client() as client:
        stop = asyncio.Event()
        probe = asyncio.create_task(probe_health(client, stop))
        chunks = [c async for c in slow_stream()]
        stop.set()
        latencies = await probe
    assert len(chunks) == 10 and max(latencies) < 0.25


# ---- the extraction worker --------------------------------------------------------------------


async def test_the_worker_reads_documents_the_same_as_before(worker):
    worker("process")
    data = (FIXTURES / "mock_cbc_test_report.pdf").read_bytes()
    here = medical_reports.analyse(medical_reports.read(data, "application/pdf"))
    there = await extraction_worker.run(medical_reports.extract_document, data, "application/pdf")
    assert there.as_dict() == here.as_dict()


async def test_too_many_reads_at_once_are_refused_not_queued(worker):
    worker("thread", ai_extraction_queue_limit=2)
    first = asyncio.create_task(extraction_worker.run(time.sleep, 0.3))
    second = asyncio.create_task(extraction_worker.run(time.sleep, 0.01))
    await asyncio.sleep(0.05)
    with pytest.raises(extraction_worker.ExtractionBusy):
        await extraction_worker.run(time.sleep, 0)
    await asyncio.gather(first, second)
    assert extraction_worker.pending() == 0
    await extraction_worker.run(time.sleep, 0)  # free again


async def test_a_read_past_the_limit_is_stopped_and_the_next_one_works(worker):
    worker("process", ai_extraction_timeout_seconds=1)
    await extraction_worker.run(sum, [1])
    started = time.perf_counter()
    with pytest.raises(extraction_worker.ExtractionTimeout):
        await extraction_worker.run(time.sleep, 30)
    assert time.perf_counter() - started < 5  # the worker was killed, not waited for
    assert await extraction_worker.run(sum, [2, 3]) == 5  # a fresh worker
    assert extraction_worker.pending() == 0


async def test_cancelling_a_waiting_read_releases_its_place(worker):
    worker("thread", ai_extraction_queue_limit=2)
    running = asyncio.create_task(extraction_worker.run(time.sleep, 0.2))
    waiting = asyncio.create_task(extraction_worker.run(time.sleep, 0.2))
    await asyncio.sleep(0.02)
    waiting.cancel()  # the user pressed Stop
    with pytest.raises(asyncio.CancelledError):
        await waiting
    await running
    assert extraction_worker.pending() == 0


def test_a_kept_extraction_reads_back_identically():
    x = medical_reports.extract_document((FIXTURES / "mock_cbc_test_report.pdf").read_bytes(), "application/pdf")
    import json

    stored = json.loads(json.dumps(x.as_dict()))  # what JSONB gives back
    assert medical_reports.extraction_from_dict(stored) == x


def test_production_uses_a_process_and_development_a_thread(monkeypatch):
    from app.core.config import Environment

    monkeypatch.setattr(settings, "ai_extraction_isolation", None)
    monkeypatch.setattr(settings, "environment", Environment.production)
    assert settings.extraction_in_process
    monkeypatch.setattr(settings, "environment", Environment.development)
    assert not settings.extraction_in_process


# ---- request capacity -------------------------------------------------------------------------


def test_requests_over_the_limit_are_told_busy_and_slots_come_back(monkeypatch):
    monkeypatch.setattr(settings, "ai_max_concurrent_requests", 2)
    with capacity.slot(), capacity.slot():
        with pytest.raises(AiUnavailableError) as busy:
            with capacity.slot():
                pass
        assert busy.value.code == "AI_BUSY"
    with pytest.raises(RuntimeError):
        with capacity.slot():
            raise RuntimeError("the request failed")
    assert capacity.active() == 0


# ---- Gemini stream timeouts -------------------------------------------------------------------


def _gemini(chunks, *, delay_first=0.0, delay_between=0.0):
    from types import SimpleNamespace

    from app.services.ai.gemini_provider import GeminiProvider

    closed = []

    class Models:
        async def generate_content_stream(self, *, model, contents, config):
            async def stream():
                try:
                    await asyncio.sleep(delay_first)
                    for i, chunk in enumerate(chunks):
                        if i:
                            await asyncio.sleep(delay_between)
                        yield chunk
                finally:
                    closed.append(True)

            return stream()

    client = SimpleNamespace(aio=SimpleNamespace(models=Models()))
    return GeminiProvider(model="gemini-test", api_key="unused", client=client), closed


def _text_chunk(text):
    from google.genai import types

    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=text)]), finish_reason="STOP")]
    )


async def test_chunks_are_forwarded_as_they_arrive_and_first_chunk_time_is_measured():
    from app.services.ai.provider import Turn

    provider, _ = _gemini([_text_chunk("Hello "), _text_chunk("there")], delay_first=0.05, delay_between=0.1)
    seen = []
    reply = await provider.complete(system="s", turns=[Turn(role="user", text="hi")], tools=[],
                                    on_text=lambda t: _record(seen, t))
    assert [t for t, _ in seen] == ["Hello ", "there"]
    assert seen[1][1] - seen[0][1] >= 0.08  # streamed, not buffered
    assert reply.text == "Hello there" and reply.first_chunk_ms is not None and reply.first_chunk_ms >= 40


async def _record(seen, text):
    seen.append((text, time.perf_counter()))


async def test_no_first_chunk_in_time_is_a_timeout_and_the_stream_is_closed(monkeypatch):
    from app.services.ai.provider import Turn

    monkeypatch.setattr(settings, "ai_first_token_timeout_seconds", 3)
    provider, closed = _gemini([_text_chunk("late")], delay_first=10)
    started = time.perf_counter()
    with pytest.raises(AiUnavailableError) as failed:
        await provider.complete(system="s", turns=[Turn(role="user", text="hi")], tools=[])
    assert failed.value.code == "AI_TIMEOUT" and time.perf_counter() - started < 5 and closed


async def test_a_stalled_answer_is_a_timeout(monkeypatch):
    from app.services.ai.provider import Turn

    monkeypatch.setattr(settings, "ai_stream_idle_timeout_seconds", 3)
    provider, closed = _gemini([_text_chunk("a"), _text_chunk("b")], delay_between=10)
    with pytest.raises(AiUnavailableError) as failed:
        await provider.complete(system="s", turns=[Turn(role="user", text="hi")], tools=[])
    assert failed.value.code == "AI_TIMEOUT" and closed


async def test_stopping_mid_answer_closes_the_model_stream():
    from app.services.ai.provider import Turn

    provider, closed = _gemini([_text_chunk("a"), _text_chunk("b")], delay_between=10)
    task = asyncio.create_task(provider.complete(system="s", turns=[Turn(role="user", text="hi")], tools=[]))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed


# ---- kept extractions (database) --------------------------------------------------------------


async def test_a_document_is_read_once_and_stored_even_across_restarts(client, storage, clinic, cast, provider, db_session, monkeypatch):
    from sqlalchemy import select

    from app.models.document_extraction import DocumentExtraction
    from app.services.ai import medical_tools
    from tests.test_ai_agent import BASE, call, text_reply, tool_results
    from tests.test_ai_medical import CBC_NEW, add

    monkeypatch.setattr(settings, "ai_rate_limit_per_minute", 0)
    lines = [*CBC_NEW[:-1], f"Sample {uuid.uuid4().hex[:8]}"]  # unique content
    document_id = await add(client, cast.alice, clinic.patient_a, lines, "Blood count", "2026-09-01")
    reads = []
    original = storage.get

    async def counting_get(key):
        reads.append(key)
        return await original(key)

    storage.get = counting_get

    async def explain(headers):
        provider.calls.clear()
        provider.replies = [call("explain_medical_document", document_id=document_id), text_reply("ok")]
        await client.post(f"{BASE}/messages", json={"text": "Explain my blood test"}, headers=headers)
        return tool_results(provider.calls[1])["explain_medical_document"]

    medical_tools.clear_cache()
    await explain(cast.alice)
    assert len(reads) == 1
    row = await db_session.scalar(select(DocumentExtraction).where(DocumentExtraction.version == medical_reports.EXTRACTION_VERSION))
    assert row is not None and row.status in ("ok", "partial") and row.payload["measurements"]

    medical_tools.clear_cache()  # a restart: the memory cache is empty
    await explain(cast.alice)
    assert len(reads) == 1  # served from the kept extraction, the file was not downloaded again

    # The kept extraction is no way around the record's rules.
    medical_tools.clear_cache()
    denied = await explain(cast.bob)
    assert "not found" in denied["error"].lower() and len(reads) == 1

    # A new extractor version never reuses an older result.
    monkeypatch.setattr(medical_reports, "EXTRACTION_VERSION", "test-next")
    medical_tools.clear_cache()
    await explain(cast.alice)
    assert len(reads) == 2


async def test_a_busy_server_answers_the_stream_with_an_error_event_and_the_slot_returns(client, auth_headers, provider, monkeypatch):
    from app.core.permissions import RoleCode
    from tests.test_ai_agent import BASE, parse_sse, text_reply

    monkeypatch.setattr(settings, "ai_max_concurrent_requests", 1)
    headers = await auth_headers(RoleCode.patient)
    with capacity.slot():  # someone else's answer is in progress
        events = parse_sse((await client.post(f"{BASE}/messages/stream", json={"text": "hi"}, headers=headers)).text)
        assert events[0][1].pop("request_id")
        assert events == [("error", {"code": "AI_BUSY", "message": capacity.BUSY})]
        busy = await client.post(f"{BASE}/messages", json={"text": "hi"}, headers=headers)
        assert busy.status_code == 503 and busy.json()["error"]["code"] == "AI_BUSY"
    provider.replies = [text_reply("Hello!")]
    events = parse_sse((await client.post(f"{BASE}/messages/stream", json={"text": "hi"}, headers=headers)).text)
    assert events[-1][0] == "done" and capacity.active() == 0


def a_function_that_freezes_the_loop():
    time.sleep(2.6)  # stands in for CPU-bound work that never yields


async def test_a_frozen_event_loop_is_logged_with_where_it_is_stuck(monkeypatch, caplog):
    """D132: the lag task cannot report a loop that never comes back; the watchdog thread can."""
    from app.core import loop_monitor

    monkeypatch.setattr(settings, "event_loop_lag_warning_ms", 500)
    monkeypatch.setattr(settings, "event_loop_stall_seconds", 1)
    loop_monitor.start()
    try:
        await asyncio.sleep(0.6)
        a_function_that_freezes_the_loop()
        await asyncio.sleep(0.1)
    finally:
        await loop_monitor.stop()
    [stall, *_] = [r for r in caplog.records if r.getMessage() == "event_loop_stalled"]
    assert stall.stalled_s >= 1 and any("a_function_that_freezes_the_loop" in line for line in stall.stack), stall.stack
    assert all(":" in line for line in stall.stack)  # file:line function only, no values
