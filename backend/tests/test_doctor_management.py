"""Admin > Doctors (D90): staff search by contact details, column sorting,
filter options, upcoming-appointment count, strict edits and audit entries."""

import os
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.permissions import RoleCode
from app.models import Appointment, AuditLog, Patient
from app.models.appointment import AppointmentStatus

DOCTORS = "/api/v1/doctors/"


@pytest.fixture
async def admin(auth_headers):
    return await auth_headers(RoleCode.admin)


@pytest.fixture
def tag():
    return f"Zd{os.urandom(3).hex()}"


async def listed(client, headers, **params):
    response = await client.get(DOCTORS, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def names(page):
    return [d["name"] for d in page["items"]]


async def actions(db_session, target_id):
    return list((await db_session.scalars(select(AuditLog.action).where(AuditLog.target_id == str(target_id)))).all())


async def test_staff_search_finds_email_and_phone_but_the_directory_does_not(client, admin, make_doctor, tag):
    await make_doctor(name=f"{tag} Phone", phone=f"0300{tag}")
    by_email = await make_doctor(name="Someone Else")
    email = (await client.get(f"{DOCTORS}{by_email.id}", headers=admin)).json()["email"]

    assert names(await listed(client, admin, q=tag.upper())) == [f"{tag} Phone"]
    assert names(await listed(client, admin, q=email.split("@")[0].upper())) == ["Someone Else"]
    public = await client.get("/api/v1/public/doctors/", params={"q": f"0300{tag}"})
    assert public.json()["total"] == 0  # contact details never searchable publicly


async def test_sorting_by_every_column_is_server_side(client, admin, make_department, make_doctor, tag):
    a_dept = await make_department(f"{tag} A-dept")
    b_dept = await make_department(f"{tag} B-dept")
    await make_doctor(name=f"{tag} One", department=b_dept, specialization="Neurologist", years_of_experience=3)
    await make_doctor(name=f"{tag} Two", department=a_dept, specialization="cardiologist", years_of_experience=9, is_active=False)
    await make_doctor(name=f"{tag} Three", department=a_dept, specialization="Dermatologist", years_of_experience=5)

    async def order(sort):
        return names(await listed(client, admin, q=tag, sort=sort))

    assert await order("name_asc") == [f"{tag} One", f"{tag} Three", f"{tag} Two"]
    assert await order("department_asc") == [f"{tag} Three", f"{tag} Two", f"{tag} One"]
    assert await order("department_desc") == [f"{tag} One", f"{tag} Three", f"{tag} Two"]
    assert await order("specialization_asc") == [f"{tag} Two", f"{tag} Three", f"{tag} One"]  # case-insensitive
    assert await order("experience_desc") == [f"{tag} Two", f"{tag} Three", f"{tag} One"]
    assert await order("status_asc") == [f"{tag} One", f"{tag} Three", f"{tag} Two"]  # active first
    assert await order("status_desc") == [f"{tag} Two", f"{tag} One", f"{tag} Three"]


async def test_filters_combine_and_page(client, admin, make_department, make_doctor, tag):
    dept = await make_department(f"{tag} Cardio")
    for i in range(3):
        await make_doctor(name=f"{tag} C{i}", department=dept, specialization="Cardiologist")
    await make_doctor(name=f"{tag} Off", department=dept, specialization="Cardiologist", is_active=False)
    await make_doctor(name=f"{tag} Elsewhere", specialization="Cardiologist")

    page = await listed(client, admin, q=tag, department_id=str(dept.id), specialization="Cardiologist", is_active="true", page_size=2)
    assert page["total"] == 3 and page["total_pages"] == 2 and len(page["items"]) == 2
    assert names(await listed(client, admin, q=tag, is_active="false")) == [f"{tag} Off"]


async def test_specialization_options_include_inactive_doctors(client, admin, make_doctor, tag):
    await make_doctor(specialization=f"{tag} Retired Speciality", is_active=False)
    staff = (await client.get(f"{DOCTORS}specializations", headers=admin)).json()
    assert f"{tag} Retired Speciality" in staff
    public = (await client.get("/api/v1/public/doctors/specializations")).json()
    assert f"{tag} Retired Speciality" not in public


async def test_detail_counts_upcoming_and_deactivation_keeps_them(client, db_session, admin, make_doctor, make_user):
    doctor = await make_doctor()
    booker = await make_user(RoleCode.receptionist)
    patient = Patient(first_name="P", last_name="Q", date_of_birth=date(1990, 1, 1))
    db_session.add(patient)
    await db_session.flush()
    start = clock.utcnow() + timedelta(days=3)
    db_session.add(Appointment(patient_id=patient.id, doctor_id=doctor.id, starts_at=start, ends_at=start + timedelta(minutes=30),
                               status=AppointmentStatus.scheduled, booked_by_user_id=booker.id))
    await db_session.commit()

    assert (await client.get(f"{DOCTORS}{doctor.id}", headers=admin)).json()["upcoming_appointments"] == 1
    refused = await client.post(f"{DOCTORS}{doctor.id}/deactivate", headers=admin)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "HAS_UPCOMING_APPOINTMENTS"
    kept = await db_session.scalar(select(Appointment).where(Appointment.doctor_id == doctor.id))
    assert kept.status == AppointmentStatus.scheduled
    # Lists do not carry the count.
    assert (await listed(client, admin, q="zzzz-none"))["items"] == []


async def test_status_department_and_creation_are_audited(client, db_session, admin, make_department, make_doctor):
    doctor = await make_doctor()
    target = await make_department()
    assert (await client.post(f"{DOCTORS}{doctor.id}/deactivate", headers=admin)).status_code == 200
    assert (await client.post(f"{DOCTORS}{doctor.id}/activate", headers=admin)).status_code == 200
    moved = await client.patch(f"{DOCTORS}{doctor.id}", json={"department_id": str(target.id)}, headers=admin)
    assert moved.status_code == 200
    assert await actions(db_session, doctor.id) == ["doctor.deactivated", "doctor.activated", "doctor.department_changed"]

    body = {
        "account": {"name": "New Doc", "email": f"new-doc-{os.urandom(3).hex()}@example.com", "password": "Temp-pass-123"},
        "department_id": str(target.id),
        "specialization": "Cardiologist",
        "years_of_experience": 4,
        "phone": "+92 300 1234567",
    }
    created = await client.post(DOCTORS, json=body, headers=admin)
    assert created.status_code == 201, created.text
    assert await actions(db_session, created.json()["id"]) == ["doctor.created"]
    duplicate = await client.post(DOCTORS, json=body, headers=admin)
    assert duplicate.status_code == 409


async def test_edit_refuses_status_and_account_fields(client, admin, make_doctor):
    doctor = await make_doctor()
    for field in ({"is_active": False}, {"user_id": "x"}, {"email": "a@b.c"}):
        assert (await client.patch(f"{DOCTORS}{doctor.id}", json=field, headers=admin)).status_code == 422, field
    ok = await client.patch(f"{DOCTORS}{doctor.id}", json={"specialization": "Cardiologist", "years_of_experience": 12}, headers=admin)
    assert ok.json()["years_of_experience"] == 12


async def test_moving_into_an_inactive_department_is_refused(client, admin, make_department, make_doctor):
    doctor = await make_doctor()
    closed = await make_department(is_active=False)
    response = await client.patch(f"{DOCTORS}{doctor.id}", json={"department_id": str(closed.id)}, headers=admin)
    assert response.json()["error"]["code"] == "DEPARTMENT_INACTIVE"


@pytest.mark.parametrize("role", [RoleCode.patient, RoleCode.receptionist, RoleCode.doctor, RoleCode.doctor_applicant])
async def test_doctor_administration_is_closed_to_other_roles(client, auth_headers, make_doctor, role):
    doctor = await make_doctor()
    headers = await auth_headers(role)
    assert (await client.post(f"{DOCTORS}{doctor.id}/deactivate", headers=headers)).status_code == 403
    assert (await client.patch(f"{DOCTORS}{doctor.id}", json={"specialization": "X"}, headers=headers)).status_code == 403
    assert (await client.post(DOCTORS, json={}, headers=headers)).status_code in (403, 422)
    # Reviewing applications is for reviewers only: no one approves themselves.
    assert (await client.get("/api/v1/doctor-applications/", headers=headers)).status_code == 403
