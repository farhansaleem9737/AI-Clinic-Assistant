"""Reception booking on behalf of a patient (D82): the directory's today
hours and availability, and what the final booking checks."""

from datetime import datetime, time

from app.core.permissions import RoleCode
from app.models.schedule import ExceptionKind, ScheduleException
from tests.conftest import login

BOOK = "/api/v1/appointments/"
PUBLIC = "/api/v1/public/doctors/"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def availability(client, doctor_id):
    response = await client.get(f"{PUBLIC}{doctor_id}")
    assert response.status_code == 200, response.text
    return response.json()["availability"]


async def test_today_hours_come_from_the_schedule(client, clinic, freeze_clock):
    freeze_clock(clinic.slot(0, "08:00"))
    body = await availability(client, clinic.doctor_a.id)
    assert body["today_hours"] == [{"start_time": "09:00:00", "end_time": "17:00:00"}]
    assert body["available_today"] is True


async def test_today_hours_follow_a_custom_hours_exception(client, db_session, clinic, freeze_clock):
    today = clinic.today
    db_session.add(
        ScheduleException(
            doctor_id=clinic.doctor_a.id,
            kind=ExceptionKind.custom_hours,
            starts_at=datetime.combine(today, time(10), tzinfo=clinic.tz),
            ends_at=datetime.combine(today, time(12), tzinfo=clinic.tz),
        )
    )
    await db_session.commit()
    freeze_clock(clinic.slot(0, "08:00"))
    body = await availability(client, clinic.doctor_a.id)
    assert body["today_hours"] == [{"start_time": "10:00:00", "end_time": "12:00:00"}]


async def test_a_doctor_with_no_schedule_has_no_hours(client, make_doctor):
    doctor = await make_doctor(name="Doctor Unscheduled")
    body = await availability(client, doctor.id)
    assert body["today_hours"] == [] and body["status"] == "unavailable" and body["next_available"] is None


async def test_after_hours_today_points_to_the_next_free_day(client, clinic, freeze_clock):
    freeze_clock(clinic.slot(0, "18:00"))
    body = await availability(client, clinic.doctor_a.id)
    assert body["available_today"] is False
    assert body["today_hours"] == [{"start_time": "09:00:00", "end_time": "17:00:00"}]
    assert datetime.fromisoformat(body["next_available"]) == clinic.slot(1, "09:00")


async def test_reception_books_for_the_chosen_patient_and_is_recorded_as_the_actor(client, clinic):
    reception = await clinic.headers_for(clinic.receptionist.id)
    response = await client.post(
        BOOK,
        json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.walk_in.id), "starts_at": iso(clinic.slot(2, "10:00"))},
        headers=reception,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["patient"]["id"] == str(clinic.walk_in.id)
    assert body["booked_by_user_id"] == str(clinic.receptionist.id)
    # The doctor sees it too.
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    listed = (await client.get(BOOK, params={"patient_id": str(clinic.walk_in.id)}, headers=dr_a)).json()
    assert [a["id"] for a in listed["items"]] == [body["id"]]


async def test_reception_must_name_an_existing_active_patient(client, clinic, db_session):
    from app.models.patient import Patient

    reception = await clinic.headers_for(clinic.receptionist.id)
    body = {"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot(2, "10:00"))}
    missing = await client.post(BOOK, json=body, headers=reception)
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "PATIENT_REQUIRED"
    unknown = await client.post(BOOK, json={**body, "patient_id": "00000000-0000-0000-0000-000000000000"}, headers=reception)
    assert unknown.status_code == 404

    patient = await db_session.get(Patient, clinic.walk_in.id)
    patient.is_active = False
    await db_session.commit()
    inactive = await client.post(BOOK, json={**body, "patient_id": str(clinic.walk_in.id)}, headers=reception)
    assert inactive.status_code == 400 and inactive.json()["error"]["code"] == "PATIENT_INACTIVE"


async def test_booking_permission_alone_does_not_reach_patients(client, clinic, make_role, make_user, db_session):
    """A role that may book but not see patients cannot book for one."""
    from app.services import rbac_service

    await make_role("booker_only", ["appointment:create", "availability:read"])
    user = await make_user(role=None)
    await rbac_service.grant_roles(db_session, user.id, ["booker_only"])
    await db_session.commit()
    headers = await login(client, user.email)
    response = await client.post(
        BOOK,
        json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.walk_in.id), "starts_at": iso(clinic.slot(2, "10:00"))},
        headers=headers,
    )
    assert response.status_code == 404


async def test_the_same_slot_cannot_be_booked_twice(client, clinic):
    reception = await clinic.headers_for(clinic.receptionist.id)
    slot = iso(clinic.slot(2, "11:00"))
    first = await client.post(
        BOOK, json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.walk_in.id), "starts_at": slot}, headers=reception
    )
    assert first.status_code == 201
    second = await client.post(
        BOOK, json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_b.id), "starts_at": slot}, headers=reception
    )
    assert second.status_code == 409


async def test_patients_cannot_book_for_someone_else(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    response = await client.post(
        BOOK,
        json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_b.id), "starts_at": iso(clinic.slot(2, "12:00"))},
        headers=alice,
    )
    assert response.status_code == 404


async def test_reception_role_is_seeded_with_booking_but_not_doctor_permissions(client, auth_headers):
    me = (await client.get("/api/v1/auth/me", headers=await auth_headers(RoleCode.receptionist))).json()
    assert {"appointment:create", "patient:read_any"} <= set(me["permissions"])
    assert not {"appointment:consult", "doctor:update_own", "schedule:manage_own"} & set(me["permissions"])
