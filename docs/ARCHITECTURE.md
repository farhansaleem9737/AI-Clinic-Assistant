# Clinic AI Assistant — Master Architecture

**Status:** authoritative. When a per-entity prompt conflicts with this document, the conflict is
raised and resolved before implementation.
**Scope:** analysis and decisions only. No entity models, no migrations.
**Baseline reviewed:** `backend/app` (User + auth only), `frontend/src` (auth context + 3 pages).

---

## 0. Decisions at a glance

| # | Decision | Choice | Rejected |
|---|---|---|---|
| D1 | Identity split | `User` = credentials + account. Profiles hold domain data. | One fat user table |
| D2 | Patient without account | `patients.user_id` **nullable + unique** | `1:1 NOT NULL` (breaks walk-in registration) |
| D3 | Roles | DB tables (`roles`, `permissions`, M2M) + `StrEnum` mirror in code | Bare enum column; hardcoded `if role ==` |
| D4 | User↔Role | **many-to-many** | Single `role_id` FK |
| D5 | Authorization | Two layers: RBAC gate (permission) + ReBAC gate (relationship to *this* row) | Permissions alone |
| D6 | Primary keys | UUIDv7 for externally addressable rows; BIGINT for `audit_log`, `ai_message` | Sequential int everywhere (enumerable PHI) |
| D7 | Refresh tokens | Opaque, hashed, in DB, rotating, with family reuse-detection | JWT refresh tokens; no refresh at all |
| D8 | Token transport | Access token in memory; refresh in `HttpOnly` cookie scoped to the refresh path | `localStorage` (current code) |
| D9 | Availability | Computed from templates at read time; **no slot table** | Materialised slots |
| D10 | Double-booking | PostgreSQL `EXCLUDE USING gist` on `(doctor_id, during)` | Application-level check |
| D11 | Time | `timestamptz` everywhere; clinic IANA tz stored explicitly | Naive `datetime.utcnow()` (current code) |
| D12 | `rescheduled` | A *transition* → cancel + new row via `rescheduled_from_id` | A resting status |
| D13 | AI data access | AI calls the same service functions with the same principal | Text-to-SQL; privileged AI DB user |
| D14 | Clinical notes | Append-only; amendments create versions | `UPDATE` in place |
| D15 | Deletion | Status/deactivation for clinical + identity; hard delete only for join rows and expired tokens | Blanket `deleted_at` |
| D16 | Enums | Native PG enum for closed developer-owned sets; lookup tables for business-editable sets | Unconstrained `VARCHAR` |
| D17 | Repositories | No generic repository layer; services + focused query modules | Repository-per-entity ceremony |
| D18 | Tests | Real PostgreSQL, `httpx.AsyncClient`, table-driven authz matrix | SQLite; sync `TestClient` |

---

## 1. Actors

| Actor | Has account | Primary concern | Never gets by default |
|---|---|---|---|
| **Patient** | yes (or record-only, unclaimed) | own record, booking, AI | any other patient's data |
| **Doctor** | yes | assigned patients, schedule, clinical notes | unrelated patients |
| **Receptionist** | yes | registration, booking, queue, check-in | clinical note bodies |
| **Administrator** | yes | users, roles, departments, config, audit | clinical note bodies (needs explicit grant + audit) |
| **Nurse / Pharmacist / Lab tech / Clinic manager** | yes | future clinical + operational | — |
| **AI Assistant** | no — not a principal | acts *as* the caller | any capability the caller lacks |
| **Anonymous visitor** | no | public directory, FAQ, registration | everything else |

The AI is **not an actor with its own identity**. It is a delivery channel for the authenticated
user's own permissions. This is the single most important security statement in the document.

---

## 2. Entity inventory

### Core — build these

| # | Entity | Responsibility |
|---|---|---|
| 1 | `User` | Authentication identity + account lifecycle. Nothing clinical. |
| 2 | `Role` | Named bundle of permissions. Admin-manageable. |
| 3 | `Permission` | Atomic capability, `resource:action`. Developer-owned, seeded. |
| 4 | `RolePermission` | M2M join. |
| 5 | `UserRole` | M2M join + `granted_by`, `granted_at`, `expires_at`. |
| 6 | `RefreshToken` | Rotating session family, hashed. |
| 7 | `AuditLog` | Append-only record of security- and PHI-relevant events. |
| 8 | `Department` | Organisational unit; owns IANA timezone. |
| 9 | `Specialty` | Lookup; M2M with Doctor. |
| 10 | `Doctor` | Professional profile. No schedule, no credentials. |
| 11 | `StaffProfile` | Receptionist/nurse/etc. — one table, `staff_type` discriminator. |
| 12 | `Patient` | Clinical-legal identity + MRN. Not the medical history. |
| 13 | `ScheduleTemplate` | Recurring weekly availability with validity window. |
| 14 | `ScheduleException` | Leave, holiday, block, or extra availability. Overrides templates. |
| 15 | `Appointment` | The booking. Owns `during tstzrange`, status, participants. |
| 16 | `AppointmentStatusHistory` | Every transition: from, to, actor, reason, at. |

### Secondary — after the core works

| # | Entity | Notes |
|---|---|---|
| 17 | `Notification` | The logical event + in-app inbox row. |
| 18 | `NotificationDelivery` | Per-channel attempt, status, retries. Separate from #17. |
| 19 | `NotificationPreference` | Per user × type × channel opt-out. |
| 20 | `QueueEntry` | Today's waiting room. Short-lived, high-churn. |
| 21 | `Encounter` | A visit. 0..1 ↔ 1 with a completed Appointment. |
| 22 | `ClinicalNote` | Versioned, signed, append-only. Attached to Encounter. |
| 23 | `AIConversation` | Owned by a **User**, not a Patient. |
| 24 | `AIMessage` | Ordered turn; role user/assistant/system/tool. |
| 25 | `AIToolCall` | Tool name + `JSONB` arguments + outcome. |
| 26 | `Attachment` | Object-storage pointer + access policy. |

### Postponed — do not model now

`Prescription`, `Medication`, `LabTest`, `LabResult`, `Invoice`, `Payment`, `Referral`,
`EmergencyContact`, `InsurancePolicy`, `PatientAllergy`, `PatientCondition`, `MessageThread`
(patient↔clinician chat), `Review`, `Location`/multi-clinic tenancy, FHIR/HL7 resources.

Each is a real entity, not a column. Nothing above gets stuffed into `Patient` as a JSON blob.

---

## 3. Relationships — corrections to the proposed model

