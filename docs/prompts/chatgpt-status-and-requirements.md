You are helping me plan the next stage of my project, CLINIC AI ASSISTANT. Your job is NOT to write code. Your job is to write ONE implementation prompt that I will give to Claude Code (an AI coding agent that has full access to my repository and can read, edit, run commands and run tests). Read everything below, then produce that prompt using the output format at the end.

======================================================================
PART A — PROJECT IN ONE PARAGRAPH
======================================================================

A clinic-management platform with a role-aware AI assistant, built as a learning/interview project that should still look production-grade. Roles: patient, doctor, receptionist, admin. Stack: React 19 + Vite + react-router + axios (frontend, separate app) → REST → FastAPI (Python) → service layer → SQLAlchemy 2.x async (AsyncSession, asyncpg) → PostgreSQL, with Alembic migrations, JWT access tokens, bcrypt password hashing. Redis, Celery, WebSockets/SSE, AI, Docker and CI/CD are planned for later and must NOT be introduced in this stage.

The repository contains docs/ARCHITECTURE.md, an agreed architecture document that is the source of truth. Claude Code can read it; you cannot. The decisions from it that matter for this stage are summarised in Part D. The prompt you write must tell Claude Code to read docs/ARCHITECTURE.md first and to raise conflicts instead of silently choosing.

======================================================================
PART B — WHAT ACTUALLY EXISTS (verified by inspecting the code on 2026-09-29)
======================================================================

Layout: backend/ (FastAPI, venv at backend/venv) and frontend/ (Vite). Not a git repository yet. No tests folder. No docker-compose, no README at root.

Backend files that exist:
- app/main.py — creates the app, hardcoded CORS origin http://localhost:5173, mounts three routers from app/api/routes/ WITHOUT a version prefix (/auth, /departments, /doctors). Also GET / and GET /health.
- app/api/v1/router.py and app/api/v1/endpoints/ — exist but are EMPTY. Two competing router trees.
- app/core/config.py — pydantic-settings reading .env: database_url, secret_key, algorithm, access_token_expire_minutes, refresh_token_expire_days. No CORS or environment settings.
- app/core/security.py — passlib bcrypt hash/verify, create_access_token (claims: sub=user id, role, exp, type), generate_refresh_token (opaque random string).
- app/core/deps.py — get_current_user (HTTPBearer, decodes JWT, loads User by int id), require_role(*roles) checking a single enum column.
- app/core/clock.py — utcnow() returning timezone-aware UTC. Used by all models.
- app/db/base.py (DeclarativeBase, no naming convention), database.py (async engine with echo=True), session.py (get_db yields AsyncSession).
- app/services/ — EMPTY. All business logic and queries live in the route functions.
- No custom exceptions, no global exception handlers, no logging setup.

Models (all integer primary keys, all timestamps DateTime(timezone=True)):
- User: id, name, email (unique), password_hash, role (PG enum user_role: patient/doctor/receptionist/admin, default patient), is_active, created_at, updated_at.
- RefreshToken: id, user_id (FK users CASCADE), token (stored in PLAIN TEXT, unique), revoked, expires_at, created_at.
- Department: id, name (unique), description, created_at. No updated_at, no status.
- Doctor: id, user_id (FK users, ON DELETE CASCADE, unique), department_id (FK RESTRICT, no index), specialization (free-text string), bio, years_of_experience, consultation_fee Numeric(10,2) but typed Mapped[float], created_at, updated_at. Deliberately stores NO name — the name comes from User.
- Patient: DOES NOT EXIST. No model, schema, route, migration or page.

Schemas (Pydantic v2): user.py (UserCreate includes role: str = "patient"; UserResponse; UserLogin; Token; RefreshRequest; AccessTokenResponse), department.py (Create, Response), doctor.py (Create, Update, Response — consultation_fee typed as float).

Endpoints:
- /auth/register — CRITICAL BUG: accepts role from the request body, so anyone can register as admin.
- /auth/login — returns access token + refresh token in the JSON body.
- /auth/refresh — looks up the plain-text token, returns a new access token; NO rotation.
- /auth/logout — marks the refresh token revoked. /auth/me — current user.
- /departments — POST (admin), GET list (unpaginated), GET by id. No update/deactivate.
- /doctors — POST (admin; checks user exists, has doctor role, department exists, no duplicate profile), GET list (unpaginated, no filters, joins User for name), GET by id, PUT (admin), DELETE (admin, HARD delete).
- Errors are raised as HTTPException directly in routes; duplicates return 400 rather than 409.

