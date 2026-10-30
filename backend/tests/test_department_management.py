"""Admin > Departments (D89): list with doctor counts and previews, search,
status filter, sorting, paging, icon metadata, detail, and what deactivation
does and does not do."""

import os
from datetime import date, timedelta

import pytest

from app.core import clock
from app.core.exceptions import NotFoundError
from app.core.permissions import RoleCode
from app.models import Appointment, Patient, User
from app.models.appointment import AppointmentStatus
from app.services import availability_service

ADMIN = "/api/v1/departments/"


@pytest.fixture
async def admin(auth_headers):
    return await auth_headers(RoleCode.admin)


@pytest.fixture
def tag():
    return f"Zq{os.urandom(3).hex()}"


async def listed(client, headers, **params):
    response = await client.get(ADMIN, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_counts_and_previews_only_practising_doctors(client, db_session, admin, make_department, make_doctor, tag):
    department = await make_department(f"{tag} Cardiology")
    names = ["Dr Delta", "Dr Alpha", "Dr Charlie", "Dr Bravo"]
    for name in names:
        await make_doctor(department=department, name=name)
    await make_doctor(department=department, name="Dr Retired", is_active=False)
    locked_out = await make_doctor(department=department, name="Dr Locked")
    user = await db_session.get(User, locked_out.user_id)
    user.is_active = False
    await db_session.commit()

    row = (await listed(client, admin, q=tag))["items"][0]
    assert row["doctor_count"] == 4
    assert [d["name"] for d in row["doctors_preview"]] == ["Dr Alpha", "Dr Bravo", "Dr Charlie"]
    assert row["timezone"] == "Asia/Karachi"

    await make_department(f"{tag} Empty")
    empty = (await listed(client, admin, q=f"{tag} Empty"))["items"][0]
    assert empty["doctor_count"] == 0 and empty["doctors_preview"] == []


async def test_search_status_sort_and_paging(client, admin, make_department, make_doctor, tag):
    a = await make_department(f"{tag} Alpha", timezone="Europe/London")
    b = await make_department(f"{tag} beta", timezone="Asia/Karachi", is_active=False)
    c = await make_department(f"{tag} Gamma", timezone="America/New_York")
    for _ in range(2):
        await make_doctor(department=c)
    await make_doctor(department=a)

    async def order(**params):
        return [d["name"] for d in (await listed(client, admin, **{"q": tag, **params}))["items"]]

    assert await order(q=tag.upper()) == [f"{tag} Alpha", f"{tag} beta", f"{tag} Gamma"]  # case-insensitive
    assert await order(is_active="false") == [f"{tag} beta"]
    assert await order(is_active="true") == [f"{tag} Alpha", f"{tag} Gamma"]
    assert await order(sort="-name") == [f"{tag} Gamma", f"{tag} beta", f"{tag} Alpha"]
    assert await order(sort="timezone") == [f"{tag} Gamma", f"{tag} beta", f"{tag} Alpha"]
    assert await order(sort="-doctors") == [f"{tag} Gamma", f"{tag} Alpha", f"{tag} beta"]
    assert await order(sort="status") == [f"{tag} Alpha", f"{tag} Gamma", f"{tag} beta"]
    first = await listed(client, admin, q=tag, page_size=2, page=1)
    second = await listed(client, admin, q=tag, page_size=2, page=2)
    assert first["total"] == 3 and first["total_pages"] == 2
    assert {d["id"] for d in first["items"]}.isdisjoint({d["id"] for d in second["items"]})
    assert (await client.get(ADMIN, params={"sort": "secret"}, headers=admin)).status_code == 422


async def test_search_includes_the_description(client, admin, tag):
    await client.post(ADMIN, json={"name": f"{tag} ENT", "description": "Ear, nose and throat"}, headers=admin)
    assert [d["name"] for d in (await listed(client, admin, q="nose and"))["items"]] == [f"{tag} ENT"]


async def test_create_with_icon_colour_and_status(client, admin, tag):
    body = {"name": f"  {tag}   Neurology ", "timezone": "Asia/Karachi", "icon": "brain", "color": "orange", "is_active": False}
    created = await client.post(ADMIN, json=body, headers=admin)
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["name"], body["icon"], body["color"], body["is_active"]) == (f"{tag} Neurology", "brain", "orange", False)

    for bad in ({"icon": "skull"}, {"color": "#ff0000"}, {"timezone": "Mars/Base"}, {"doctor_count": 3}, {"name": "   "}):
        response = await client.post(ADMIN, json={"name": f"{tag} X", **bad}, headers=admin)
        assert response.status_code == 422, bad
    duplicate = await client.post(ADMIN, json={"name": f"{tag} NEUROLOGY"}, headers=admin)
    assert duplicate.status_code == 409


