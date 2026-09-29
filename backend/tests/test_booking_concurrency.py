"""Two patients race for the same slot on separate connections.

Exactly one booking may succeed; the other must fail with a clean slot
conflict (a 409 at the API) — never a 500, and never a second booking.

A gate holds each request just before it inserts, until the other arrives
(or one second passes). Without the per-doctor booking lock both arrive,
insert at the same instant and deadlock on the EXCLUDE constraint — which
is how this bug was found. With the lock, the second request cannot reach
the gate until the first has committed, then sees the slot is taken.

This test commits real rows (it cannot run inside the per-test rollback
transaction, which would hide each session's data from the other), so it
creates its own data and deletes it afterwards.
"""

import asyncio
import os
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.exceptions import ConflictError
from app.core.permissions import RoleCode
from app.models import (
    Appointment,
    AppointmentStatusHistory,
    Department,
    Doctor,
    Patient,
    ScheduleTemplate,
    User,
    UserRole,
)
from app.schemas.appointment import AppointmentCreate
from app.services import appointment_service, rbac_service
from tests.conftest import TEST_PASSWORD_HASH

RACERS = 2


async def test_parallel_bookings_for_one_slot_yield_exactly_one_appointment():
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    tag = os.urandom(3).hex()
    tz = ZoneInfo("Asia/Karachi")
    created: dict[str, list] = {"users": [], "patients": []}

    async with AsyncSession(engine, expire_on_commit=False) as setup:
        department = Department(name=f"Race {tag}", timezone="Asia/Karachi")
        doctor_user = User(name="Race Doctor", email=f"race-dr-{tag}@example.com", password_hash=TEST_PASSWORD_HASH)
        setup.add_all([department, doctor_user])
        await setup.flush()
        await rbac_service.grant_roles(setup, doctor_user.id, [RoleCode.doctor])
        doctor = Doctor(user_id=doctor_user.id, department_id=department.id, specialization="GP")
        setup.add(doctor)
        await setup.flush()
        today = datetime.now(tz).date()
        setup.add(ScheduleTemplate(
            doctor_id=doctor.id, weekday=(today + timedelta(days=3)).weekday(), start_time=time(9), end_time=time(10),
            slot_minutes=30, valid_from=today,
        ))
        created["users"].append(doctor_user.id)
        for i in range(RACERS):
            user = User(name=f"Racer {i}", email=f"racer{i}-{tag}@example.com", password_hash=TEST_PASSWORD_HASH)
            setup.add(user)
            await setup.flush()
            await rbac_service.grant_roles(setup, user.id, [RoleCode.patient])
            patient = Patient(user_id=user.id, first_name="Racer", last_name=str(i), date_of_birth=date(1990, 1, 1))
            setup.add(patient)
            await setup.flush()
            created["users"].append(user.id)
            created["patients"].append(patient.id)
        await setup.commit()

    starts_at = datetime.combine(today + timedelta(days=3), time(9), tzinfo=tz).astimezone(ZoneInfo("UTC"))
    request = AppointmentCreate(doctor_id=doctor.id, starts_at=starts_at)

    arrived = 0
    both_here = asyncio.Event()
    original = appointment_service._ensure_patient_free

    async def gate(*args, **kwargs):
        nonlocal arrived
        await original(*args, **kwargs)
        arrived += 1
        if arrived == RACERS:
            both_here.set()
        try:
            await asyncio.wait_for(both_here.wait(), timeout=1.0)
        except TimeoutError:
            pass  # the other request is (correctly) blocked on the booking lock

    async def attempt(user_id):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            principal = await rbac_service.load_principal(session, await session.get(User, user_id))
            try:
                await appointment_service.book(session, principal, request, None)
                return "booked"
            except ConflictError as exc:
                return exc.code

    appointment_service._ensure_patient_free = gate
    try:
        results = await asyncio.gather(*(attempt(user_id) for user_id in created["users"][1:]))
    finally:
        appointment_service._ensure_patient_free = original
        async with AsyncSession(engine) as cleanup:
            appointment_ids = [a for a in (await cleanup.scalars(
                Appointment.__table__.select().with_only_columns(Appointment.id).where(Appointment.doctor_id == doctor.id)
            )).all()]
            await cleanup.execute(delete(AppointmentStatusHistory).where(AppointmentStatusHistory.appointment_id.in_(appointment_ids)))
            await cleanup.execute(delete(Appointment).where(Appointment.doctor_id == doctor.id))
            await cleanup.execute(delete(ScheduleTemplate).where(ScheduleTemplate.doctor_id == doctor.id))
            await cleanup.execute(delete(Doctor).where(Doctor.id == doctor.id))
            await cleanup.execute(delete(Patient).where(Patient.id.in_(created["patients"])))
            await cleanup.execute(delete(UserRole).where(UserRole.user_id.in_(created["users"])))
            await cleanup.execute(delete(User).where(User.id.in_(created["users"])))
            await cleanup.execute(delete(Department).where(Department.id == department.id))
            await cleanup.commit()
        await engine.dispose()

    assert sorted(results) == ["SLOT_UNAVAILABLE", "booked"], results
