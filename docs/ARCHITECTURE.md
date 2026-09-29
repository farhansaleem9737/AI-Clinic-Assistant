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

**Registration is patient-only.** `POST /api/v1/auth/register` ignores any role in the body.
Staff accounts are created by an admin through an invitation flow.

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
| Patient | self, receptionist, admin | owner, related clinician, ops staff, admin | owner (contact only), staff, admin | never — deactivate/merge |
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
