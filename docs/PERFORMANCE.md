# Performance and deployment notes

Measured 2026-11-03 from the development machine against Neon (AWS ap-southeast-1, Singapore), pooled endpoint, asyncpg.

## Where request time goes

| Measurement | Result |
|---|---|
| TCP connect to Neon (= network round trip) | ~100–120 ms |
| New connection (TCP + TLS + auth) | ~640 ms pooled endpoint, ~730 ms direct |
| `SELECT 1` on an open connection | ~98 ms pooled, ~119 ms direct |
| Server-side execution (`EXPLAIN ANALYZE`) | under 1 ms |
| `pool_pre_ping` per checkout (asyncpg: BEGIN, `;`, ROLLBACK) | ~360 ms |

Neon is not slow; the distance is. Each SQL statement costs one round trip, and every
request also pays BEGIN and (after the response is sent) ROLLBACK/COMMIT. Fewer
statements per request is what makes endpoints faster.

The pooled endpoint (`-pooler` in the host) connects faster and handles many
connections; keep using it.

## Connection pool (`app/db/database.py`)

- No `pool_pre_ping`. A connection idle for more than `DB_PING_AFTER_IDLE_SECONDS`
  (default 30) is checked with a single `;` (one round trip, PgBouncer-safe). A
  dead one is discarded and replaced, so the request still succeeds
  (`tests/test_db_pool.py`).
- `DB_POOL_RECYCLE_SECONDS` (240) retires connections before Neon's 5-minute
  auto-suspend can close them.
- `DB_POOL_SIZE` (5) + `DB_MAX_OVERFLOW` (10) per process. Neon's pooler accepts
  far more client connections than this.

## Local PostgreSQL for development (optional)

Local Postgres removes the ~100 ms per statement, so development and the test suite
run much faster. Neon stays for staging and production. `DATABASE_URL` alone
decides which one is used; no code change is needed.

```bash
createdb clinic_ai                      # PostgreSQL 16+
# backend/.env:
# DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/clinic_ai
cd backend
alembic upgrade head                    # schema from the existing migrations
python -m scripts.seed_demo             # optional: fictional demo data only
```

Do not copy the Neon database to a laptop: it may hold patient data. Tests create
their own database (`TEST_DATABASE_URL`, default `<name>_test`).

## AI requests

Each AI message logs `ai_timing` with:
- `prepare_ms`: auth, conversation, limits and history queries;
- `model_ms`: one entry per Gemini call, including the tool-choice step;
- `tools_ms`: tool execution, including their database queries;
- `save_ms`: final commit;
- `total_ms`.

It logs durations only, never content. Gemini time is outside our control. The
database part is a handful of round trips, so it shrinks to almost nothing when the
backend runs next to the database.

## Deployment (not done)

- **Region:** run the backend in AWS ap-southeast-1 (Singapore), the same region
  as Neon, or the nearest region of another host (e.g. Render, Fly.io or Railway
  Singapore). A round trip then drops from ~100 ms to ~1–2 ms, so a dashboard
  request goes from ~0.5–1 s to a few tens of milliseconds plus the user's own
  distance to the server.
- **Serving:** serve the built frontend from a CDN or the same host. Keep `/api`
  same-origin (as the Vite proxy does in development) so the SameSite=Strict
  refresh cookie keeps working.
