"""A database behind the code's migrations (the D120 incident, 2026-11-08: Neon
was on d5e9a3c7b418, so every query naming appointments.booking_mode failed and
the appointment list and booking showed "An unexpected error occurred").

Such a failure must be named, not hidden: a specific 503 for the client, a
specific log line for the operator, and a startup check that spots it."""

import os

from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db import schema_check
from app.services import appointment_service


class _UndefinedColumn(Exception):
    sqlstate = "42703"


async def test_a_missing_column_is_reported_as_a_schema_update_not_a_generic_500(client, clinic, monkeypatch):
    async def broken(*args, **kwargs):
        raise ProgrammingError("SELECT appointments.booking_mode ...", {}, _UndefinedColumn("column does not exist"))

    monkeypatch.setattr(appointment_service, "list_appointments", broken)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    response = await client.get("/api/v1/appointments/", headers=alice)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "SCHEMA_OUT_OF_DATE"
    assert "booking_mode" not in response.text and "SELECT" not in response.text  # no SQL reaches the client


async def test_the_startup_check_compares_the_database_with_the_code():
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        result = await schema_check.check(engine)
    finally:
        await engine.dispose()
    assert result["status"] == "current"  # the test database is migrated to head
    assert result["database"] == result["code"] == sorted(schema_check.code_heads())


def test_sqlstate_is_read_through_the_driver_wrapper():
    wrapped = ProgrammingError("x", {}, _UndefinedColumn("x"))
    assert schema_check.sqlstate_of(wrapped) == "42703"
    assert schema_check.sqlstate_of(ValueError("x")) is None
