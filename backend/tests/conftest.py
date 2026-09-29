"""Test infrastructure.

Tests run against a real PostgreSQL database, never SQLite: the schema relies on
PostgreSQL types and constraints that SQLite does not have.

* The test database is dropped and rebuilt from the Alembic chain once per run,
  so every run also proves the migrations build a database from empty.
* Each test runs inside a transaction that is rolled back afterwards; services
  that call ``commit()`` only release a savepoint.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Must happen before anything imports app.core.config, which reads settings once.
_env = dotenv_values(BACKEND_DIR / ".env")
_dev_url = make_url(os.environ.get("DATABASE_URL") or _env["DATABASE_URL"])
_test_url = make_url(
    os.environ.get("TEST_DATABASE_URL") or _env.get("TEST_DATABASE_URL") or _dev_url.set(database=f"{_dev_url.database}_test")
)
if _test_url.database == _dev_url.database:
    raise RuntimeError("Refusing to run tests against the development database")
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["SQL_ECHO"] = "false"

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.permissions import RoleCode  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import rbac_service  # noqa: E402

TEST_PASSWORD = "Str0ng-test-password"

# bcrypt at production cost (12 rounds) is deliberately slow; tests only need
# correct hashing, not brute-force resistance. Production code is unaffected.
from app.core import security  # noqa: E402

security.pwd_context.update(bcrypt__rounds=4)
TEST_PASSWORD_HASH = hash_password(TEST_PASSWORD)


def alembic_config() -> Config:
    # No ini file on purpose: alembic.ini's logging section would reconfigure
    # (and disable) the application's loggers mid-run.
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


async def _recreate_test_database() -> None:
    admin_dsn = _test_url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    conn = await asyncpg.connect(admin_dsn)
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{_test_url.database}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{_test_url.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    asyncio.run(_recreate_test_database())
    command.upgrade(alembic_config(), "head")


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        # Mirror production: a failed request rolls back its uncommitted work
        # (here: back to the last savepoint, so fixture data survives).
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db_session: AsyncSession):
    async def _make_user(
        role: RoleCode | str | None = RoleCode.patient,
        email: str | None = None,
        is_active: bool = True,
        name: str | None = None,
    ) -> User:
        label = str(role) if role else "norole"
        user = User(
            name=name or f"Test {label}",
            email=email or f"{label}-{os.urandom(4).hex()}@example.com",
            password_hash=TEST_PASSWORD_HASH,
            is_active=is_active,
        )
        db_session.add(user)
        await db_session.flush()
        if role is not None:
            await rbac_service.grant_roles(db_session, user.id, [role])
        # Inside the test transaction this only releases a savepoint.
        await db_session.commit()
        # Detached, so its attributes stay readable even after a request fails
        # and rolls the session back. To modify the row, load it with db_session.get().
        db_session.expunge(user)
        return user

    return _make_user


async def login(client: AsyncClient, email: str, password: str = TEST_PASSWORD) -> dict[str, str]:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth_headers(client: AsyncClient, make_user):
    """Create a user with the given role, log in through the API, return headers."""

    async def _auth_headers(role: RoleCode = RoleCode.patient, **kwargs) -> dict[str, str]:
        user = await make_user(role, **kwargs)
        return await login(client, user.email)

    return _auth_headers


@pytest.fixture
def make_role(db_session: AsyncSession):
    """Create a custom role holding exactly the given permissions."""
    from sqlalchemy import select

    from app.models.rbac import Permission, Role, RolePermission

    async def _make_role(code: str, permissions: list[str]) -> Role:
        role = Role(code=code, name=code.title())
        db_session.add(role)
        await db_session.flush()
        for perm in await db_session.scalars(select(Permission).where(Permission.code.in_(permissions))):
            db_session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await db_session.commit()
        db_session.expunge(role)
        return role

    return _make_role


@pytest.fixture
def make_department(db_session: AsyncSession):
    from app.models.department import Department

    async def _make_department(name: str | None = None, *, is_active: bool = True, timezone: str = "Asia/Karachi"):
        department = Department(name=name or f"Dept {os.urandom(3).hex()}", timezone=timezone, is_active=is_active)
        db_session.add(department)
        await db_session.commit()
        db_session.expunge(department)
        return department

    return _make_department


@pytest.fixture
def make_doctor(db_session: AsyncSession, make_user, make_department):
    """A doctor profile with its own login (doctor role) and department."""
    from decimal import Decimal

    from app.models.doctor import Doctor

    async def _make_doctor(
        *,
        name: str | None = None,
        department=None,
        specialization: str = "General Medicine",
        years_of_experience: int = 5,
        consultation_fee: Decimal | None = Decimal("100.00"),
        is_active: bool = True,
        **fields,
    ) -> Doctor:
        user = await make_user(RoleCode.doctor, name=name)
        department = department or await make_department()
        doctor = Doctor(
            user_id=user.id,
            department_id=department.id,
            specialization=specialization,
            years_of_experience=years_of_experience,
            consultation_fee=consultation_fee,
            is_active=is_active,
            **fields,
        )
        db_session.add(doctor)
        await db_session.commit()
        db_session.expunge(doctor)
        return doctor

    return _make_doctor


@pytest.fixture
def make_patient(db_session: AsyncSession, make_user):
    """A patient profile; with `with_account=True` it also gets a patient login."""
    from datetime import date

    from app.models.patient import Patient

    async def _make_patient(
        *,
        first_name: str = "Pat",
        last_name: str | None = None,
        date_of_birth: date = date(1990, 5, 17),
        with_account: bool = False,
        is_active: bool = True,
        **fields,
    ) -> Patient:
        user_id = None
        if with_account:
            user_id = (await make_user(RoleCode.patient, name=f"{first_name} {last_name or 'Patient'}")).id
        patient = Patient(
            user_id=user_id,
            first_name=first_name,
            last_name=last_name or f"Patient{os.urandom(2).hex()}",
            date_of_birth=date_of_birth,
            is_active=is_active,
            **fields,
        )
        db_session.add(patient)
        await db_session.commit()
        db_session.expunge(patient)
        return patient

    return _make_patient


async def login_as(client: AsyncClient, db_session: AsyncSession, user_id) -> dict[str, str]:
    """Log in as an existing fixture user (by id)."""
    user = await db_session.get(User, user_id)
    return await login(client, user.email)
