# Clinic AI Assistant — Gemini setup and operation

The floating assistant (decisions D96, D97, D100 in `ARCHITECTURE.md`) answers in
natural language and acts **only through the clinic's own backend**: doctors,
availability, appointments and counts always come from PostgreSQL, never from the
model. It is off until a provider, model and API key are configured.

## 1. Configure Gemini

1. Create an API key in Google AI Studio (aistudio.google.com) for a project
   **without billing** if you want to stay on the free tier.
2. In `backend/.env` (never commit it):

   ```env
   AI_PROVIDER=gemini
   GEMINI_API_KEY=your-key
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```

3. Check the model before using it:

   ```bash
   cd backend
   python -m app.cli.ai_check          # model metadata only (no generation)
   python -m app.cli.ai_check --smoke  # plus one tiny synthetic prompt
   ```

   This reports whether the model exists for your project and supports
   `generateContent`. **It cannot tell whether the model is free**: the API does
   not report that. Check the project's rate limits and billing status in Google
   AI Studio. The server uses exactly the configured model and never falls back to
   another (possibly paid) one; if the model is unavailable the assistant answers
   `AI_MODEL_UNAVAILABLE`. Alternatives to try: `gemini-3.1-flash-lite`,
   `gemini-2.5-flash-lite`.
4. Apply the migration and restart the backend:

   ```bash
   cd backend
   alembic upgrade head    # adds ai_usage and ai_messages.results (additive only)
   uvicorn app.main:app --reload
   ```

The key is read only by the backend (`google-genai` SDK). It is never sent to the
browser, logged, or returned by any endpoint; `/api/v1/ai/status` reports only
whether the assistant is configured and the model name.

## 2. Settings

| Variable | Default | Purpose |
|---|---|---|
| `AI_ENABLED` | `true` | Master switch. |
| `AI_PROVIDER` | `none` | `gemini` (also `anthropic`, `openai_compatible`). |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | — | Gemini credentials and model (`AI_API_KEY` / `AI_MODEL` also work). |
| `GEMINI_THINKING_LEVEL` | model default | Optional, e.g. `low`. |
| `AI_MAX_OUTPUT_TOKENS` | `1024` | Per model request (600 suggested for the free tier). |
| `AI_MAX_TOOL_CALLS` | `4` | Model round trips per message (alias `AI_MAX_TOOL_STEPS`). |
| `AI_MAX_HISTORY_MESSAGES` | `12` | Rolling window of earlier messages sent. |
| `AI_REQUEST_TIMEOUT_SECONDS` | `30` | Per model request. |
| `AI_DAILY_REQUEST_LIMIT` | `20` | Messages per user per clinic day (0 = none). |
| `AI_RATE_LIMIT_PER_MINUTE` | `5` | Messages per user per minute. |
| `AI_GLOBAL_DAILY_REQUEST_LIMIT` | `500` | Whole server, per day — keep below your project's quota. |
| `AI_GLOBAL_RATE_LIMIT_PER_MINUTE` | `15` | Whole server, per minute. |
| `AI_LOG_TOKEN_USAGE` | `true` | Log token counts (never content). |
| `AI_ACTION_TTL_MINUTES` | `15` | A proposed booking/cancellation/move expires after this. |
| `AI_PHI_ALLOWED` | `false` | Patient data may reach the provider. Keep `false` on free tiers. |
| `AI_ENABLE_MEDICAL_DOCUMENT_UPLOAD` | `false` | Document upload; also needs `AI_PHI_ALLOWED`. |
| `AI_CONVERSATION_RETENTION_DAYS` | `90` | Used by `python -m scripts.purge_ai_documents`. |
| `AI_DOCUMENT_RETENTION_DAYS` | `30` | Same script. |

Not implemented as settings: `AI_STORE_CONVERSATIONS` (conversations are always
stored: confirmations are bound to a stored message), `AI_REQUIRE_AUTH` (every AI
route always requires sign-in) and `AI_ALLOW_PAID_FALLBACK` (there is no fallback).

## 3. What it can do, by role

Tools run with the signed-in user's own permissions through the existing services;
a tool the user may not use is never offered, and calling it anyway fails.

| Tool | Who | Notes |
|---|---|---|
| `search_doctors`, `get_doctor_profile`, `list_departments`, `get_doctor_availability` | everyone | Public directory data; real free slots. |
| `get_clinic_help` | everyone | Fixed how-to answers and page links. |
| `get_dashboard_figures` | everyone | The same role-scoped counts as the dashboard. |
| `propose_booking` | patients with a record | Proposal only. |
| `get_my_appointments`, `propose_cancellation`, `propose_reschedule` | patients | Only with `AI_PHI_ALLOWED`. |
| `list_appointments` | doctors (own), front desk and admins (all) | Patient names reach the model only with `AI_PHI_ALLOWED`; staff still see them on result cards. |
| `find_patient`, `propose_booking_for_patient` | front desk | Only with `AI_PHI_ALLOWED`. |

