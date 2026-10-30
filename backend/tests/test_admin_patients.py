"""Admin > Patients (D91): gender filter, column sorting, bulk status
changes, audit entries, and MRNs under concurrent registration."""

import asyncio
import os
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import clock
from app.core.permissions import Principal, RoleCode
from app.models import Appointment, AuditLog, Patient, User
from app.models.appointment import AppointmentStatus
from app.schemas.patient import PatientCreate
from app.services import patient_service
from tests.conftest import TEST_PASSWORD_HASH

PATIENTS = "/api/v1/patients/"


@pytest.fixture
async def admin(auth_headers):
    return await auth_headers(RoleCode.admin)


@pytest.fixture
def tag():
    return f"Zp{os.urandom(3).hex()}"


async def listed(client, headers, **params):
    response = await client.get(PATIENTS, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def first_names(page):
    return [p["first_name"] for p in page["items"]]


async def test_gender_filter_keeps_unspecified_patients_findable(client, admin, make_patient, tag):
    await make_patient(first_name="Fem", last_name=tag, sex_at_birth="female")
    await make_patient(first_name="Mal", last_name=tag, sex_at_birth="male")
    await make_patient(first_name="Unk", last_name=tag)  # unknown by default
    assert first_names(await listed(client, admin, q=tag, sex_at_birth="female")) == ["Fem"]
    assert first_names(await listed(client, admin, q=tag, sex_at_birth="unknown")) == ["Unk"]
    assert len((await listed(client, admin, q=tag))["items"]) == 3  # no filter: everyone
    assert (await client.get(PATIENTS, params={"sex_at_birth": "robot"}, headers=admin)).status_code == 422


async def test_sorting_by_every_column(client, admin, make_patient, tag):
    a = await make_patient(first_name="Ann", last_name=f"{tag} A", email=f"c-{tag}@example.com", phone="0300 3")
    b = await make_patient(first_name="Bob", last_name=f"{tag} B", email=None, phone="0300 1", is_active=False)
    c = await make_patient(first_name="Cal", last_name=f"{tag} C", email=f"a-{tag}@example.com", phone=None)
    mrns = {a.first_name: a.mrn, b.first_name: b.mrn, c.first_name: c.mrn}

    async def order(sort):
        return first_names(await listed(client, admin, q=tag, sort=sort))

    assert await order("name") == ["Ann", "Bob", "Cal"]
    assert await order("-name") == ["Cal", "Bob", "Ann"]
    assert await order("mrn") == sorted(mrns, key=mrns.get)
    assert await order("email") == ["Cal", "Ann", "Bob"]  # no email: last
    assert await order("-email") == ["Ann", "Cal", "Bob"]
    assert await order("phone") == ["Bob", "Ann", "Cal"]  # no phone: last
    assert await order("status") == ["Ann", "Cal", "Bob"]  # active first
    assert (await client.get(PATIENTS, params={"sort": "dob"}, headers=admin)).status_code == 422


async def test_search_by_email_mrn_and_phone_pages(client, admin, make_patient, tag):
    walk_in = await make_patient(first_name="Walk", last_name=tag, phone=f"0321{tag[-4:]}")
    for i in range(11):
        await make_patient(first_name=f"P{i:02d}", last_name=tag)
    assert first_names(await listed(client, admin, q=walk_in.mrn.lower())) == ["Walk"]
    assert first_names(await listed(client, admin, q=f"0321{tag[-4:]}")) == ["Walk"]
    page2 = await listed(client, admin, q=tag, page=2, page_size=10)
    assert page2["total"] == 12 and len(page2["items"]) == 2


async def test_bulk_status_reports_each_patient_and_keeps_appointments(client, db_session, admin, make_patient, make_doctor, make_user):
    free = await make_patient(first_name="Free")
    booked = await make_patient(first_name="Booked")
    doctor = await make_doctor()
    booker = await make_user(RoleCode.receptionist)
    start = clock.utcnow() + timedelta(days=2)
    db_session.add(Appointment(patient_id=booked.id, doctor_id=doctor.id, starts_at=start, ends_at=start + timedelta(minutes=30),
                               status=AppointmentStatus.scheduled, booked_by_user_id=booker.id))
    await db_session.commit()
    free_id, booked_id = free.id, booked.id

    response = await client.post(f"{PATIENTS}bulk-status", json={"patient_ids": [str(free_id), str(booked_id)], "is_active": False}, headers=admin)
    assert response.status_code == 200, response.text
    results = {r["patient_id"]: r for r in response.json()}
    assert results[str(free_id)]["ok"] is True
    assert results[str(booked_id)]["code"] == "HAS_UPCOMING_APPOINTMENTS"
    kept = await db_session.scalar(select(Appointment).where(Appointment.patient_id == booked_id))
    assert kept.status == AppointmentStatus.scheduled

    audited = await db_session.scalars(select(AuditLog.action).where(AuditLog.target_id == str(free_id)))
    assert list(audited) == ["patient.deactivated"]
    stored = await db_session.get(Patient, free_id)
    await db_session.refresh(stored)
    assert stored.is_active is False and stored.mrn == free.mrn  # MRN kept


async def test_bulk_status_validation_and_permissions(client, auth_headers, admin, make_patient):
    patient = await make_patient()
    assert (await client.post(f"{PATIENTS}bulk-status", json={"patient_ids": [], "is_active": False}, headers=admin)).status_code == 422
    too_many = [str(patient.id)] * 101
    assert (await client.post(f"{PATIENTS}bulk-status", json={"patient_ids": too_many, "is_active": False}, headers=admin)).status_code == 422
    for role in (RoleCode.patient, RoleCode.doctor):
        headers = await auth_headers(role)
        body = {"patient_ids": [str(patient.id)], "is_active": False}
        assert (await client.post(f"{PATIENTS}bulk-status", json=body, headers=headers)).status_code == 403


async def test_concurrent_registrations_get_distinct_mrns():
    """Separate connections, committed rows (the sequence is only shared
    across transactions), deleted afterwards."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    tag = os.urandom(3).hex()
    async with AsyncSession(engine, expire_on_commit=False) as setup:
        staff = User(name="MRN Staff", email=f"mrn-{tag}@example.com", password_hash=TEST_PASSWORD_HASH)
        setup.add(staff)
        await setup.commit()
    principal = Principal(user=staff, roles=frozenset({"receptionist"}), permissions=frozenset({"patient:create"}))

    async def register(i):
        async with AsyncSession(engine, expire_on_commit=False) as db:
            data = PatientCreate(first_name=f"Race{i}", last_name=tag, date_of_birth=date(2000, 1, 1))
            return (await patient_service.create_patient(db, principal, data)).mrn

    try:
        mrns = await asyncio.gather(*(register(i) for i in range(8)))
        assert len(set(mrns)) == 8
        assert all(m.startswith("MRN") and len(m) == 11 for m in mrns)
    finally:
        async with AsyncSession(engine) as db:
            await db.execute(delete(Patient).where(Patient.last_name == tag))
            await db.execute(delete(User).where(User.id == staff.id))
            await db.commit()
        await engine.dispose()