async def test_edit_can_clear_optional_fields_but_not_status(client, admin, make_department, tag):
    department = await make_department(f"{tag} Derm")
    url = f"{ADMIN}{department.id}"
    saved = await client.patch(url, json={"description": "Skin", "icon": "scan-face", "color": "purple", "timezone": "Europe/Paris"}, headers=admin)
    assert saved.status_code == 200 and saved.json()["timezone"] == "Europe/Paris"
    cleared = await client.patch(url, json={"description": None, "icon": None, "name": None}, headers=admin)
    assert cleared.json()["description"] is None and cleared.json()["icon"] is None
    assert cleared.json()["name"] == f"{tag} Derm"  # name cannot be emptied
    assert (await client.patch(url, json={"is_active": False}, headers=admin)).status_code == 422


async def test_detail_lists_every_doctor_and_upcoming_appointments(client, db_session, admin, make_department, make_doctor, make_user, tag):
    department = await make_department(f"{tag} Peds")
    active = await make_doctor(department=department, name="Dr Active")
    await make_doctor(department=department, name="Dr Inactive", is_active=False)
    patient = Patient(first_name="P", last_name="Q", date_of_birth=date(2015, 1, 1))
    booker = await make_user(RoleCode.receptionist)
    db_session.add(patient)
    await db_session.flush()
    start = clock.utcnow() + timedelta(days=2)
    db_session.add(
        Appointment(patient_id=patient.id, doctor_id=active.id, starts_at=start, ends_at=start + timedelta(minutes=30),
                    status=AppointmentStatus.scheduled, booked_by_user_id=booker.id)
    )
    await db_session.commit()
    appointment_id = (await db_session.execute(Appointment.__table__.select().where(Appointment.patient_id == patient.id))).first().id

    detail = (await client.get(f"{ADMIN}{department.id}", headers=admin)).json()
    assert detail["doctor_count"] == 1
    assert [(d["name"], d["is_active"]) for d in detail["doctors"]] == [("Dr Active", True), ("Dr Inactive", False)]
    assert detail["upcoming_appointments"] == 1

    # Deactivating keeps the appointment exactly as it was...
    assert (await client.post(f"{ADMIN}{department.id}/deactivate", headers=admin)).status_code == 200
    kept = await db_session.get(Appointment, appointment_id)
    await db_session.refresh(kept)
    assert kept.status == AppointmentStatus.scheduled
    # ...but the doctor takes no new bookings, and no one can be moved in.
    with pytest.raises(NotFoundError) as err:
        await availability_service.bookable_doctor(db_session, active.id)
    assert err.value.code == "DOCTOR_UNAVAILABLE"
    other = await make_doctor()
    moved = await client.patch(f"/api/v1/doctors/{other.id}", json={"department_id": str(department.id)}, headers=admin)
    assert moved.json()["error"]["code"] == "DEPARTMENT_INACTIVE"
    # Reactivating restores bookings.
    assert (await client.post(f"{ADMIN}{department.id}/activate", headers=admin)).status_code == 200
    assert (await availability_service.bookable_doctor(db_session, active.id)).doctor.id == active.id


async def test_moving_a_doctor_updates_both_counts(client, admin, make_department, make_doctor, tag):
    source = await make_department(f"{tag} Source")
    target = await make_department(f"{tag} Target")
    doctor = await make_doctor(department=source)
    moved = await client.patch(f"/api/v1/doctors/{doctor.id}", json={"department_id": str(target.id)}, headers=admin)
    assert moved.status_code == 200, moved.text
    counts = {d["name"]: d["doctor_count"] for d in (await listed(client, admin, q=tag))["items"]}
    assert counts == {f"{tag} Source": 0, f"{tag} Target": 1}