| Proposed | Verdict | Corrected |
|---|---|---|
| `User 1 — 1 Doctor` | OK | `users.id` ← `doctors.user_id` **UNIQUE NOT NULL** |
| `User 1 — 1 Patient` | **wrong** | `patients.user_id` **UNIQUE NULLABLE** — reception registers patients who never log in; the account is claimed later |
| `Department 1 — N Doctor` | incomplete | `doctors.primary_department_id NOT NULL` now; add `doctor_departments` M2M when a doctor covers two departments |
| `Patient 1 — N Appointment` | OK | plus `booked_by_user_id` — who created it ≠ who it is for |
| `Doctor 1 — N Appointment` | OK | `doctor_id` **NOT NULL** — required by the overlap constraint (D10) |
| `Doctor 1 — N Schedule` | OK | split into `ScheduleTemplate` + `ScheduleException` |
| `Patient 1 — N AIConversation` | **wrong** | `User 1 — N AIConversation`. Doctors and staff use the assistant too. (The brief's §7 and §12 contradict each other; §12 is right.) |
| `AIConversation 1 — N AIMessage` | OK | `ON DELETE CASCADE`; index `(conversation_id, created_at)` |
| `User 1 — N Notification` | OK | plus `Notification 1 — N NotificationDelivery` |
| `User 1 — N AuditLog` | incomplete | `actor_user_id` **NULLABLE** — failed logins for unknown emails have no user |

### Cardinality summary

- **One-to-one:** User↔Doctor, User↔StaffProfile, User↔Patient *(0..1)*, Appointment↔Encounter *(0..1)*.
- **One-to-many:** Department→Doctor, Doctor→Appointment, Patient→Appointment,
  Doctor→ScheduleTemplate, Doctor→ScheduleException, Appointment→StatusHistory,
  User→AIConversation, AIConversation→AIMessage, User→Notification,
  Notification→NotificationDelivery, User→RefreshToken, Encounter→ClinicalNote.
- **Many-to-many:** User↔Role, Role↔Permission, Doctor↔Specialty, (later) Doctor↔Department.

### Cascade policy

| Parent → child | Rule | Why |
|---|---|---|
| AIConversation → AIMessage | `CASCADE` | Conversation is the unit of ownership |
| Notification → Delivery | `CASCADE` | Delivery has no standalone meaning |
| User → RefreshToken | `CASCADE` | Sessions die with the account |
| User → Patient / Doctor / Staff | `RESTRICT` | Deactivate the user, never delete |
| Anything → AuditLog | `RESTRICT` / `SET NULL` on actor | Audit outlives its subject |
| Appointment → StatusHistory | `RESTRICT` | Appointments are cancelled, never deleted |

---

## 4. Authentication architecture

```
POST /auth/login   ──► verify password (bcrypt) ──► issue:
                                                    access  JWT    10–15 min   in memory
                                                    refresh opaque 14–30 days  HttpOnly cookie
POST /auth/refresh ──► hash lookup → rotate → new pair; reuse ⇒ revoke whole family + audit
POST /auth/logout  ──► revoke family; clear cookie
```

**Access token claims:** `sub` (user UUID), `jti`, `iat`, `exp`, `roles` (short codes),
`tv` (token version). No permission list — permissions resolve server-side from a cached
role→permission map so a role change takes effect on the next request, not the next hour.

**Refresh token:** 32 random bytes, stored as SHA-256, never as a JWT. Row carries
`family_id`, `expires_at`, `revoked_at`, `replaced_by_id`, `user_agent`, `ip`.
Presenting an already-rotated token is a breach signal: revoke the family, write an audit
event, force re-login.

**Account hardening:** email verification, `failed_login_count` + `locked_until`, single-use
hashed password-reset tokens, password change revokes all families, uniform response on
register/forgot-password so email existence cannot be probed.

**Registration creates a patient or a doctor *applicant*, nothing else.** `POST /api/v1/auth/register`
takes `account_type` = `patient` (default) or `doctor`, ignores any role in the body, and rejects any
other account type. A doctor applicant has no clinical access until an administrator approves the
application (D77). Staff accounts are created by an admin through an invitation flow.

---

## 5. Authorization — two layers

**Layer 1 — RBAC (coarse, in the dependency).** `require_permission("appointment:create")`
answers *can this kind of user do this kind of thing*. Fails fast with 403.

**Layer 2 — ReBAC (fine, in the service).** Answers *may this user touch this row*.
One choke point per protected resource, e.g. `PatientAccessPolicy.assert_can_read(user, patient)`:

| Caller | Rule |
|---|---|
| Patient | `patient.user_id == user.id` |
| Doctor | an appointment or encounter links doctor↔patient (later: a care-team row) |
| Receptionist | operational fields only, department-scoped |
| Admin | allowed, always audited |
| Break-the-glass | allowed with a mandatory reason, loudly audited *(future)* |

**Layer 3 — serialization.** Even an authorized read returns a role-appropriate schema:
`PatientPublicRead` / `PatientAdministrativeRead` / `PatientClinicalRead`. Filtering the query
but reusing one response model is how PHI leaks.

**Existence is sensitive.** For patients, appointments and clinical notes return **404**, not 403,
when the caller has no relationship — a 403 confirms the record exists.

### Permission vocabulary (seeded, `resource:action`)

```
user:        read create update deactivate assign_role
role:        read create update delete
patient:     read_own read_assigned read_any create update merge
doctor:      read create update deactivate
schedule:    read manage_own manage_any
appointment: read_own read_assigned read_any create
             cancel_own cancel_any check_in transition
clinical:    note_read note_create note_amend note_sign
queue:       read manage
ai:          use_patient use_clinical
audit:       read
```

Permissions are a **closed set defined in code** and seeded by migration. Roles are open and
admin-composable. Never invent a permission at runtime.

---

## 6. Data ownership

| Entity | Create | Read | Update | Delete |
|---|---|---|---|---|
| User | self (patient) / admin | self, admin | self (limited), admin | never — deactivate |
| Patient | self, receptionist, admin | owner, related clinician, ops staff, admin | owner (contact + personal details, audited; D99), staff, admin | never — deactivate/merge |
| Doctor | admin | public (listed subset), authenticated (full) | own profile, admin | never — deactivate |
| Department | admin | public | admin | never — deactivate |
| ScheduleTemplate | doctor (own), admin | staff, patients (as availability) | doctor (own), admin | soft — `is_active`/`valid_until` |
| Appointment | patient (self), staff, doctor | patient, assigned doctor, ops staff, admin | status transitions only | never — cancel |
| ClinicalNote | clinician on the encounter | authoring clinician, treating clinicians, patient *(future portal)* | amend-as-new-version only | never |
| Notification | system | recipient only | recipient (`read_at`) | purge after retention |
| AIConversation | owning user | owning user only | owning user | user may delete; audit records that they did |
| AuditLog | system | `audit:read` | **nobody** | **nobody** |

`audit_log` should have `UPDATE` and `DELETE` revoked from the application role at the database
level. Append-only is a grant, not a convention.

---

## 7. Public vs authenticated

Public (no token) — rate-limited, cacheable, no PHI:

| Endpoint | Exposes |
|---|---|
| `GET /api/v1/public/departments` | name, description |
| `GET /api/v1/public/doctors` | only `is_publicly_listed = true`: name, photo, specialties, department, languages, bio, accepting-new-patients, fee |
| `GET /api/v1/public/doctors/{slug}` | same subset — **never** availability detail, email, phone, or internal id |
| `GET /api/v1/public/faq`, `/health/live`, `/health/ready` | static |
| `POST /auth/register`, `/auth/login`, `/auth/forgot-password` | uniform responses, strict throttle |

Everything else requires a token **and** a permission **and**, for row-scoped resources, a
relationship. Being logged in is never sufficient.

---

## 8. Appointment workflow

```
                    ┌──────────► cancelled ◄──────────┐
                    │                                 │
 requested ──► scheduled ──► confirmed ──► checked_in ──► in_progress ──► completed
                    │            │
                    └────────────┴──────► no_show          (after start + grace)
```

`rescheduled` is **not** a state. Rescheduling = cancel the old row with
`cancellation_reason = RESCHEDULED` + create a new row carrying `rescheduled_from_id`.
The chain stays queryable and the state machine stays acyclic.

| Transition | Who | Guard |
|---|---|---|
| → `requested` | patient | slot open, lead time honoured |
| `requested` → `scheduled` | staff, doctor, or automatic on self-service booking | overlap constraint holds |
| `scheduled` → `confirmed` | patient, staff | — |
| `*` → `checked_in` | receptionist | on the day, within window |
| `checked_in` → `in_progress` | doctor, nurse | — |
| `in_progress` → `completed` | doctor | — |
| pre-check-in → `cancelled` | patient (inside window), staff, doctor | reason required |
| `scheduled`/`confirmed` → `no_show` | staff, doctor | now > start + grace |

Implemented as a single `AppointmentStateMachine` — a `{from: {to: required_permission}}` map
plus guard callables. Routers never test `status ==`. Every transition writes a history row in
the same transaction.

**Concurrency.** Two patients booking 10:00 is resolved by the database, not by a read-then-write:

```sql
EXCLUDE USING gist (doctor_id WITH =, during WITH &&)
  WHERE (status NOT IN ('cancelled','no_show'))
```

plus the mirror constraint on `patient_id`. Requires `btree_gist`. The service catches
`IntegrityError` on that constraint name and returns **409 Conflict**. Add an
`Idempotency-Key` header on `POST /appointments` so a retried request cannot double-book.

---

## 9. Doctor scheduling workflow

```
ScheduleTemplate   (doctor, weekday, start_time, end_time, slot_minutes, valid_from, valid_until)
      minus
ScheduleException  (LEAVE | HOLIDAY | BLOCK | EXTRA_AVAILABILITY, over a tstzrange)
      minus
existing appointments  +  buffer_minutes
      bounded by  min_lead_time, max_advance_days
      =  available slots
```

Templates store **local wall-clock time** (`TIME`) plus a weekday; they are expanded in the
department's IANA timezone, so a 09:00 clinic stays 09:00 across a DST boundary. Everything
persisted is `timestamptz`. `Doctor` holds no schedule fields whatsoever.

Availability results are cached in Redis for 30–60 s, keyed by `avail:{doctor_id}:{date}`,
invalidated on any booking, cancellation, template change or exception.

---

## 10. Patient data boundaries

| Belongs on | Fields |
|---|---|
| `User` | email (login), password_hash, status, locale, timezone, MFA, last_login_at |
| `Patient` | MRN, legal name, DOB, sex at birth, gender identity, contact phone/email, address, preferred language, `registered_by_user_id`, `user_id` (nullable) |
| `Encounter` | the visit: chief complaint, start/end, doctor, appointment link |
| `ClinicalNote` | assessment, plan, structured/SOAP body, signature, version chain |
| `Appointment` | reason for visit (patient's own words), type, status, participants |
| *(future tables)* | allergies, conditions, medications, vitals, documents |

A patient's account email and their contact email are different facts and may differ. So are
their account display name and their legal name — model both, don't collapse them.

---

## 11. AI assistant architecture

> Implemented as described in D96, D97 and D100; setup and operation: `docs/AI_ASSISTANT.md`.

```
 React ──SSE──► /api/v1/ai/conversations/{id}/messages
                        │
                        ▼
                 AIOrchestrator          ← role-specific system prompt + tool set
                        │
             ┌──────────┴──────────┐
             ▼                     ▼
      Anthropic API          Tool layer  ── each tool wraps a SERVICE function
      (claude-opus-5)                        and receives the SAME current_user
                                             ⇒ identical authorization path as REST
                                             ⇒ no SQL, no ORM, no privileged client
```

**Rules**

1. The model never sees a database connection and never generates SQL.
2. Every tool is a thin wrapper over an existing service call taking `current_user`. If the REST
   caller would get a 403, the tool raises the same domain error and the model is told
   "not permitted".
3. Tool sets are role-scoped:
   - *Patient*: `search_doctors`, `list_departments`, `get_doctor_availability`,
     `get_my_appointments`, `draft_appointment_request` (proposes; the human confirms in UI).
   - *Clinician*: `get_my_schedule`, `get_patient_summary` (relationship-gated),
     `summarize_encounter`, `search_clinic_policy`.
   - *Reception*: `find_patient`, `get_doctor_availability`, `get_queue_state`.
4. **No write is executed by the model.** Booking, cancelling and status changes are *proposed*
   and confirmed by an explicit user action.
5. **Safety**: deterministic pre-filter for emergency red flags → emergency banner, bypass the
   model; system prompt forbidding diagnosis and dosing; post-generation check; `safety_flag`
   persisted on the message.
6. **Prompt injection**: patient-authored free text and tool results are data. Wrap them, label
   them untrusted, and never let them widen the tool set.
7. **PHI boundary** — a policy decision required before launch: minimise identifiers in prompts,
   confirm the provider's retention/BAA posture, and log request *metadata* (tokens, latency,
   model, tool names) rather than message bodies.

### Model and API choices (Anthropic Python SDK)

| Concern | Choice |
|---|---|
| Model | `claude-opus-5` for the assistant; `claude-haiku-4-5` for cheap classification (intent routing, red-flag triage, conversation titling) |
| Thinking | `thinking={"type": "adaptive"}` — do **not** pass `budget_tokens`, it is removed on Opus 5 |
| Effort | `output_config={"effort": "low"}` for routing/titles, `"high"` for clinical summarisation |
| Streaming | `client.messages.stream(...)` forwarded to the browser over SSE |
| Tools | `strict=True` on every tool definition; `additionalProperties: false` + `required` |
| Caching | `cache_control={"type":"ephemeral"}` on the stable system prompt + clinic-context prefix. Volatile content (timestamps, the user's question) goes *after* the last breakpoint or the cache never hits. Verify with `usage.cache_read_input_tokens`. |
| Cost control | per-user Redis token bucket + monthly ceiling; `usage` persisted per message |

## 12. AI conversation model

`AIConversation` — `id`, `user_id`, `title`, `context_type`
(`PATIENT_GENERAL | CLINICAL_ASSIST | STAFF_ASSIST`), `model`, `is_archived`, timestamps.

`AIMessage` — `id (BIGINT)`, `conversation_id`, `role` (`user | assistant | system | tool`),
`content`, `token_count`, `model`, `latency_ms`, `safety_flag`, `created_at`.

`AIToolCall` — `message_id`, `tool_name`, `arguments JSONB`, `status`, `result_summary`.
This is the one justified `JSONB` column in the schema: tool arguments are genuinely schemaless.

---

## 13. Notification architecture

```
domain event ─► Notification (the record, in-app inbox)
                     │
                     ├─► NotificationDelivery(IN_APP)    immediate
                     ├─► NotificationDelivery(EMAIL)     Celery task, retry w/ backoff
                     └─► NotificationDelivery(SMS/PUSH)  future
```

Splitting record from delivery lets one logical notification fan out with independent retry and
per-channel status. `NotificationPreference` gates each channel per type.

**No PHI in outbound email or SMS.** "You have an appointment tomorrow at 10:00 — sign in for
details." Never the doctor, department, or reason.

Reminders run on Celery Beat over a window (`now+24h`, `now+24h+5min`) with a unique
`dedupe_key` so a worker restart cannot double-send.

---

## 14. Real-time — where it actually earns its place

| Feature | Transport | Why |
|---|---|---|
| AI response streaming | **SSE** | one-way token stream; native reconnect |
| Notification inbox push | **SSE** | one-way, low frequency |
| Appointment status on a patient's open page | **SSE** | one-way |
| Waiting-room queue board | **WebSocket** | bidirectional, staff reorder/call-next, high churn |
| Patient↔clinician chat *(if ever built)* | **WebSocket** | bidirectional |
| Everything else | plain HTTP | polling a dashboard is fine |

`EventSource` cannot set headers — authenticate SSE with the refresh cookie or a short-lived,
single-use stream token, never by putting the access JWT in a query string that gets logged.
With more than one worker process, in-memory connection registries break: fan out through
**Redis Pub/Sub**.

---

## 15. Redis

| Use | Notes |
|---|---|
| Rate limiting | login, register, refresh, AI, public search |
| Cache | departments, public doctor directory, computed availability (30–60 s), role→permission map |
| Celery broker + result backend | |
| Real-time fan-out | Pub/Sub across uvicorn workers |
| Ephemeral counters | failed logins, reset-token throttles, idempotency keys |
| Optional slot hold | `SET key val NX PX 300000` while a patient completes booking |

Not used for: durable state, the authoritative session store, or anything that must survive a
flush. PostgreSQL remains the source of truth.

---

## 16. Background work — BackgroundTasks vs Celery

**Rule: if losing it silently would be a bug, it goes to Celery.**

| FastAPI `BackgroundTasks` | Celery |
|---|---|
| in-process, dies with the worker, no retry, no visibility | durable queue, retries, backoff, scheduling, monitoring |
| cache invalidation | email / SMS delivery |
| non-critical metrics | appointment reminders (Beat) |
| best-effort read-access logging | report and export generation |
| | nightly cleanup of expired refresh tokens, stale queue entries |
| | document processing, batch AI summarisation |

**Trap:** Celery workers are synchronous. Do not call the async session from a task. Keep a
second, sync `sessionmaker` over the same models — SQLAlchemy models are engine-agnostic.
(`taskiq` or `arq` are natively async alternatives if you would rather not run two engines.)

---

## 17. API architecture

```
/api/v1
  /auth          register login refresh logout me verify-email
                 forgot-password reset-password change-password
  /users         (admin)   /roles (admin)   /permissions (read-only)
  /public        departments doctors faq
  /patients      /patients/{id}/appointments
  /doctors       /doctors/{id}/availability
  /departments   /specialties
  /appointments  /appointments/{id}/status
  /schedules     /schedule-exceptions
  /queue
  /encounters    /clinical-notes
  /notifications /notifications/stream                      (SSE)
  /ai            /ai/conversations/{id}/messages            (SSE)
  /admin         /admin/audit-logs
  /ws/queue                                                 (WebSocket)
```

- One router per resource, composed in `api/v1/router.py`. Never one mega-router.
- **Cursor (keyset) pagination** for appointments `(starts_at, id)`, AI messages and audit logs
  `(created_at, id)`. Offset pagination only for small admin tables — never `OFFSET 50000`.
- Typed filter models per resource; `pg_trgm` + GIN for name search, `tsvector` for bios.
- `Idempotency-Key` on `POST /appointments`.
- `ETag` / `If-None-Match` on public directory endpoints.

### Error contract

```json
{"error": {"code": "APPOINTMENT_SLOT_TAKEN",
           "message": "That time is no longer available.",
           "details": {"doctor_id": "…", "starts_at": "…"},
           "request_id": "01J…"}}
```

| Status | Used for |
|---|---|
| 400 | malformed request |
| 401 | missing/invalid/expired token |
| 403 | authenticated, lacks permission, existence not sensitive |
| 404 | not found **or** no relationship to a sensitive resource |
| 409 | slot taken, duplicate email, stale version |
| 422 | Pydantic validation |
| 429 | rate limit; include `Retry-After` |
| 500 | `request_id` only — never a driver message |

Global handlers translate `IntegrityError` → 409 and domain exceptions → their status. Services
raise **domain exceptions, never `HTTPException`** — that is what lets Celery tasks and AI tools
reuse them.

---

## 18. Backend layering

```
Router        HTTP only: parse, delegate, serialize.   No ORM queries. No business rules.
  ↓
Dependencies  session, current_user, require_permission, pagination, rate limit.
  ↓
Service       business rules, transactions, authorization decisions, domain exceptions.
  ↓            ← Celery tasks and AI tools enter HERE, not at the router
Query module  complex/reused SQL only (add when a service outgrows inline queries).
  ↓
SQLAlchemy 2.x async  →  PostgreSQL
```

No generic repository layer. It duplicates the session API, fights eager-loading, and pays for a
database swap that will not happen. Extract a focused query module when a query is reused three
times or a service passes ~200 lines.

---

## 19. PostgreSQL principles

- `timestamptz` for every instant; `date` for birthdays; `time` for template wall-clock.
- `Numeric(10,2)` for money. Never `float`.
- UUIDv7 PKs (PostgreSQL 18 has a native `uuidv7()`; on earlier versions generate in Python with
  `uuid-utils` / `uuid6` — verify what your server supports).
- Native PG enums for `appointment_status`, `user_status`, `ai_message_role`,
  `notification_channel`. Lookup tables for anything the business edits.
  Alembic does **not** autogenerate enum value additions — write those by hand.
- Set a `MetaData(naming_convention=...)` on `Base` **before** more tables exist, so constraint
  names are stable and Alembic diffs stay clean.
- Extensions: `btree_gist` (overlap constraints), `pg_trgm` (search), optionally `citext` (email).
- Partial and composite indexes matched to real queries:
  `(doctor_id, starts_at) WHERE status NOT IN ('cancelled','no_show')`,
  `(patient_id, starts_at DESC)`, `(conversation_id, created_at)`.
- Consider partitioning `audit_log` and `ai_message` by month once volume warrants.
- Row-Level Security is a genuine defence-in-depth option but interacts badly with pooling and a
  single app role. Skip it in v1 — but keep every patient read behind one policy object so RLS
  can be added later without touching routers.
- Behind PgBouncer in transaction mode, disable asyncpg's prepared-statement cache.
- Migrations run as a deploy step. Never `Base.metadata.create_all()` in application code.

---

## 20. Soft delete vs hard delete vs archive

| Entity | Policy |
|---|---|
| `UserRole`, `RolePermission` | **hard delete** |
| `RefreshToken` | hard delete after expiry, by scheduled job |
| `QueueEntry` | hard delete / archive nightly |
| `Notification` | purge read notifications after retention |
| `AIConversation` | user-initiated delete allowed; the deletion itself is audited |
| `User` | **never delete** — `status = DEACTIVATED` (audit logs reference it) |
| `Doctor`, `Department`, `Specialty` | `is_active = false` |
| `ScheduleTemplate` | `is_active` + `valid_until` |
| `Patient` | never delete — deactivate or merge duplicates |
| `Appointment` | never delete — cancel |
| `ClinicalNote` | never delete, never edit — amend as a new version |
| `AuditLog` | never, enforced by database grants |

Do not add `deleted_at` everywhere. Where a record can be retired, use a **status enum** — because
*why* it was retired (suspended ≠ deactivated ≠ merged) is information the system needs.

Right-to-erasure conflicts with medical retention law. Implement it as **pseudonymisation**
(scrub identifiers, keep the clinical and audit skeleton with a tombstone), not deletion. That is
a policy decision, not a code decision — settle it before you promise a delete button.

---

## 21. Audit logging

Columns: `id BIGINT`, `occurred_at`, `actor_user_id` *(nullable)*, `actor_ip inet`,
`actor_user_agent`, `action` (e.g. `appointment.status_changed`), `resource_type`, `resource_id`,
`outcome` (`SUCCESS | DENIED | ERROR`), `request_id`, `metadata JSONB`.

`metadata` holds ids and **changed field names**, never PHI values. Log that the note changed,
not what it said.

| Event class | Write path |
|---|---|
| Login, failed login, lockout, token reuse, permission change, role grant | **in the same transaction** — if the audit write fails, the action fails |
| Appointment create/transition, patient create, note create/sign | in-transaction |
| PHI *read* access (high volume) | asynchronous but durable — buffer and drain, never fire-and-forget |

---

## 22. Testing architecture

```
tests/
  conftest.py     engine, per-test transaction rollback, app override
  factories/      user, patient, doctor, appointment builders
  unit/           state machine, availability maths, password policy
  api/            endpoint contracts per router
  security/       test_authz_matrix.py   ← the highest-value file in the repo
  integration/    booking concurrency, reminder scheduling, SSE stream
```

- **Real PostgreSQL** (testcontainers or a compose service). SQLite silently lacks `timestamptz`
  semantics, native enums, `EXCLUDE` constraints, partial indexes and `JSONB` — the exact features
  this design depends on.
- `pytest-asyncio` + `httpx.AsyncClient(transport=ASGITransport(app))`. The sync `TestClient`
  cannot properly exercise an async session.
- Isolation: outer transaction + nested savepoint per test, session bound to that connection.
- `as_user(role, **rel)` fixture returning an authenticated client.
- **Authorization matrix**: parametrise (actor role × endpoint × relationship) → expected status.
  Patient B reading Patient A → 404. Doctor with no appointment → 404. Receptionist reading a
  clinical note → 403. Anonymous on anything protected → 401.
- Freeze time (`time-machine`) for schedule, reminder and no-show tests.
- Concurrency: fire two bookings for one slot in parallel; assert exactly one 201 and one 409.
- Mock the model provider at the HTTP boundary (`respx`) or behind a provider protocol.
  Never call the real API in CI.

---

## 23. Deployment architecture

```
Internet ──► Nginx (TLS, static React build, /api proxy, gzip)
                │
                ├─► Gunicorn + UvicornWorker ──► FastAPI ──► PostgreSQL (managed, PITR)
                │                                        └─► Redis
                ├─► Celery worker
                └─► Celery beat
```

- Migrations as a distinct job before the app rolls — never on startup with multiple workers.
- `/health/live` (process) and `/health/ready` (DB + Redis) are different endpoints.
- Structured JSON logs with `request_id`; Sentry; DB and Redis metrics.
- `echo=True` on the engine logs query parameters — that is PHI in your logs. Dev only.
- Secrets from the platform's secret manager. `.env` never enters an image.
- CI: ruff → mypy → pytest (with postgres + redis services) → `alembic check` for drift →
  `pip-audit` → build → deploy.

---

## 24. Recommended structure

```
backend/
├── alembic/{env.py,versions/}
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── deps/{db.py,auth.py,rbac.py,pagination.py,ratelimit.py}
│   │   └── v1/{router.py,endpoints/*.py}
│   ├── core/{config.py,security.py,exceptions.py,logging.py,enums.py,redis.py}
│   ├── db/{base.py,session.py,mixins.py,types.py}
│   ├── models/{user.py,rbac.py,patient.py,doctor.py,department.py,
│   │           schedule.py,appointment.py,clinical.py,notification.py,ai.py,audit.py}
│   ├── schemas/                      # mirrors models + per-role read models
│   ├── services/
│   │   ├── access/{patient_access.py,policies.py}
│   │   └── {auth,user,patient,doctor,availability,appointment,
│   │         appointment_state,queue,notification,audit}_service.py
│   ├── ai/{client.py,orchestrator.py,tools/,prompts/,safety.py,streaming.py}
│   ├── realtime/{sse.py,ws.py,broker.py}
│   └── workers/{celery_app.py,beat.py,tasks/}
├── tests/                            # see §22
├── pyproject.toml
└── Dockerfile

frontend/src/
├── app/{App.jsx,routes.jsx,providers.jsx}
├── lib/
│   ├── api/{client.js,endpoints/}    # axios + single-flight refresh interceptor
│   └── auth/{AuthProvider.jsx,useAuth.js,RoleGuard.jsx,permissions.js}
├── components/{ui/,layout/}
├── layouts/{Public,Patient,Doctor,Staff,Admin}Layout.jsx
├── features/{auth,doctors,departments,appointments,schedule,queue,ai,
│             notifications,patients,admin}/
└── pages/{Landing,About,FAQ,NotFound}.jsx
```

Frontend notes: role-based routing is **cosmetic** — the backend is the enforcement point. Never
read roles out of a decoded JWT for anything but hiding a menu item. The axios refresh interceptor
must be single-flight (queue concurrent 401s behind one refresh) or a page firing six parallel
requests will rotate the token six times and trip reuse detection. TanStack Query is strongly
recommended over hand-rolled `useState`/`useEffect` for server state; it wraps axios cleanly.

---

## 25. Problems and conflicts in the current codebase

| # | Severity | Issue | Location |
|---|---|---|---|
| 1 | **critical** | `/auth/register` accepts `role` from the request body — anyone can register as `admin` | `app/api/routes/auth.py` |
| 2 | **critical** | Baseline migration `5fe0b8c8ede5` has `pass` in `upgrade()` — the schema is not actually under Alembic control; every future autogenerate will be wrong | `alembic/versions/` |
| 3 | high | Access token in `localStorage`; no refresh token at all | `frontend/src/services/api.js`, `core/security.py` |
| 4 | high | `role` is a free-text `String(50)` on `users` — conflicts with the RBAC design | `app/models/user.py` |
| 5 | high | Naive `DateTime` + `datetime.utcnow` — wrong foundation for a scheduling product | `app/models/user.py` |
| 6 | high | Integer PK exposes sequential, enumerable ids for future patient records | `app/models/user.py` |
| 7 | medium | Two competing router trees: `api/routes/` (mounted, unversioned) and `api/v1/` (empty) | `app/main.py` |
| 8 | medium | `echo=True` will log query parameters — PHI in logs once real data exists | `app/db/database.py` |
| 9 | medium | `requirements.txt` is UTF-16 (PowerShell `>` redirect); `pip install -r` will likely fail | `backend/requirements.txt` |
| 10 | medium | Not a git repository, `.env` on disk, `venv/` inside `backend/` — init git with a `.gitignore` before secrets get committed | repo root |
| 11 | medium | CORS origins hardcoded; with cookie auth, `allow_credentials` requires exact env-driven origins | `app/main.py` |
| 12 | low | Pydantic v1 `class Config` instead of v2 `model_config = ConfigDict(...)` | `app/schemas/user.py` |
| 13 | low | `passlib` is effectively unmaintained and breaks on `bcrypt>=4.1` (pinned to 4.0.1 today). Consider `pwdlib[argon2]`. Note bcrypt's 72-byte truncation. | `app/core/security.py` |
| 14 | low | No `updated_at`, no optimistic locking — concurrent staff edits will silently clobber | all models |

Design conflicts in the brief itself, resolved above: §7 says `Patient 1—N AIConversation` while
§12 says `user_id` (§12 wins); `User 1—1 Patient` cannot represent a walk-in; `rescheduled` is
listed as a status but behaves as a transition.

---

## 26. Build order

| Phase | Contents | Gate |
|---|---|---|
| **0 — Foundation** | git + `.gitignore`, rotate `SECRET_KEY`, remove `role` from register, fix `requirements.txt`, settle UUID + `timestamptz` + naming convention, regenerate a real baseline migration, collapse onto `/api/v1`, env-driven settings/CORS, exception handlers, structured logging | nothing else starts until this lands |
| **1 — Identity & access** | `User` (rewritten), `Role`, `Permission`, joins, `RefreshToken`, permission seed migration, `require_permission`, admin user management, `AuditLog`, auth + authz test suites | authz matrix green |
| **2 — Directory** | `Department`, `Specialty`, `Doctor`, `StaffProfile`, `Patient`, public endpoints, search, pagination | patient registration works by self *and* by reception |
| **3 — Scheduling** | `ScheduleTemplate`, `ScheduleException`, availability service, `Appointment`, `AppointmentStatusHistory`, state machine, `EXCLUDE` constraints, idempotency | concurrency test passes |
| **4 — Operations** | `QueueEntry` + WebSocket board, check-in, `Notification` + deliveries + preferences, Celery + Beat reminders, Redis cache and rate limits | reminders fire exactly once |
| **5 — Clinical** | `Encounter`, `ClinicalNote` with versioning and signing, attachments | notes are provably append-only |
| **6 — AI** | `AIConversation`, `AIMessage`, `AIToolCall`, role-scoped tool layer, SSE streaming, safety filters, usage caps | AI cannot reach data the caller cannot |
| **7 — Production** | Docker, Compose, Nginx, Gunicorn, CI/CD, observability, backups | |

### Explicitly not now

Billing, invoicing, payments · prescriptions and e-prescribing · lab orders and results ·
HL7/FHIR interoperability · insurance and claims · telemedicine video · multi-clinic tenancy ·
mobile push · patient↔clinician freeform messaging (carries real regulatory weight) ·
document OCR · analytics/ML beyond the assistant · i18n beyond a `locale` column ·
Row-Level Security · table partitioning.

Each is deliberately deferred, not forgotten. The schema above leaves room for every one of them.

---

## 27. Decision log — implementation stages (2026-09-29)

Decisions taken while executing the staged implementation plan. They refine, and where noted
override, the sections above.

| # | Decision | Choice | Notes |
|---|---|---|---|
| D19 | Doctor profile fields | Name stays on `User`; `Doctor` gets professional fields (license number, title, phone, room, status) | Phone/license are admin/authenticated only — never in the public directory (§7) |
| D20 | Origin topology | **Same-origin** in every environment: Vite dev proxy (`/api` → FastAPI) in development, Nginx in production | Frontend calls a relative `/api/v1`. CORS stays configurable for any extra origins |
| D21 | Refresh cookie | `HttpOnly`, `SameSite=Strict`, `Path=/api/v1/auth`, `Secure` outside development | Refines D8. Access token held in memory; one refresh on page load restores the session |
| D22 | CSRF | Double-submit token (readable CSRF cookie echoed in `X-CSRF-Token`) on cookie-authenticated endpoints only — `/auth/refresh`, `/auth/logout` | All other endpoints use the bearer header, which browsers never attach automatically |
| D23 | Registration enumeration | **Deferred.** Duplicate email returns 409 for now; login already gives one error for unknown email and wrong password | Uniform register responses need email verification (Notifications phase) to stay usable; rate-limit register in the Redis phase. Temporarily overrides the uniform-response line in §4 |
| D24 | Constraint names | `Base.metadata` naming convention; migration `828cba23d723` renames legacy PostgreSQL default names | Fresh and existing databases produce identical schemas |
| D25 | Stage 2 — UUID keys | UUIDv7: `uuid.uuid7()` in Python (id known before flush) + `uuidv7()` server default (PostgreSQL 18). Existing integer rows converted in place by `d7309d4412bb` | |
| D26 | Stage 2 — role grants | `user_roles(user_id, role_id, granted_by_user_id, granted_at)`; **no `expires_at`** yet (no time-boxed grants are needed) | Add when temporary access (locums, break-the-glass) is built |
| D27 | Stage 2 — refresh reuse grace | A rotated token presented again within `REFRESH_REUSE_GRACE_SECONDS` (10 s) returns an access token and no new cookie, instead of revoking the family | Two tabs refreshing at once are a race, not theft. Replay after the window revokes the family |
| D28 | Stage 2 — permissions per request | Access token carries role codes for UI only; permissions are loaded from the database on every request | A role change or deactivation takes effect on the next request |
| D29 | Stages 4–5 — public vs staff routes | Anonymous directory under `/api/v1/public/{departments,doctors}` (active rows only, public schema); management under `/api/v1/{departments,doctors}` behind permissions, full schema | Implements §7. Public schema never carries phone, license, email, ids of the login |
| D30 | Stages 4–5 — retirement | `is_active` on Department and Doctor (§20); no DELETE endpoints. A department with active doctors cannot be deactivated | |
| D31 | Stage 5 — doctor onboarding | `POST /doctors` takes exactly one of `user_id` (existing user holding the doctor role) or `account` (creates the login and grants the role in one transaction) | Removes the "type a raw user id" workflow |
| D32 | Pagination | Offset `page`/`page_size` (max 100) everywhere, including appointments | Overrides §17's keyset suggestion for now: every appointment list is filtered by date range/doctor/patient, so offsets stay small. Revisit if a list grows unbounded |
| D33 | Stage 6 — patient identity | `patients.user_id` UNIQUE NULLABLE (D2); MRN `MRN########` from a PostgreSQL sequence; self-registration creates User + role + Patient in one transaction | Existing patient logins without a profile complete it via `POST /patients/me`; no legal names or birth dates are invented by migration |
| D34 | Stage 6 — patient self-service | Patients edit contact fields only; legal name and date of birth are corrected by staff (§6) | |
| D35 | Stage 6 — record-level access | `services/access.py` builds one SQL visibility condition per caller, used by both list and single reads, so they cannot disagree; a hidden record is a 404 | Doctors' `patient:read_assigned` is enforced once appointments exist |
| D36 | Stage 7 — schedules | `schedule_templates` (weekday + local `TIME` + slot length + validity dates) and `schedule_exceptions` (leave/holiday/block/extra over `timestamptz` start/end). Availability computed per request (D9), max 31 days | Exceptions use `starts_at`/`ends_at` columns rather than a `tstzrange` column: simpler ORM mapping, same queries. `availability:read` is separate from `schedule:read` so patients never see leave reasons |
| D37 | Stage 7 — leave vs bookings | A leave/holiday/block over booked appointments is refused (409); those must be moved first. Deactivating a template keeps already-booked appointments | |
| D38 | Stage 8 — appointments | Implements §8 as designed: `requested → scheduled` automatic on a verified-free slot; `rescheduled` is a transition (D12); EXCLUDE constraints on doctor and patient (D10); append-only status history; `Idempotency-Key` on booking | |
| D39 | Stage 8 — booking concurrency | Bookings take `pg_advisory_xact_lock` on doctor then patient before checking availability | Found by the concurrency test: two simultaneous inserts deadlock on the EXCLUDE check (500). With the lock the loser gets a clean 409; deadlock/serialization errors are also mapped to 409 as a safety net |
| D40 | Stage 8 — transition rules | One table maps (from, to) → grants of (permission, scope: any/own/assigned, optional guard). Patients: confirm, cancel/reschedule before a cutoff. Reception: check-in (same local day), no-show (after grace), cancel, reschedule. Doctors: start/complete, cancel, no-show — own appointments only. Admin has reception's powers, not the doctor's | Responses include `allowed_transitions` / `can_reschedule` for the UI; the API re-checks on submit |
| D41 | Stage 8 — staff notes | `staff_notes` visible to staff and the treating doctor, never to the patient (separate response schema) | Clinical documentation still belongs in future clinical tables, not here |
| D42 | Dashboard — data | `GET /api/v1/dashboard/summary` returns sections (`patient`, `doctor`, `front_desk`, `overview`) by *permission*, each one aggregate query scoped by the same visibility conditions as the appointment list. Lists on the dashboard reuse `/appointments` | No new tables. "Today" = the doctor's department date (doctor section) or the clinic timezone (front desk) |
| D43 | Dashboard — appointment location | Appointment responses include the doctor's `room_number`; the public doctor directory still does not | Appointment responses only reach people authorised for that appointment |
| D44 | Frontend shell | Left sidebar + top bar (search, current user), role-aware menu with `lucide-react` icons; one stylesheet of tokens and classes for every page. Light theme only, per the design | No notification bell until Notifications exists; initials avatars until file uploads exist |
| D45 | Frontend data loading | `useFetch(fetcher, deps, {enabled})` gives every section the same loading / error / empty handling; "loading" is derived, not stored | Session restore is skipped when no CSRF cookie is present (no 401 for anonymous visitors) |
| D46 | Frontend tests | Vitest + Testing Library (jsdom); services and `useAuth` mocked at the module boundary | |
| D47 | `*_own` permissions | Held only by the patient and doctor roles; migration `88584f93ce0c` removes `doctor:update_own` from admin | The "My Profile" link for doctors also requires an actual doctor profile |
| D48 | Sign-in pages | `/login` and `/forgot-password` use a full-screen `AuthLayout` (brand panel + card) outside the app shell; the panel is hidden below 900px. After sign-in everyone goes to the page that asked for the login (in-app paths only) or `/dashboard`, which is already role-aware | No per-role landing routes; no open redirect |
| D49 | "Remember me" | `remember_me` on login sets `refresh_tokens.persistent`. Off: browser-session cookies and a `SESSION_TOKEN_EXPIRE_HOURS` (12h) server lifetime. On: cookies and token last `REFRESH_TOKEN_EXPIRE_DAYS`. Rotation inherits the flag. API default is off | The password is never stored anywhere on the client; only this flag is sent |
| D50 | Not yet supported on the sign-in page | Password reset (needs email delivery) → an honest information page, no form. Google/Microsoft sign-in (no OAuth backend) → visible but disabled | Refines D23. Neither imitates success |
| D51 | Create-account page | `/register` uses `AuthLayout` (`variant="register"`), sharing the card, fields, password input and provider block with `/login`. One "Full name" input is split (last word = family name) into the backend's `first_name`/`last_name`; **Date of birth is asked too**, because `patients.date_of_birth` is required | The patient model was not weakened to match the mock-up. Two-word names are required, as for staff-registered patients |
| D52 | Registration lifecycle | Unchanged: `POST /auth/register` creates User + patient role + Patient (MRN from the sequence) in one transaction and issues no session; the frontend then logs in (browser-session cookie). If that sign-in step fails, the user is sent to `/login` with "account created" | |
| D53 | Login emails | `schemas.common.LoginEmail` lowercases every email that identifies a login (register, login, staff/doctor/patient account creation); migration `1a6e1ee8ec97` lowercases existing rows | Fixes duplicate accounts differing only by letter case |
| D54 | Consent | The checkbox is required and never pre-ticked, but acceptance is **not recorded** in the database, and `/terms` and `/privacy` only state that the clinic has not published the documents | Before real patients register: supply the legal text and store acceptance (timestamp + document version) |
| D55 | Doctors directory: layout | `/doctors`, `/doctors/:id` and `/departments` render in `DirectoryLayout`: visitors get `PublicLayout` (top navigation, Sign in / Create account), signed-in users keep the `AppLayout` sidebar shell | One page for both audiences; the sidebar is never shown to someone with no session |
| D56 | Doctors directory: state and queries | The URL query string is the only state (`q`, `department`, `specialization`, `min_experience`, `fee`, `sort`, `page`, `view`). `GET /public/doctors` does all searching (`q` over name, specialization, department), filtering, sorting (`sort=name_asc…fee_desc`) and paging; `Page` now also returns `total_pages`. `GET /public/doctors/specializations` feeds the filter. Filters apply on "Apply filters"/Enter, not per keystroke | Refresh, back button and shared links reproduce the result; React never filters or sorts doctors |
| D57 | Availability badge | `availability.status` on every public doctor: `available` = at least one slot a patient could book in the next `AVAILABILITY_STATUS_DAYS` (7); `busy` = has working hours in that window but every slot is taken; `unavailable` = no working hours (no schedule or on leave). `next_available` is the first free slot. Computed for a whole page in 4 queries by `availability_service.availability_status`, from the same functions that build the slot list | Refines §7 ("never availability detail"): the public sees a summary and the first free time, **not** the slot list, which still needs `availability:read` (any signed-in user). Book is disabled only for `unavailable` |
| D58 | "Verified" mark | `is_verified` is true when a `license_number` is on file; the number itself is never published | There is no separate verification workflow yet; an admin entering the licence is the verification |
| D59 | Doctor profile fields | Added `doctors.qualifications` (migration `f04272fcbf11`). No photo upload, "services" or "clinic/hospital" fields: avatars are initials, the hero is a local illustration (`assets/doctor-hero.svg`), the clinic is the single tenant | File uploads are a later stage; nothing on the page is a stock photo of a real person |
| D60 | Demo data | `python -m scripts.seed_demo` (from `backend/`) adds fictional departments, doctors (`@clinic-demo.example`), schedules, one doctor on leave and one fully booked. Idempotent; refuses when `ENVIRONMENT=production`; password from `SEED_PASSWORD` or random, printed once | Development and demos only, never part of migrations |
| D61 | Public booking calendar | `GET /public/doctors/{id}/availability?date_from&date_to` (≤ 31 days, no login) returns the doctor's **free** slots grouped by the clinic's local date, plus `bookable_until`. Same `available_slots` computation as the signed-in endpoint, with the patient booking notice; 404 unless the doctor is publicly listed. It exposes nothing about existing appointments beyond a slot being absent | **Supersedes** §7 "never availability detail" and D57's "slot list needs `availability:read`": the profile prompt requires visitors to pick a date and time before signing in. Seeing a slot reserves nothing |
| D62 | Booking from the profile | Profile → date → time → `/appointments/book?doctor&slot` → (sign-in if needed, returning to the same URL) → **confirmation step** for patients → `POST /appointments`. The confirmation step re-reads availability first; the booking itself re-checks the slot under the advisory locks and EXCLUDE constraints (unchanged), so a stale slot gets 409 and a clear "just booked by someone else" message. Staff still use the full form | No slot holds, no new infrastructure |
| D63 | Career history | `doctor_experiences` (title, organization, location, start/end year, description; end NULL = Present) and `doctor_education` (qualification, institution, field of study, years), migration `8cba3b163f58`; only on the profile response, not the directory list. **No editing UI or API yet** (out of scope for the profile stage); data comes from the demo seed | Next: let admins (and doctors, for their own profile) edit these |
| D64 | Bookable means a visible login too | `availability_service.bookable_doctor` now also requires the doctor's **user** to be active, matching the public directory's rule | Closes a gap where a disabled doctor login could still be booked |
| D65 | Not built (no backing data) | Doctor photos (initials avatar instead), "Accepting new patients" (no such field) | Shown only when the domain supports them |
| D66 | One "upcoming" rule | `models.appointment.upcoming_condition(now)` (open status and not yet ended) is used by the dashboard counts **and** the new `GET /appointments?upcoming=true` filter, so the patient dashboard's list and its "Upcoming" card always agree. The summary endpoint stays counts-only | Visibility still comes from `access.appointment_visibility`; a patient's `patient_id` filter cannot widen it |
| D67 | Default avatars | The shared `Avatar` shows an uploaded picture (`src`) when given, falling back on load error; otherwise an **illustrated, faceless doctor** (cool-toned, no implied gender/ethnicity) for doctors and initials for everyone else. No stock or realistic faces anywhere | No upload/media storage exists yet; the component is ready for a future `photo_url` |
| D68 | Patient dashboard layout | Summary cards → Upcoming appointments (with View details) + My Profile → Quick Actions + Need Help. No notification bell (no notifications), no row "⋯" menu (reschedule/cancel live on the appointment page), no fake support form | Header search goes to the doctor directory (name, specialty, department) and says so |
| D69 | Help & Support | `/help` (signed-in) explains the features that exist and shows clinic contact details only when `VITE_SUPPORT_PHONE` / `VITE_SUPPORT_EMAIL` are configured; otherwise it says to speak to reception | No ticketing system |
| D70 | Patient sidebar | Patients no longer get a "Book appointment" sidebar item (booking starts from a doctor or the dashboard's quick action); staff with `appointment:create` keep it | Matches the patient navigation in the dashboard reference |
| D71 | Appointment list scopes | `GET /appointments` takes `scope=upcoming|past|all` (replacing D66's `upcoming=true`) and `q` (doctor name, specialization, department). Upcoming = D66's rule; **past = everything else**, so a future appointment that was cancelled is in Past, not Upcoming. `date_from > date_to` is a 400 `INVALID_RANGE` | One list endpoint, no per-tab endpoints |
| D72 | Tab counts | `GET /appointments/counts` returns `{upcoming, past, all}` in one `COUNT … FILTER` query under the same visibility and filters as the list (scope ignored) | Counts never come from the loaded page |
| D73 | Patient appointments page | `/appointments` renders `PatientAppointments` for patient-only logins (URL holds tab, search, status, dates, page); doctors and staff keep the table. Row actions come from the API's `allowed_transitions` / `can_reschedule`: confirm attendance, reschedule (opens the picker on the detail page), cancel (confirmation dialog, reason `patient_request`). No action, no "⋯" menu | Reason is shown as the visit purpose; room as the location; no invented clinic names |
| D74 | Appointment detail contract | `GET /appointments/{id}` returns `AppointmentDetailRead` / `AppointmentStaffDetailRead`: the list shape plus `patient_profile` (sex at birth, gender identity, phone, email, address). The profile passes the **patient** visibility rule (`access.patient_visibility`), not the appointment's, so a role that can read appointments but not patients gets `patient_profile: null`. Lists and mutation responses keep the lighter shape. `AppointmentDoctor` gains `years_of_experience` and `is_verified` (D58's rule; the licence number is never sent) | Contact details only on the single-record read, never in lists |
| D75 | Appointment detail page | Summary card → Details / Notes / History tabs + Quick Actions + Doctor card. Actions come only from `allowed_transitions` / `can_reschedule`; unavailable ones stay visible, disabled, with the reason. Notes = the patient's reason, the cancellation note and (staff/doctor only) staff notes; no clinical notes exist yet. History = the recorded status changes, actor shown only as "you" or "automatically". "Appointment type" and clinic name/address are **not shown**: the domain has no such fields | Location is the doctor's room + department (D43) |
| D76 | Add to calendar / contact | "Add to Calendar" builds an RFC 5545 `.ics` in the browser for open, not-yet-ended appointments: UTC times, doctor, room/department — never the reason for the visit. "Contact Clinic" uses `VITE_SUPPORT_PHONE` / `VITE_SUPPORT_EMAIL` (D69), else links to Help & Support | No new endpoints or storage |
| D77 | Doctor self-registration | `/register` has an **Account Type** dropdown (Patient / Doctor). Doctor sign-up (`account_type: "doctor"`) creates the login with the new `doctor_applicant` role (permission `doctor_application:manage_own` only) and a `doctor_applications` row in `pending_review`; **no Doctor profile, no doctor role**, so the applicant is not listed, not bookable and has no clinical access. Every professional field and every credential document is optional at registration. Credentials (registration certificate, degree, supporting document) go to private R2 under `doctor-credentials/{application_id}/` (category `doctor_credential`), validated from their bytes; only `doctor_application:review` (admins) gets 5-minute links. The applicant edits details and adds/removes documents at `/doctor/application` while pending. Approval (`POST /doctor-applications/{id}/approve`) creates the Doctor from the application and swaps the role in one transaction; it requires specialization + department plus `DOCTOR_APPROVAL_REQUIREMENTS` (settings), and checks the licence is not held by another doctor. Rejection needs a reason the applicant can read. Nobody reviews their own application | Registration validation and approval policy are separate, so requirements can be tightened without blocking sign-up. Licence numbers are not unique on applications (nobody can block a real doctor by registering their number first). No admin review screen yet: the API exists |
| D78 | My Schedule | `/schedule` shows the regular week (7 rows: on/off, one or more time ranges, Edit, one **Save Changes**) and date exceptions (Unavailable / Custom Hours, add, edit, delete). API: `GET/PUT /doctors/{id}/weekly-schedule` (the whole week at once; only changed weekdays get new templates valid from today, old ones end yesterday so history is kept) and `GET/POST/PUT/DELETE /doctors/{id}/date-exceptions` (one exception per local date; Unavailable = a whole-day `leave`, Custom Hours = new kind `custom_hours`, migration `a7d3e5f19b42`). Precedence, in `availability_service.working_slots` used by booking, the public calendar and the directory badge: a date's custom hours **replace** its weekly hours; extra availability adds; leave/holiday/block remove. A change that would leave an upcoming active appointment outside the doctor's hours is refused with 409 `SCHEDULE_CONFLICT` (the doctor's dates only, no patient data), never applied by moving or cancelling appointments. Schedule changes take the same per-doctor advisory lock as bookings | Times are local wall-clock in the department timezone; no overnight shifts. `schedule:manage_own` for one's own doctor id, `manage_any` for staff. Multi-day or partial-day exceptions made with the older interval API are listed but can only be deleted here |
| D79 | Doctor My Appointments | `/appointments` for a doctor-only login renders `DoctorAppointments` (staff keep the table, patients D73). Views: a **day** (Today by default, `?date=` from the dashboard, arrows and a date picker), **Upcoming** (from tomorrow) and **Past** (before today, newest first) by *date*; badges always show the stored status. `GET /appointments/day-counts?day=` returns `{timezone, today, day, on_day, upcoming, past}` in one aggregate query; status and search filters apply to the counts too. List/count dates now use the doctor's department timezone (`filter_timezone`), not the clinic default. `q` additionally matches patient name, MRN and reason for callers with `appointment:read_any`/`read_assigned`, always inside their visible appointments; the search text is never put in the URL. Patient photos come with the list (`patient.photo_url`). Row menus show only `allowed_transitions` / `can_reschedule`; cancel, no-show and complete ask first | Doctors cannot confirm or reschedule (patient/front-desk permissions in the state machine); there is no appointment-type field, so the second line only says when an appointment was rescheduled |
| D80 | Reception Patients page | `/patients`: search (name, MRN, phone, email), status, **doctor** and **registration date** filters, 10 per page with a numbered pager, row checkboxes (current page only; no bulk action exists, and the page says so), row menu from permissions (view, edit = detail page `?edit=1`, book = `/appointments/book?patient=`, (de)activate only with `patient:deactivate`). `GET /patients` gains `doctor_id` (an EXISTS over appointments: the only doctor-patient relationship; never duplicates a patient), `registered_from` / `registered_to` (inclusive clinic-local dates on `created_at`; reversed range = 400 `INVALID_RANGE`) and `sort` (name / registered newest / oldest, id as tie-breaker). Add Patient creates a record **without a login** (no invented password); the MRN comes from the database sequence. Search text stays out of the URL | Reception keeps its seeded permissions: it cannot change a patient's status (admins can). Filters only narrow `patient_visibility`, so a doctor's doctor filter never widens their view |
| D81 | Patient detail page | `/patients/:id`: breadcrumb, identity header (photo or initials, status, MRN, age from date of birth, sex, registration date), Edit (dialog; also opened by `?edit=1` from the list) and Book Appointment (`/appointments/book?patient=`), section tabs (Personal / Contact / Appointments scroll to their cards), Personal and Contact cards, and an Appointments card with Upcoming / Recent (status-based scopes of the existing list API, filtered by `patient_id`, 5 each, real counts, state-machine actions) and View All (`/appointments?patient=`). Migration `b8e4c2a9d715` adds nullable `emergency_contact_name`, `emergency_contact_relationship`, `emergency_contact_phone` and `preferred_contact_method` (phone/sms/email, CHECK constraint) to `patients`; phone fields accept digits and the usual separators. **Medical Information** is the existing clinical documents, shown only with `document:read_assigned` (the treating doctor); for everyone else the tab is locked and nothing clinical is requested | No blood type: it is clinical data and has no clinical-records module to live in. Reception still cannot change patient status (admin permission) |
| D82 | Staff booking on behalf of a patient | `/appointments/book` for `appointment:create` now runs the **same three-step wizard** as patients (the one-page staff form is gone): an on-behalf panel, the selected patient card (`?patient=<uuid>`, loaded through the patient API; inactive or invisible patients cannot be booked) with Change Patient (server-side search of active patients; replacing a patient clears the draft, after a warning), then Select Doctor → Date & Time → Confirm, which sends `patient_id`. Continue from step 1 needs a patient. Doctor cards show today's working hours or the next free date: the directory's availability gains `today_hours` (merged working ranges for today after exceptions, before bookings), computed in the existing batch query. Booking for a patient now also requires that patient to be within the caller's `patient_visibility` (404 otherwise): `appointment:create` alone no longer reaches any patient by id | `booked_by_user_id` records the staff member; the appointment belongs to the patient. Badge wording keeps the directory's labels (Available today / Available this week / Fully booked …) |
| D83 | Doctor Schedules (staff view) | `/doctor-schedules` (`schedule:read`; sidebar "Doctors / Schedules" for `appointment:create`, replacing "Doctors" and, for front desk without a schedule of its own, "Schedule", which stays reachable from the page): doctor / department / specialization filters over the public directory (only bookable doctors), date picker with Previous / Today / Next, summary card, Sunday–Saturday week strip, working hours, slot grid and a hand-off to the booking wizard (`?doctor&slot[&patient]`; without a patient the wizard opens the patient picker first). `GET /doctors/{id}/day-schedule?day=` (default: today in the doctor's timezone; −366 … +horizon+7 days) returns hours, breaks, slot length, totals, every slot's status (`available`, `booked`, `blocked` by leave/block, `break`, `past` incl. booking notice, `beyond_horizon`) and the week's day status (`available`, `fully_booked`, `off`, `unavailable`, `past`), computed by `availability_service.day_schedule` from the same rules as booking. **Breaks are the gaps between a day's working blocks** (no separate break model). Booked slots carry no appointment or patient data | The calendar is always computed (no weekday/date taken from a picture). The page never books: the wizard's Confirm does, with the usual locks |
| D84 | Staff Appointments page | `/appointments` for `appointment:read_any` renders `ReceptionAppointments` (patients D73, doctors D79 unchanged; the plain staff table is gone): search (patient name/MRN, doctor, reason), date / doctor (incl. inactive, for history) / department / status filters, tabs **All** (no scope), **Today** (today's local date from the API; it ignores the date filter, and picking a date moves to All), **Upcoming** and **Past** (the lifecycle scopes of D71), 10 per page, sortable Time / Patient / Doctor / Department / Status, and per-row menus from `allowed_transitions` / `can_reschedule` plus View Appointment / Patient / Doctor. API: `GET /appointments?sort=` (`time|patient|doctor|department|status` + `_asc|_desc`, validated enum; status sorts in lifecycle order; time and id break ties) and `GET /appointments/counts?include_today=true` adds `today` and `today_date` (omitted otherwise, so other callers see the old shape); list rows gain `patient.sex_at_birth` | Completing visits stays with the doctor (`appointment:consult`); reception may accept requests, confirm, check in, cancel, mark no-show (after the grace period) and reschedule, as the state machine already allowed |
| D85 | Admin dashboard | `/dashboard` for callers with `user:read` + `patient:read_any` + `appointment:read_any` renders `AdminDashboard` (other roles unchanged). `GET /dashboard/admin?day=` (same three permissions; default today in the clinic timezone) returns five KPIs — users, doctors, patients, appointments, departments — each the **cumulative count of records created up to the end of `day`** (any current status: a deactivated department or a cancelled appointment still existed), compared with the same count at the end of the previous month: `change_percent` rounded to 0.1, `trend` up/down/flat, or `new` (null percent) when the previous count was 0. Users count each account once whatever its roles; doctors are Doctor profiles, so applicants (D77) are users but not doctors; patients include walk-ins without a login. Also the five newest accounts up to `day` (name, email, roles, active, joined). The page adds that day's appointments (the list API, 5 rows) and four shortcuts to the existing admin pages | One COUNT query per table, no stored counters. No global search, notifications or Settings page exist: the header is unchanged and nothing is invented. The admin sidebar keeps its permission-driven items |
| D86 | Admin route, workspace header, notifications, settings | **`/admin` is the admin dashboard route** (`ProtectedRoute allOf=[user:read, patient:read_any, appointment:read_any]`; visitors → `/login` and back, other roles → `/dashboard`); `/dashboard` sends administrators on to `/admin`. Administrators get their own sidebar (Dashboard, Users, Departments, Doctors, Patients, Appointments, Profile; Settings + Logout at the bottom). The signed-in header has **global search** (`GET /search?q=`, ≥2 chars, up to 5 patients / doctors / appointments / users, each section only with its list permission and through the same service + visibility rules; names, MRNs, dates, statuses only), a **notification bell** (`/notifications`, `/notifications/unread-count`, `/notifications/{id}/read`, `/notifications/read-all`; always the caller's own, others' are 404; polled every 60 s and on opening) and an **account menu** (View Profile → role profile or `/account`, Settings, Logout). Notifications are rows (`notifications`, migration `c5f1a8e2d364`) created in the same transaction as their event: new doctor application → holders of `doctor_application:review`; booking → the doctor; cancellation → doctor and patient except whoever cancelled. Messages carry dates and times, never patient names or reasons; links are internal paths only (CHECK). **Settings** (`/admin/settings`, `GET /settings/clinic` for any signed-in user, `PUT` with new `settings:manage`): clinic name, phone, email, address in `clinic_settings` (one row); timezone, slot length and booking rules stay server configuration and are shown read-only | No e-mail, push, WebSockets or Redis. The doctor-application notification has no link yet: there is no review page |
| D87 | Administrator provisioning: bootstrap, invitations, audit log | The admin role is granted only two ways. (1) **First administrator**: `python -m app.cli.create_admin` (interactive; password via getpass, typed CREATE confirmation). It creates a *new* account and refuses if any account holds the admin role or the email exists; an advisory lock (namespace 3) serializes concurrent runs. No HTTP equivalent. (2) **Invitation**: holders of new `admin_invitation:manage` invite from Users (re-entering their password); `admin_invitations` stores only the SHA-256 of a 256-bit token, expiring (`ADMIN_INVITE_EXPIRE_HOURS`, 24) and single-use; resend rotates the token. The link is `FRONTEND_BASE_URL/accept-admin-invite#token=…` (fragment: never in server logs or Referer; the page strips it from history). Public `POST /auth/admin-invitations/{preview,accept,accept-existing}` take the token in the body, are rate limited per IP (in-process fixed window, `INVITE_ATTEMPTS_PER_MINUTE`), lock the invitation row (no double acceptance) and re-check that the inviter is still active with the permission. A new email gets a new account; an existing account must be signed in as that email and re-enter its password; its password is never replaced. `POST /users` and `PUT /users/{id}/roles` refuse to *add* admin (`ADMIN_REQUIRES_INVITATION`); removing it (also `POST /admin/administrators/{id}/revoke-role` with password) and deactivating keep self/last-admin rules, now under the same lock. **Email**: `email_service` with `EMAIL_BACKEND` smtp / outbox (development only, `backend/var/outbox/*.eml`) / none; `delivery_status` records what the provider said and the UI never says sent otherwise. **Audit**: `audit_logs` rows written in the action's transaction (bootstrap, invitation created/resent/revoked/accepted, admin role granted/revoked, roles changed, user (de)activated); secrets never stored | Rate limit is per process (needs a shared store behind several workers). No audit-log viewer yet |
| D88 | Admin > Users management | `GET /users` gains `q` over name, email **and the phone on the linked doctor/patient profile**, `joined_from/_to` (inclusive clinic-local dates), and `sort` = name/email/role/status/created_at with `-` for descending, always tie-broken by `id` for stable paging. **Role sort**: a user sorts by their most privileged role (admin < doctor < receptionist < patient < doctor_applicant < other; no role last), then by name. Role filter matches any held role (many-to-many), rows list every role. Rows (`AdminUserRead`) add phone, signed photo URL, doctor_id, patient_id from the profile; users themselves have no phone or photo. `PATCH /users/{id}` accepts only name/email (`extra=forbid`). New `POST /users/bulk-status` (≤100 ids, `user:deactivate`) runs `set_active` per user in its own transaction, so self/last-admin rules, session revocation and audit apply to each; the result lists each outcome. Add User routes by type to the existing workflows: receptionist via `POST /users` (admin-chosen temporary password), patient via the walk-in registration dialog (MRN), doctor to Admin > Doctors, administrator to the D87 invitation. Manage Roles never offers Administrator; removing it uses the password-confirmed revoke | No admin password reset for other users (needs email reset links); phone/photo are edited on the profile, not the account |
| D89 | Admin > Departments management | `GET /departments` (department:manage) returns `DepartmentListItem`: `doctor_count` = practising doctors (active profile **and** active login; profiles exist only after approval, so applicants never count) and `doctors_preview` = the first three of those same doctors by name, via one aggregate subquery and one `row_number()` query per page (no N+1). `q` searches name and description; `is_active` filters; `sort` = name/timezone/doctors/status with `-` for descending, tie-broken by id. `GET /departments/{id}` adds every doctor (practising or not) and `upcoming_appointments`. New nullable `icon` and `color` columns (migration `e4a9c2f7b310`) hold keys from a fixed list; NULL = the UI guesses from the name. Create/update refuse unknown fields; update cannot change status. Timezone stays an IANA name (default `CLINIC_TIMEZONE`), validated by ZoneInfo; the UI shows `(GMT±hh:mm) City` for the offset in force now, so DST shows correctly. **Deactivation no longer requires moving doctors out** (`DEPARTMENT_HAS_ACTIVE_DOCTORS` removed): doctors stay assigned, existing appointments are untouched and can still be attended, while the public directory hides the department, no slots are offered and booking/rescheduling refuse via `bookable_doctor`; doctors cannot be moved into an inactive department. A doctor has exactly one department, so Manage Doctors moves doctors in or out through `PATCH /doctors/{id}` | Department icons are display metadata only |
| D90 | Admin > Doctors management | Lists **approved doctor profiles** only (a `doctors` row exists only after approval or admin creation); self-registered applicants stay `doctor_applications` and are reviewed in the Doctor Applications panel on the same page through the existing D77 API (detail, short-lived document links, approve with notes, reject with a required reason). Staff `q` now also matches email and the doctor's phone (never in the public directory). New sorts department/specialization (case-insensitive)/status (active first), each tie-broken by name then id. `GET /doctors/specializations` (doctor:read) lists every specialization, inactive doctors included; the department filter includes inactive departments while assignment offers only active ones. `GET /doctors/{id}` adds `upcoming_appointments`; deactivation still refuses while any exist (`HAS_UPCOMING_APPOINTMENTS`, nothing is cancelled automatically). `PATCH /doctors/{id}` refuses unknown fields. Audit entries: doctor created / activated / deactivated / department changed, application approved / rejected. Manage Schedule opens `/schedule?doctor=` (schedule:manage_any) | Admin-created doctors have no credential documents: documents belong to applications |
| D91 | Admin > Patients | Same `/patients` page and API as reception (D80), no second module. `GET /patients` adds `sex_at_birth` (female/male/intersex/unknown; the filter offers "Not recorded" so unrecorded patients stay findable) and sorts `-name`, `mrn`, `email`, `phone`, `status` (active first) with `-` for descending; walk-ins without email/phone sort last; id breaks ties. New `POST /patients/bulk-status` (≤100 ids, patient:deactivate) runs `set_active` per patient in its own transaction, so the upcoming-appointment refusal and audit apply to each; outcomes are reported per patient. Activation and deactivation are audited. MRNs remain `MRN` + 8 digits from the `patient_mrn_seq` sequence (unique, never reused, safe under concurrent registration; covered by a concurrency test). Walk-ins stay account-less (`user_id` NULL); a login can be added later from the patient record. The row menu adds View Appointments (`/appointments?patient=`) | Selection and bulk actions apply to the current page only |
| D92 | Admin > Appointments; appointment department history | Administrators use the same staff page and API as reception (D84), no second appointment system: search (patient name, doctor name, MRN), an inclusive **date range** (`from`/`to`; `?date=` still means one day), doctor / department (inactive included for administrators) / status filters, Clear Filters (also resets the sort), server-side sorting and paging, state-machine actions, reschedule and cancel. The first column shows date then time. **New `appointments.department_id`** (migration `f1b6d3a8c925`): the doctor's department at booking, written inside the INSERT by the booking service for new and rescheduled appointments; existing rows are backfilled from the doctor's department at migration time. Reads, the department filter and department sorting use `coalesce(appointments.department_id, doctors.department_id)`, so moving a doctor no longer moves their past appointments | Rows written outside the booking service (tests, scripts) fall back to the doctor's current department |
| D93 | Admin > Departments as cards | The D89 table becomes a card grid (4 / 2 / 1 columns by width), 12 per page, ordered by name: icon (saved choice or a guess from the name; rounded square), name, status badge with text, actions menu, description ("No description provided." when empty), up to three practising doctors' avatars + "+N" + count, and View Doctors (`/admin/doctors?department=`). Above it, four clinic-wide totals from new `GET /departments/summary` (department:manage): total, active, inactive departments and practising doctors (same rule as each card's count); they ignore the page's search and status filter and refresh after any change; a failed request shows a dash, never a number. All D89 actions and dialogs are unchanged; no delete action (departments are retired, never deleted) | Column sorting from D89 stays in the API but the cards are always by name |
| D94 | Patient / visitor Departments page | The existing public `/departments` page (DirectoryLayout: visitors get the public header, signed-in users their own shell and sidebar) becomes the card grid. Cards are one shared `DepartmentCard` used by both pages; the admin passes status, menu and details, the public card has none. `GET /public/departments` now returns `DepartmentPublicCard`: id, name, description, icon, color, `doctor_count` and up to three `doctors_preview` (id, name, title, signed photo URL only) for **active departments only**, from the same query as the admin list (`manage_list(is_active=True)`, two queries per page, no N+1); search covers name and description. A doctor counts when their profile and login are active, the same rule as the directory, so applicants and inactive doctors never appear. View Doctors goes to `/doctors?department=` | Other callers of the public list (pickers) receive the extra fields and ignore them |
| D95 | Render-error containment; Admin Dashboard strip | Root cause of the blank Admin Departments page: a backend process started before D89 (no reload) returned departments without `doctor_count`/`doctors_preview`, while the database also lacked migrations `e4a9c2f7b310`/`f1b6d3a8c925`; the card read `doctors_preview.length`, threw, and with no error boundary the render failed. Fixes: `DoctorAvatarGroup` shows "Doctor count unavailable" when the doctor fields are missing (never a fake 0); a reusable `ErrorBoundary` wraps every page inside `AppLayout` (reset on route change; sidebar and header stay) and the departments grid ("Unable to load departments", Try again reloads without re-rendering the failed data); errors are logged to the console in development only. Admin Dashboard: the KPI note becomes an information strip (sum of the five totals, cutoff date, comparison month, and the time this browser fetched the figures); panels equal height at about 53/47; Recent Users names and emails truncate with the full value in a tooltip | No KPI sparklines: the API has no history series. No "Live data" label: the page does not refresh itself |
| D96 | Clinic AI Assistant (floating agent) | One `ClinicAssistant` mounted in `AppLayout` for signed-in users (survives navigation): the official avatar (`assets/clinic-ai-avatar.png`, the supplied image cropped to its circle) as a launcher, bottom-right by default, draggable with Pointer Events + capture (6 px threshold separates click from drag), edge snapping, position in localStorage clamped to the viewport; opens a drawer (440 px, full screen on phones). Backend `/api/v1/ai`: status, conversations (owner-only), messages, documents, and a decision endpoint. Providers behind one interface (`services/ai/provider.py`): Gemini REST and any OpenAI-compatible API (Groq etc.), chosen by `AI_PROVIDER`/`AI_MODEL`/`AI_API_KEY`; none configured → honest 503 `AI_NOT_CONFIGURED`. The agent loop is bounded (`AI_MAX_TOOL_STEPS`); tools wrap existing services with the user's own Principal (search_doctors incl. min experience, list_departments, get_doctor_availability, get_my_appointments, propose_booking). Booking is only *proposed*; the user's Confirm re-checks the slot and books through `appointment_service.book` (idempotency key per message). Documents: PDF/PNG/JPG/WEBP/DOCX/TXT detected from bytes, ≤ `AI_MAX_FILES_PER_MESSAGE` × `AI_MAX_FILE_BYTES`, stored in private R2 under random keys, text extracted at upload (pypdf; DOCX XML; TXT); images and scanned PDFs are sent as files to a vision model or reported unreadable. Document text is fenced as untrusted data. `AI_PHI_ALLOWED=false` (default) keeps all patient data (own appointments, documents) away from the provider. Model output is rendered by a safe Markdown subset, never as HTML. Conversations store user and assistant text only (tool traffic is not persisted) | No streaming; no OCR without a vision model; retention purge is a script to schedule |
| D97 | Claude provider, streaming, screenshot panel | `AI_PROVIDER=anthropic` uses the official `anthropic` SDK (2.3.0, API version 2026-10-21: no sampling parameters are sent) in `services/ai/anthropic_provider.py`, kept separate from the Gemini/OpenAI-compatible module; key from `ANTHROPIC_API_KEY` or `AI_API_KEY`, model from `AI_MODEL` (e.g. `claude-sonnet-5-5`). Each agent step is one streamed Messages request; thinking stays at the model default (adaptive); `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) is sent for claude-sonnet-5-5 / opus-5-5 / opus-5 / fable-5-1; tools use `eager_input_streaming` and are validated by the agent's Pydantic schemas; refusal and truncated-tool turns never run tools; the step's content blocks are sent back unchanged. `POST /ai/messages/stream` (SSE: `delta`, then `done` or `error`) runs the same agent; the stored answer is exactly the streamed text; a stopped or failed request saves nothing. The frontend reads it with fetch (Bearer token). New proposals `propose_cancellation` / `propose_reschedule` (own appointments, AI_PHI_ALLOWED) confirm through `change_status` / `reschedule`. Panel redesigned to the screenshot: rounded drawer, header controls, welcome illustration (the official avatar with halo and sparkles; no waving variant was supplied), four quick actions (Find a Doctor, Book Appointment, My Appointments, Clinic Services) each tied to a server capability and showing why when unavailable, composer with image previews and per-file retry | No separate OCR: scanned PDFs and images are read by Claude itself |
| D98 | Adaptive dashboard sections | The patient's Upcoming Appointments card fills its grid row and adapts to the count: none shows a centred invitation to find a doctor; one adds the "Need to make changes?" and "Planning another visit?" panels; two or three sit above the changes panel (three compact); more show the nearest three and "Showing the next 3 of N". Each card has a menu with only the actions the API allows (cancel asks first and reloads the counts). Capped lists on the doctor, front-desk and admin dashboards say "Showing X of N"; admin cards share the row's height. No fixed heights | Fixed-height cards |
| D99 | Patients edit their personal details | Supersedes D34's identity lock at the user's request: `PATCH /patients/me` (`PatientSelfUpdate`) also accepts first/last name, date of birth (not in the future) and sex at birth; blank names are rejected. The MRN, status and anything clinical stay staff-only. A change to any identity field writes `patient.identity_changed` to the audit log with the fields and their previous values, so the clinic can review or reverse it. My Profile: Edit on the Personal Information card (identity fields), Edit on Contact Information (contact fields), Edit Profile (both) | Keep the front-desk-only correction (D34) |
| D100 | Gemini through google-genai; usage limits; role tools | `AI_PROVIDER=gemini` uses the official `google-genai` SDK (2.34.0) in `services/ai/gemini_provider.py`: streamed generateContent, manual function calling (SDK auto-calling off), thought signatures sent back, errors mapped to AI_TIMEOUT / AI_RATE_LIMITED / AI_QUOTA_EXHAUSTED / AI_AUTH_FAILED / AI_MODEL_UNAVAILABLE; no automatic model fallback; `GEMINI_API_KEY`/`GEMINI_MODEL`; `python -m app.cli.ai_check` checks the model. `ai_usage` records every model-bound message (tokens, counts, never content) and enforces per-user and server limits (429, per-user advisory lock namespace 5); `GET /ai/usage/me`. Urgent symptoms get fixed emergency guidance without a model call; without AI_PHI_ALLOWED identifiers in messages are redacted before the provider. Proposals expire (AI_ACTION_TTL_MINUTES). New tools: get_doctor_profile, get_clinic_help, get_dashboard_figures, list_appointments (staff; patient names to the model only with AI_PHI_ALLOWED), find_patient and propose_booking_for_patient (front desk, AI_PHI_ALLOWED). Results are stored as cards (`ai_messages.results`). Document upload needs AI_ENABLE_MEDICAL_DOCUMENT_UPLOAD too. Panel: role-based suggestions (only usable ones), doctor and appointment cards, "N of M messages left". See docs/AI_ASSISTANT.md | Keep raw REST calls to Gemini |
| D101 | Medical record documents through the assistant | New tools list_medical_documents, explain_medical_document, summarize_medical_documents and show_my_profile (services/ai/medical_tools.py) call document_service with the user's own Principal, so the record's rules apply unchanged: patients their own documents; doctors only through one of their appointments; reception and admins none (not even offered). Documents are read on this server only when the model calls a tool for a request about them (services/ai/medical_reports.py): PDF text page by page, local Tesseract OCR for scanned pages/images when installed, lab rows (test, value, unit, printed reference range, flag), dates exactly as printed; values are judged high/low only against the printed range. Results are shown as cards with page citations and fixed general information per test. Without AI_PHI_ALLOWED the provider gets ids and counts only (no titles, values or text); with it, fenced text and parsed values. Nothing is cached; file bytes are discarded after the request | Send documents to the free-tier model; pre-load the record into the prompt |