Alembic (5 revisions, one linear chain; alembic current == alembic heads == fff745854020):
1. 5fe0b8c8ede5 create users (originally empty, since repaired to create the table in its historical shape)
2. 231b352f348f refresh_tokens, users.is_active/updated_at, role → PG enum
3. fadd14706b01 users/refresh_tokens timestamps → timestamptz
4. ca3b9a4cdbf9 departments + doctors
5. fff745854020 departments/doctors timestamps → timestamptz
alembic/env.py imports each model explicitly. Replaying the whole chain on a FRESH empty database has not been verified.

Other backend problems:
- requirements.txt is UTF-16 encoded (created by PowerShell redirect); pip install -r will likely fail on another machine.
- echo=True logs SQL parameters — will leak patient data once patients exist.
- passlib is unmaintained; bcrypt pinned to 4.0.1 to keep it working.
- backend/.env contains the real secret and there is no .gitignore at the root.

Frontend (frontend/src):
- services/api.js — axios with hardcoded baseURL http://127.0.0.1:8000, access and refresh tokens in localStorage, 401 → refresh → retry interceptor with a request queue.
- context/AuthContext.jsx — login, register (sends role "patient"), logout, fetchCurrentUser via /auth/me.
- components/ProtectedRoute.jsx, AdminRoute.jsx (checks user.role === "admin").
- pages: Login, Register, Dashboard (minimal), Doctors (public list, no search/filter/pagination), AdminDepartments (list + create only), AdminDoctors (create by typing a raw numeric user_id; list; update/delete wired in service).
- services/doctorService.js, departmentService.js.
- No patient pages, no staff/user management pages, no layout/navigation, no shared error handling.

Status summary:
- Completed: frontend/backend separation; async DB session layer; Alembic chain consistent with the dev DB; timezone-aware UTC policy applied in code and schema.
- Partial: authentication (works in code, insecure token storage, no rotation, register escalation); authorization (single enum role, no permissions, no per-record checks); Department (backend + frontend partial); Doctor (backend CRUD + frontend partial).
- Needs verification: login/refresh/logout at runtime against the timestamptz columns; migration chain from an empty database; whether SECRET_KEY has been rotated.
- Not started: services layer, /api/v1, exception handling, logging, RBAC tables, AuditLog, Patient, StaffProfile, Specialty, schedules, appointments, queue, clinical records, notifications, AI, tests, Redis, Celery, Docker, CI/CD.

======================================================================
PART C — WHAT THIS STAGE MUST ACHIEVE
======================================================================

The goal is to finish the foundation and bring everything already started to a genuinely complete state (model + migration + schema + service + router + authorization + frontend + tests), then build Patient as the next entity on top of it. Nothing from later phases (appointments, schedules, AI, Redis, Celery, Docker) belongs in this stage.

C1. Foundation (must be done first — it blocks everything else)
- git init with a root .gitignore (venv, .env, node_modules, dist, __pycache__), plus backend/.env.example with placeholder values. Rotate SECRET_KEY.
- Fix the register privilege escalation: self-registration always creates a patient; role in the body is rejected or ignored. Update the frontend register call accordingly.
- Re-save requirements.txt as UTF-8; add only the packages this stage needs (e.g. pytest, pytest-asyncio, httpx; replacing passlib is optional and must be justified).
- Settings: CORS origins, environment name, SQL echo flag, frontend API base URL (via Vite env var) — all from configuration.
- Add a MetaData naming convention on Base before more tables are created.
- Move every router under /api/v1 via app/api/v1/router.py and endpoints/; remove the old app/api/routes tree; update frontend service URLs.
- Introduce domain exceptions + global exception handlers producing one consistent error shape; IntegrityError → 409; never leak SQL/driver text.
- Basic structured logging (no passwords, tokens or health data).
- Move business logic out of routers into app/services/ (auth, department, doctor).

C2. Decisions Claude Code must confirm with me BEFORE writing any migration (your prompt must list these as explicit questions, not decide them):
- Switch primary keys to UUID now (architecture decision D6) while tables are nearly empty, or keep integers?
- Roles: move now from the single enum column to Role/Permission tables with User↔Role many-to-many (architecture D3/D4), or keep the enum for this stage and add permissions later?
- Doctor naming: keep the name only on User (current design), or add professional fields to Doctor (license_number, title, phone, room_number, status) as my original brief suggested? Personal/legal names for patients are a separate question and belong on Patient.
- Refresh token transport: move to an HttpOnly cookie now (architecture D8), or keep JSON body with hashing + rotation for now?

C3. Authentication hardening
- Store refresh tokens hashed (SHA-256), rotate on every refresh, detect reuse and revoke the token family.
- Logout revokes; deactivated users cannot refresh.
- Verify login → refresh → logout end to end against PostgreSQL.

C4. Authorization
- A require_permission-style dependency (or a clearly justified interim if the enum is kept), used by every protected endpoint.
- Admin user management needed by existing features: create staff/doctor accounts, list/search users, deactivate. This also fixes the "type a raw user_id" problem in AdminDoctors.