Nothing is changed by the model. Bookings, cancellations and moves are
**proposals** stored on the assistant's message; the user presses **Confirm**, and
the server then re-checks permissions, the state machine and slot availability
through the normal services (booking uses an idempotency key and the booking
locks). A proposal can be decided once, only by its owner, and expires after
`AI_ACTION_TTL_MINUTES`.

## 3a. Medical record documents (D101)

Patients can ask "What documents have I uploaded?", "Explain my latest blood test" or
"Summarize all my reports"; doctors can ask about a patient through one of their
appointments. The tools `list_medical_documents`, `explain_medical_document`,
`summarize_medical_documents` and `show_my_profile` use the record's existing rules:
patients see their own documents, doctors only patients they have appointments with,
reception and administrators none. A guessed document id is simply "not found".

Documents are read **on this server** and only when the current message asks for them:

- **PDF:** text is extracted page by page (citations give the page). Password-protected,
  damaged or empty files are reported, not guessed.
- **Scanned pages and images:** read with local OCR when the `tesseract` command is
  installed on the server (bounded: 5 pages, 20 s each); otherwise the card says they
  could not be read. Install Tesseract to enable it; nothing is sent elsewhere for OCR.
- **Lab rows** ("Hemoglobin 13.6 g/dL 13.0-17.0 L") give test, result, unit, printed
  reference range and flag. A value is called above/below range only against the range
  printed on the report; dates are shown exactly as printed.
- **Summaries** go oldest first, compare a test only with the same test in the same unit,
  list unreadable documents with the reason, and process at most 10 documents per request.

Results are shown as cards (documents with View/Summarize, report with measurements,
general information about each test, notes and sources). With `AI_PHI_ALLOWED=false`
(free tier) the model receives only ids and counts, never titles, values or text, so it
cannot interpret them; the explanation shown is the server's own fixed, general text.
With an approved provider (`AI_PHI_ALLOWED=true`), the model also receives the fenced
text and parsed values and writes the explanation.

### Document reader v2 (D102)

- Tables are read by their header columns (test, result, unit, reference, flag) from the PDF's layout text, so values,
  units, references and flags stay together. Reference text ("Desirable <200 mg/dL") is never mistaken for a test.
- Each report yields typed findings: measurements (with source line and page), conditions stated in the report's
  interpretation (negated mentions and family history left out), symptoms, and the interpretation / follow-up text.
- A file is extracted once per content hash and extraction version; changing the reader bumps the version, so older
  results are never reused. Report cards saved in older conversations are marked as read by an earlier version.
- Questions are answered by focus: the disease, symptoms, the full table, each abnormal value, the follow-up, or a summary.
  "It" / "that report" means the conversation's active document (the last report shown); access is re-checked every time.
- `AI_ALLOW_SYNTHETIC_DOCUMENTS=true` (development only) lets the model explain documents that declare themselves
  synthetic/fictional; real reports still stay on the server unless `AI_PHI_ALLOWED=true`.
- Golden fixtures: `backend/tests/fixtures/medical/` (four synthetic PDFs), checked by `tests/test_medical_extraction.py`.

### Appointment history (D103)

Patients can ask about their own appointments in their own words ("which doctors did I visit", "whome I got appointment
in past", "who was my last doctor"): `get_my_appointments` returns only their own records (past, completed visits,
upcoming, cancelled, latest/earliest, by doctor or dates) with doctor, specialty, department, date, time and status.
Cancelled and missed appointments are labelled as not having taken place. Follow-ups ("which one was the latest?",
"show that doctor's profile") use the appointments just shown. With `AI_PHI_ALLOWED=false` the model sees only ids and
statuses; the answer itself is written by the server from the database.

### Follow-ups and multi-turn booking (D115)

- **Everyday words.** `search_doctors` maps lay words, other forms of a specialty and close misspellings
  ("heart doctors", "skin", "children's", "cardiolgist") to specialty stems (`services/ai/specialties.py`)
  and adds those doctors to the literal matches. Every result still comes from the directory.
- **What was shown is remembered.** Doctor lists and free times are saved as cards on the answer. On the next
  message the agent rebuilds the last list (ids, in display order) from those cards, and the model sees each
  earlier answer with a numbered note of the doctors (with `doctor_id`) and times it showed. Nothing extra is
  stored; conversations stay per user.
- **References.** `pick_from_previous` resolves "the first / second / last one", "the most / least experienced",
  "the cheapest", "the earliest available", a name, or a time ("5:30 pm") against that list, re-reading the
  records first. Ties and missing lists are reported, never guessed. Picking a doctor returns their fresh next
  free times; picking a time prepares the booking proposal.
- **Times of day.** `get_doctor_availability` takes `part_of_day` (morning < 12:00, afternoon 12-17,
  evening from 17:00).
- **Typed confirmation.** When the previous answer is a pending proposal, a clear "yes" / "confirm" or
  "no" / "cancel" reply is decided by the server through the same path as the buttons (permissions, slot,
  idempotency key), with no model call. Anything less clear goes to the model.
- **Failures.** A request that ends without an answer shows no cards or proposal from the attempt, and asks a
  specific question when doctors are on screen.
