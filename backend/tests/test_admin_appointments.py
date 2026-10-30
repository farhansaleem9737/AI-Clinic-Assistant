"""Admin > Appointments (D92): each appointment keeps the department it was
booked in; the admin list's search, range, filters and sorting; isolation."""

import pytest

from app.core.permissions import RoleCode
from app.models.appointment import Appointment

BASE = "/api/v1/appointments/"


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


async def book(client, clinic, headers, *, doctor=None, when=None, patient=None):
    body = {"doctor_id": str((doctor or clinic.doctor_a).id), "starts_at": iso(when or clinic.slot()),
            "patient_id": str((patient or clinic.walk_in).id)}
    response = await client.post(BASE, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def listed(client, headers, **params):
    response = await client.get(BASE, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_moved_doctor_keeps_past_appointments_in_their_department(client, db_session, clinic, make_department):
    admin = await clinic.headers_for(clinic.admin.id)
    booked = await book(client, clinic, admin)
    stored = await db_session.get(Appointment, booked["id"])
    await db_session.refresh(stored)
    assert stored.department_id == clinic.department.id  # recorded at booking

    new_home = await make_department("Moved Here")
    moved = await client.patch(f"/api/v1/doctors/{clinic.doctor_a.id}", json={"department_id": str(new_home.id)}, headers=admin)
    assert moved.status_code == 200

    old = await listed(client, admin, department_id=str(clinic.department.id))
    assert [a["id"] for a in old["items"]] == [booked["id"]]
    assert old["items"][0]["doctor"]["department_name"] == clinic.department.name
    assert (await listed(client, admin, department_id=str(new_home.id)))["total"] == 0

    later = await book(client, clinic, admin, when=clinic.slot(4, "11:00"))
    assert (await listed(client, admin, department_id=str(new_home.id)))["items"][0]["id"] == later["id"]


async def test_search_range_filters_and_sorting_combine(client, clinic):
    admin = await clinic.headers_for(clinic.admin.id)
    first = await book(client, clinic, admin, when=clinic.slot(3, "09:00"), patient=clinic.walk_in)
    second = await book(client, clinic, admin, doctor=clinic.doctor_b, when=clinic.slot(5, "10:00"), patient=clinic.patient_a)
    day3, day5 = (clinic.today + __import__("datetime").timedelta(days=d) for d in (3, 5))

    by_mrn = await listed(client, admin, q=clinic.walk_in.mrn.lower())
    assert [a["id"] for a in by_mrn["items"]] == [first["id"]]
    by_doctor = await listed(client, admin, q="beta")
    assert [a["id"] for a in by_doctor["items"]] == [second["id"]]

    # Inclusive range in the clinic's timezone: the last day counts.
    ranged = await listed(client, admin, date_from=day3.isoformat(), date_to=day5.isoformat())
    assert {a["id"] for a in ranged["items"]} == {first["id"], second["id"]}
    only_last = await listed(client, admin, date_from=day5.isoformat(), date_to=day5.isoformat())
    assert [a["id"] for a in only_last["items"]] == [second["id"]]
    bad = await client.get(BASE, params={"date_from": day5.isoformat(), "date_to": day3.isoformat()}, headers=admin)
    assert bad.status_code == 400

    combined = await listed(client, admin, doctor_id=str(clinic.doctor_a.id), status=["scheduled"], date_from=day3.isoformat())
    assert [a["id"] for a in combined["items"]] == [first["id"]]
    newest = await listed(client, admin, sort="time_desc")
    assert [a["id"] for a in newest["items"]][:2] == [second["id"], first["id"]]
    paged = await listed(client, admin, page_size=1, page=2, sort="time_asc")
    assert paged["total"] == 2 and paged["items"][0]["id"] == second["id"]


@pytest.mark.parametrize("who", ["patient_b", "doctor_b"])
async def test_patients_and_doctors_see_only_their_own(client, clinic, who):
    admin = await clinic.headers_for(clinic.admin.id)
    await book(client, clinic, admin, patient=clinic.patient_a)  # with doctor_a
    target = getattr(clinic, who)
    user_id = target.user_id
    headers = await clinic.headers_for(user_id)
    assert (await listed(client, headers))["total"] == 0


async def test_unauthenticated_and_unknown_roles_are_refused(client, auth_headers):
    assert (await client.get(BASE)).status_code == 401
    applicant = await auth_headers(RoleCode.doctor_applicant)
    assert (await client.get(BASE, headers=applicant)).status_code == 403