C5. Department — complete it
- Add updated_at and an active/inactive status; update + deactivate (no hard delete); paginated list; public read vs admin write; 409 on duplicate name.
- Frontend: admin list with edit/deactivate; public department list.

C6. Doctor — complete it
- Money as Decimal end to end (model type, schemas, JSON serialisation); never float.
- User FK ON DELETE RESTRICT (deactivate, never delete); index department_id; replace hard delete with deactivation.
- Paginated, database-level filtering: department, specialization, min experience, fee range, name search (join to User), active only for the public view.
- Separate public vs admin response schemas (no email or internal fields in the public directory).
- A doctor can view/update their own limited profile fields; admin manages everything.
- Frontend: public directory with search/filters/pagination and a doctor detail page; admin create (pick a user from a list, or create the doctor account in the same flow), edit, deactivate; doctor "my profile" page.
- Specialty stays a string in this stage unless Claude Code shows a strong reason to create the Specialty lookup now.

C7. Patient — build it (next entity, per docs/ARCHITECTURE.md §3 and §10)
- patients.user_id is UNIQUE and NULLABLE: reception can register walk-in patients who have no login; the account can be linked later.
- Fields per the architecture: MRN (generated, unique), legal first/last name, date of birth (date type), sex/gender fields as the architecture defines, contact phone and email (separate from the login email), address, preferred language, registered_by_user_id, timestamps, status. No medical history on this table.
- Self-registration creates the User and linked Patient profile in one transaction.
- Receptionist/admin can create and search patients; a patient can read/update only their own profile. Another patient's record returns 404, not 403.
- Role-specific response schemas (a patient's own view vs staff administrative view).
- Frontend: patient "my profile" page; receptionist patient search + create/edit pages; a basic role-aware layout/navigation.

C8. Testing (must exist by the end of this stage)
- pytest + pytest-asyncio + httpx.AsyncClient against a real PostgreSQL test database (not SQLite), with per-test transaction rollback.
- Auth tests: register cannot grant admin; login; refresh rotation; reuse detection; logout; inactive user.
- Authorization matrix: anonymous → 401 on protected routes; patient A cannot read patient B (404); non-admin cannot manage departments/doctors (403); receptionist can create patients.
- Service/endpoint tests for Department, Doctor filters/pagination, Patient.
- Migration test: alembic upgrade head on an empty database succeeds and matches the models (no pending autogenerate diff).

C9. Alembic rules that the prompt must repeat
- Run alembic current and alembic heads before generating anything; never delete or edit applied migrations to fix errors; never stamp head to hide problems; review every autogenerated file by hand (enum changes are not autogenerated); one migration per logical change; every new model imported in alembic/env.py; each migration must also downgrade.

======================================================================
PART D — ARCHITECTURE DECISIONS ALREADY SETTLED (do not contradict)
======================================================================

- User = login identity only. Doctor/Patient/Staff are separate profile tables. No passwords or tokens on profiles.
- Two authorization layers: permission check in the dependency; per-record check in the service. Plus role-specific response schemas.
- Services raise domain exceptions, never HTTPException, so later Celery tasks and AI tools can reuse them.
- No generic repository layer; services + small query modules only when needed.
- timestamptz everywhere with aware UTC datetimes; date for birthdays; Numeric(10,2) for money.
- Clinical and identity data is deactivated, not deleted.
- Tests run on real PostgreSQL with httpx.AsyncClient.
- Filtering and pagination happen in SQL, never in Python.

======================================================================
PART E — WHAT I WANT FROM YOU (output format)
======================================================================

Write a single prompt addressed to Claude Code. Requirements for the prompt:

1. Start by telling Claude Code to read docs/ARCHITECTURE.md and inspect the repo, and to report any difference between the repo and Part B before changing anything.
2. Ask Claude Code to put the four C2 questions to me and wait for my answers before any migration.
3. Split the work into ordered STAGES (for example: Foundation → Auth hardening → Authorization + user management → Department → Doctor → Patient → Tests throughout). For each stage list: goal, concrete requirements, files likely touched, migration needed (yes/no), frontend work, tests, and a "definition of done" gate that must pass before the next stage starts.
4. Tell Claude Code to stop after each stage, summarise what changed, show test results, and wait for my go-ahead.
5. Describe requirements and acceptance criteria only. Do not include implementation code, and do not invent file contents or endpoints that contradict Part B or Part D.
6. Keep it scoped: explicitly list what is OUT of scope for this stage (appointments, schedules, queue, clinical notes, notifications, AI, Redis, Celery, WebSockets/SSE, Docker, CI/CD).
7. End with a checklist Claude Code must use to produce a final progress report (completed / partial / needs verification / not started).

Return only the prompt, ready to paste.