- **Environment variables:**
  - **Secrets** (in the host's secret store, never in the image or the repo):
    `DATABASE_URL` (pooled endpoint, `?ssl=require`), `SECRET_KEY`, `GEMINI_API_KEY`
    and the storage credentials.
  - **Other settings:** `ENVIRONMENT=production` (enables Secure cookies),
    `CORS_ORIGINS` (the real site only), `CLINIC_TIMEZONE`, `LOG_LEVEL=INFO`,
    `SQL_ECHO=false`, and `DB_*` only if tuning is needed.
- **AI and patient data:** keep `AI_PHI_ALLOWED=false` and
  `AI_ALLOW_SYNTHETIC_DOCUMENTS=false` until a Gemini paid tier with a data
  processing agreement is in place.
- **Server process:** run uvicorn with a few workers, and remember each has its own
  pool (workers × (pool_size + overflow) connections). Put HTTPS termination in
  front.
- **Migrations:** run `alembic upgrade head` as a deliberate release step, never
  automatically on start.

## Navigation, cached data and drafts (frontend, D107)

Measured 2026-11-03 with headless Chrome against the real backend (on the developer
machine, Neon in Singapore). "Mobile" emulates 150 ms latency, 4 Mbit/s and a 4×
slower CPU.

### Routing

- One route branch renders the app shell for every signed-in page, the doctor
  directory and departments included, so the sidebar, top bar and assistant
  (its open conversation) are never remounted by navigation.
- The dashboard is in the main bundle (most roles land on it); other pages load on
  demand through `routes/lazyPage.jsx`. Pointing at, focusing or touching an in-app
  link starts that page's download.
- A failed page download is retried twice (0.5 s, 1.5 s). If it still fails, the
  page says so, with **Try again** (downloads again, no reload) and **Reload app**.
  Nothing reloads the document automatically.
- The idle-time prefetch scheduler (D106) is removed.

### Cached server data

`useFetch(fetcher, deps, { query: "category/name" })` keeps results in one app-level
TanStack Query client (`services/queryClient.js`), in memory only:

- **Keys start with the signed-in user**, and the cache is emptied whenever the
  user changes (sign-out, expired session, another account).
- **Revisiting a page** shows its data at once. Data older than its category's
  freshness is refreshed in the background, without a skeleton.
- **Unused data** is dropped after 5 minutes.
- **Identical requests** (several components, React's development double-mount)
  are sent once.
- **Failed reads** are repeated once, after 0.8 s, for a server or network failure
  (5xx or no answer), never for 4xx. A failed background refresh keeps the data on
  screen.
- **Unnamed calls are not cached**, for example the last availability check before
  booking and a patient's documents.

| Category | Fresh for | Examples |
|---|---|---|
| departments, specializations, settings | 5 min | directory filters, department lists |
| doctors | 2 min | directory, doctor profiles, staff options |
| profile | 1 min | the signed-in user's own patient or doctor profile |
| dashboard, appointments, patients, users, schedule | 30 s | dashboards, lists, weekly hours |
| availability | 0 (always re-checked) | free times; shown while re-checking |

**After a successful change**, an axios hook marks the affected categories stale. It
uses the first path segment of the request: `appointments` → appointments,
dashboard, availability, schedule, patients; `doctors` (incl. weekly hours) →
doctors, schedule, availability, dashboard, departments, specializations, profile;
and so on. The page on screen refreshes at once; other pages refresh when next
opened.
- Assistant messages change nothing. A confirmed assistant action may change
  anything, so everything is refreshed.
- Nothing is shown as done before the server confirms it; the booking keeps its
  idempotency key.

### Drafts

`useDraft(key, initial)` (`hooks/useDraft.js`, `services/drafts.js`) is
useState that survives leaving the page. It is kept in memory for the signed-in
user and emptied on sign-out or another account. It holds:
- **Booking:** step, doctor, chosen time, the date being looked at, the doctor
  search and filters, and the typed reason.
- **List pages:** search, filters and page on Departments, Admin
  Doctors/Departments/Users, Patients and the doctor's appointments.
- **Weekly hours:** unsaved edits, restored only onto the same saved week.

**Surviving a reload:** a patient's own booking keeps the doctor id, the step and
the time (never the reason) in `sessionStorage`, for 30 minutes.
- The stored value is versioned and scoped to the user, and is validated before
  use.
- A malformed or expired value is discarded.
- Sign-out removes it.
- On restore the doctor is validated again, and the confirm step re-checks the
  time. A kept time is never a reservation.

### Measurements

- **Before:** every return showed a skeleton and repeated its requests.

  | Return to a page already visited | Before | After |
  |---|---|---|
  | Content on screen, desktop | 0.8–2.9 s | 9–28 ms |
  | Content on screen, mobile | 0.8–1.9 s | 72–176 ms |
  | API requests | 2–6 | 0 (while fresh) |

- **First visits are unchanged:** they still wait for Neon.
- **Development server (React StrictMode):** every request used to be sent twice,
  including `/auth/me`. Now each is sent once, apart from a few hand-written
  effects.
- **Failed page download:**
  - Before: one attempt, then a message whose Try again never recovered.
  - After: 3 attempts in about 2 s, then the message; Try again recovers without
    a reload.

### Backend: dropped database connections

A connection that drops mid-request (seen as `/auth/me` 500s from Neon) now
answers 503 `DATABASE_UNAVAILABLE` with `Retry-After: 1`, instead of a generic 500.
- The transaction is rolled back, and the pool discards the connection.
- The frontend repeats a failed read once, and session restore retries `/auth/me`
  once.
- Changes are never repeated automatically.

### Redis: not added

Measured earlier (D105): queries execute in under 1 ms on the server. Request time
is network round trips to Neon (~100 ms each from the developer machine, ~1–2 ms
from a backend in Singapore).
- **Department and directory reads** are already one or two statements.
- **Dashboard aggregates** are one statement per section, are per-user or
  per-clinic-day, and change with every booking.
- **A Redis cache** next to the backend would save about 1–2 ms per cached read.
  It would also add a service, invalidation rules for every write, and another
  failure mode.
- **The browser cache above** already removes repeat reads for each user.

Reconsider Redis only if a measured endpoint stays slow after the backend runs
next to the database. If added, it would be cache-aside, optional at runtime, and
limited to public reference data (departments, directory) with short TTLs.
