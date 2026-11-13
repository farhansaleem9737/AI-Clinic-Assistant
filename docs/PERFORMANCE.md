# Responsiveness on a small instance (D130)

The API runs as one uvicorn process on Render's free plan: 0.1 CPU and 512 MB.
Render restarts the service when `GET /health` stops answering within about 5 s.
This page covers what can block that process, what keeps it responsive, and how
to check that the fixes worked in production.

## What blocked it

1. **PDF reading shared the interpreter lock with the web server.** pypdf's
   layout extraction is pure Python and CPU-bound. In a worker *thread* it still
   competes with the event loop for the GIL. Locally a 50-page report costs
   0.56 s of CPU, and while it runs the loop gets only half its turns. At 0.1 CPU
   the same work takes several seconds of wall time, and every other request
   waits behind it.
2. **Every question re-read the document after a restart.** Extractions lived
   only in an in-process cache. A restart emptied it, so the next question
   downloaded and parsed every file again. A summary can parse up to 10 files.
   That made the next restart more likely.
3. **`/health` was a sync `def`.** Starlette runs a sync route in its thread
   pool, so a health check needed a free thread and had to win the GIL back.
4. **The chat-attachment classifier ran on the event loop.** It ran on every
   message in the history: about 135 ms locally for 60,000 characters, and
   10× slower on Render.

Gemini was already streamed with the async client
(`client.aio.models.generate_content_stream`, `async for`). The network wait
never blocked the loop.

## What keeps it responsive now

| Part | Behaviour |
|---|---|
| `extraction_worker` | Document reading runs in **one worker process** at OS priority +10, so the web process gets the CPU first. One read runs at a time. `AI_EXTRACTION_QUEUE_LIMIT` (4) caps how many may wait or run; more are refused as busy. Each read is capped at `AI_EXTRACTION_TIMEOUT_SECONDS` (60): past that the worker is killed and replaced. A worker that dies (for example out of memory) is replaced. Workers recycle after 25 documents. Development and tests use one dedicated thread instead (`AI_EXTRACTION_ISOLATION`). |
| `document_extractions` | Each file's extraction is **kept**, one row per file and extractor version, checked against the file's sha256. Later questions and restarts reuse it. A new `EXTRACTION_VERSION` writes a new row and never reads old ones. A row is deleted with its file (cascade, and when the stored object is deleted). It is read only after `document_service` has authorized the caller for the owning document. Storage errors, busy and timeouts are never kept. |
| `/health`, `/` | `async def`, GET and HEAD. They touch nothing: no database, storage or AI. |
| `capacity` | At most `AI_MAX_CONCURRENT_REQUESTS` (3) assistant requests at once. One more gets 503 `AI_BUSY`, or an `error` event on the stream, right away. The slot is returned however the request ends, including Stop. Nothing else is limited. |
| Gemini step | Three limits: first chunk `AI_FIRST_TOKEN_TIMEOUT_SECONDS` (25), a pause mid-answer `AI_STREAM_IDLE_TIMEOUT_SECONDS` (20), and the whole step `AI_TIMEOUT_SECONDS` (30). Each fails with `AI_TIMEOUT`, which the stream reports as an `error` event, so the thinking indicator stops. The HTTP stream is closed on timeout, error or Stop. Appointment actions are never retried. |
| `loop_monitor` | Logs `event_loop_lag` when the loop is late by more than `EVENT_LOOP_LAG_WARNING_MS` (500). The log line includes what was running: `ai_active`, `extractions` and `rss_mb`. |
| Logs | `ai_timing` now includes `first_chunk_ms` for each model step. `ai_document_extracted` includes `source` (`read` or `stored`), `download_ms` and `ms`. Durations and counts only, never content. |

## Measured locally

Measured on the real app, with 3 reads of a 50-page PDF built from the
synthetic fixtures. Windows, 12 cores, so the absolute numbers are far better
than Render's. Compare the rows with each other, not with production.

| Scenario | Loop lag p50 / p99 / max | `/health` p50 / max |
|---|---|---|
| Idle | 6.4 / 14.2 / 14.2 ms | 1.8 / 4.2 ms |
| Before: shared thread pool | 21.3 / 53.8 / 53.8 ms | 1.7 / 32.6 ms |
| After: worker process | 6.5 / 8.5 / 8.5 ms | 1.8 / 3.1 ms |
| After: two conversations reading at once | 4.7 / 8.8 / 8.8 ms | 2.2 / 3.0 ms |

Rebuilding a kept extraction takes 1 ms from a 107 KB JSON payload, plus one
database round trip. Before, a cold cache meant an R2 download and a full parse.

## Configuration

Render (`render.yaml` defaults are fine):

- Run `python -m alembic upgrade head` once to add `document_extractions`.
  Until then the server keeps working with the memory cache only: `/health`
  shows `"schema": "behind"`.
- Leave `WEB_CONCURRENCY` / worker count at 1. The extraction worker is the
  second process, about 50–70 MB while in use.

Vercel:

- Set `VITE_REALTIME_URL=wss://<render-host>/api/v1/ws` and redeploy. Without
  it, a production build now skips the live-updates socket and polls instead.
  Before, it retried through the `/api` rewrite, which drops the WebSocket
  `Upgrade` header, so Render answered `GET /api/v1/ws 404` again and again.
- `CORS_ORIGINS` on Render must contain the Vercel origin. The socket checks it.

## Checking it in production

1. **Logs:** look for `event_loop_lag`. None, or only single lines under about
   1 s, is healthy. A burst with `extractions: 1` points at document reading.
   A burst with `extractions: 0` points at something else; note `ai_active`.
2. **Logs:** the first question about a document shows
   `ai_document_extracted … "source": "read"`. Later questions, even after a
   restart, show `"source": "stored"` with a small `ms`.
3. **Logs:** `ai_timing` → `first_chunk_ms` is the model's own latency.
   `prepare_ms` and `tools_ms` are ours.
4. **Metrics:** Render → Events should show no "health check failed" restarts
   while people use the assistant. Watch Metrics → Memory: the worker process
   adds about 50–70 MB. If memory approaches 512 MB, lower
   `AI_EXTRACTION_QUEUE_LIMIT` or move to a paid instance.
5. **By hand:** while an answer is streaming, run
   `curl -s -o /dev/null -w "%{time_total}\n" https://<render-host>/health`.
   It should answer in well under a second.

## Remaining limits

- **CPU:** 0.1 CPU is shared by everything. The worker yields to the web
  process but still takes the CPU when that process is idle. A large first
  read can take tens of seconds, bounded by the 60 s limit, after which the
  user is asked to try later. A paid instance (Starter, 0.5 CPU) removes most of
  this.
- **Database connections:** an assistant request holds one connection while
  it waits for the model, because its transaction stays open. The concurrency
  limit keeps this at 3.
- **Memory cache:** the in-process cache (up to 64 extractions) still exists in
  front of the database row.
- **Chat uploads:** these are off in production and are still read when
  uploaded, now in the worker.