- **Links.** Answers never contain URLs: markdown links keep their text and absolute URLs are removed (server
  and renderer). Cards link with relative app routes.

## 4. Privacy and safety

- **Free tiers and patient data.** Google may use free-tier content to improve its
  products. Keep `AI_PHI_ALLOWED=false` there and use only synthetic test data.
  With it off, patient-record tools and document upload are disabled, and
  identifiers typed into messages (emails, phone numbers, MRNs, national ID
  numbers) are replaced with placeholders before the request; the stored
  conversation keeps the user's words. Redaction lowers exposure but does not make
  clinical text anonymous.
- **Emergencies.** Messages describing urgent symptoms (chest pain, difficulty
  breathing, stroke signs, severe bleeding, suicidal thoughts…) get fixed
  emergency guidance immediately, with no model call.
- **Not a doctor.** The system prompt forbids diagnosis and prescribing; answers are
  general information only.
- **Prompt injection.** The system prompt is not a security boundary: permissions
  are enforced in the tools and services. Document text is fenced and treated as
  data.
- **Rendering.** Answers are rendered with a safe Markdown subset (no raw HTML).
  Result cards show backend data only.

## 5. Cost controls

Per message: an emergency check (no tokens), the per-user and server limits
(refused with HTTP 429 before any model call), at most
`AI_MAX_HISTORY_MESSAGES` earlier messages, at most `AI_MAX_TOOL_CALLS` model round
trips, `AI_MAX_OUTPUT_TOKENS` per request, and no automatic retries. Every message
that reaches the model is recorded in `ai_usage` (model, tokens, tool calls,
outcome — never content), and failed attempts count too. Users see "N of M
messages left today" in the panel (`GET /api/v1/ai/usage/me`).

The server-wide limits count finished requests, so requests in flight at the same
moment can exceed them slightly; set them a little below your project's quota.

## 6. API

| Method | Path | |
|---|---|---|
| GET | `/api/v1/ai/status` | Configured?, model, capabilities and roles for this user. |
| GET | `/api/v1/ai/usage/me` | Today's messages, tokens and limits. |
| GET / DELETE | `/api/v1/ai/conversations[/{id}]` | Own conversations only. |
| POST | `/api/v1/ai/messages` | Send; returns the saved messages. |
| POST | `/api/v1/ai/messages/stream` | Same, as Server-Sent Events. |
| POST | `/api/v1/ai/conversations/{id}/messages/{id}/decision` | Confirm or cancel a proposal. |
| GET / POST / DELETE | `/api/v1/ai/documents` | Only when document upload is enabled. |

Error codes: `AI_NOT_CONFIGURED`, `AI_AUTH_FAILED`, `AI_MODEL_UNAVAILABLE`,
`AI_RATE_LIMITED`, `AI_QUOTA_EXHAUSTED`, `AI_TIMEOUT`, `AI_UNAVAILABLE` (503);
`AI_USER_RATE_LIMITED`, `AI_USER_DAILY_LIMIT`, `AI_SERVER_BUSY`,
`AI_SERVER_DAILY_LIMIT` (429); `AI_DOCUMENTS_DISABLED` (403).

## 7. Tests

All tests mock the model; no API key or credits are needed.

```bash
cd backend && python -m pytest tests/test_ai_agent.py tests/test_ai_gemini.py
cd frontend && npx vitest run src/components/assistant src/services
```

## 8. Production considerations

- Use a paid tier or another provider **with a data-processing agreement suitable for
  health data** before setting `AI_PHI_ALLOWED=true` or enabling document upload.
- Run `python -m scripts.purge_ai_documents --delete` daily for retention.
- Watch `ai_usage` (or the `ai_usage` log lines) for cost and failures.
- Medical-document analysis stays off until privacy, security and clinical
  safeguards are approved.

## 9. When a request fails (D108)

A failed question stays in the conversation, marked "Not sent". Under it, a compact
card says what happened. The explanation comes from the status and error code only,
never from server or provider text:

- **No answer, or the stream broke:** "Connection interrupted…". The server may have
  finished and saved the answer, so Try again first looks for it in the
  conversation and shows it instead of asking again.
- **Timeout:** "This request is taking longer than expected…"
- **Rate limited:** "The assistant is receiving too many requests right now…"
- **Server or provider error (5xx):** "The assistant is temporarily unavailable…"
- **Daily limit, or a clinic rule** (e.g. documents switched off): our own message.
  No Try again, because the same request would fail again.
- **Anything else:** "Something went wrong while preparing your response…"

**What Try again does:**
- It sends the same text and the same document ids, once at a time.
- The user's message is not duplicated, and the thinking words show while it runs.
- What had arrived of a failed answer stays, marked "Response interrupted"; a retry
  replaces it rather than appending to it.
- Dismiss puts the text and files back in the composer. Stop works as before.

**Actions:**
- Booking, cancelling and rescheduling run only through the confirmation call,
  which is idempotent on the server: pending-only, a row lock, and the booking key
  `ai-<message id>`.
- If that call gets no answer, or a server error, the card shows **Check status**
  instead of Confirm. It reloads the message's real outcome before anything can be
  decided again.