@pytest.mark.parametrize("role", [RoleCode.patient, RoleCode.doctor, RoleCode.receptionist])
async def test_department_management_is_admin_only(client, auth_headers, make_department, role):
    department = await make_department()
    headers = await auth_headers(role)
    assert (await client.get(ADMIN, headers=headers)).status_code == 403
    assert (await client.get(f"{ADMIN}{department.id}", headers=headers)).status_code == 403
    assert (await client.post(ADMIN, json={"name": "X"}, headers=headers)).status_code == 403
    assert (await client.post(f"{ADMIN}{department.id}/deactivate", headers=headers)).status_code == 403


async def test_unauthenticated_is_401(client):
    assert (await client.get(ADMIN)).status_code == 401


async def test_summary_counts_clinic_wide_and_ignores_page_filters(client, admin, make_department, make_doctor):
    before = (await client.get(f"{ADMIN}summary", headers=admin)).json()
    open_dept = await make_department()
    await make_department(is_active=False)
    await make_doctor(department=open_dept)
    await make_doctor(department=open_dept, is_active=False)  # not practising: not counted
    after = (await client.get(f"{ADMIN}summary", headers=admin, params={"q": "anything", "is_active": "false"})).json()
    assert after["total"] - before["total"] == 2
    assert after["active"] - before["active"] == 1
    assert after["inactive"] - before["inactive"] == 1
    assert after["doctors"] - before["doctors"] == 1
    assert after["total"] == after["active"] + after["inactive"]


async def test_summary_is_admin_only(client, auth_headers):
    for role in (RoleCode.patient, RoleCode.receptionist, RoleCode.doctor):
        assert (await client.get(f"{ADMIN}summary", headers=await auth_headers(role))).status_code == 403


# ---- public / patient cards (D94) ------------------------------------------------------

PUBLIC = "/api/v1/public/departments/"


async def test_public_cards_count_only_listed_doctors_with_minimal_fields(client, db_session, make_department, make_doctor, make_user, tag):
    from app.models import DoctorApplication

    department = await make_department(f"{tag} Pediatrics")
    for name in ("Dr C", "Dr A", "Dr B", "Dr D"):
        await make_doctor(department=department, name=name, license_number=f"L-{tag}-{name[-1]}", phone="0300 0000000")
    await make_doctor(department=department, name="Dr Off", is_active=False)
    locked = await make_doctor(department=department, name="Dr Locked")
    user = await db_session.get(User, locked.user_id)
    user.is_active = False
    applicant = await make_user(RoleCode.doctor_applicant)
    db_session.add(DoctorApplication(user_id=applicant.id, department_id=department.id, specialization="Pediatrician",
                                     submitted_at=clock.utcnow()))
    await db_session.commit()
    await make_department(f"{tag} Retired", is_active=False)

    body = (await client.get(PUBLIC, params={"q": tag})).json()
    assert [d["name"] for d in body["items"]] == [f"{tag} Pediatrics"]  # inactive department hidden
    card = body["items"][0]
    assert card["doctor_count"] == 4  # not the inactive, locked-out or applicant
    assert [d["name"] for d in card["doctors_preview"]] == ["Dr A", "Dr B", "Dr C"]
    assert set(card["doctors_preview"][0]) == {"id", "name", "title", "photo_url"}  # no license, phone or email
    text = str(body)
    assert "L-" + tag not in text and "0300" not in text


async def test_public_card_search_matches_description_without_a_session(client, admin, tag):
    created = await client.post(ADMIN, json={"name": f"{tag} ENT", "description": "Ear, nose and throat"}, headers=admin)
    assert created.status_code == 201
    found = await client.get(PUBLIC, params={"q": "NOSE AND"})  # no session: visitors and patients alike
    assert [d["name"] for d in found.json()["items"]] == [f"{tag} ENT"]
    assert (await client.get(PUBLIC, params={"q": "zz-no-such-department"})).json()["items"] == []


async def test_patients_cannot_reach_department_management(client, auth_headers, make_department):
    department = await make_department()
    patient = await auth_headers(RoleCode.patient)
    assert (await client.get(ADMIN, headers=patient)).status_code == 403
    assert (await client.post(ADMIN, json={"name": "Hack"}, headers=patient)).status_code == 403
    assert (await client.patch(f"{ADMIN}{department.id}", json={"name": "Hack"}, headers=patient)).status_code == 403
    assert (await client.post(f"{ADMIN}{department.id}/deactivate", headers=patient)).status_code == 403
    assert (await client.get(f"{ADMIN}summary", headers=patient)).status_code == 403
