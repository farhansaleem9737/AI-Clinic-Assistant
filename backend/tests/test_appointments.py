import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core.permissions import RoleCode
from app.models.appointment import Appointment, AppointmentStatus, AppointmentStatusHistory

BASE = "/api/v1/appointments/"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture
async def as_(clinic):
    """Headers for the clinic's cast, cached per test."""
    cache = {}

    async def _as(who: str):
        if who not in cache:
            user_id = {
                "alice": clinic.patient_a.user_id,
                "bob": clinic.patient_b.user_id,
                "dr_a": clinic.doctor_a.user_id,
                "dr_b": clinic.doctor_b.user_id,
                "reception": clinic.receptionist.id,
                "admin": clinic.admin.id,
            }[who]
            cache[who] = await clinic.headers_for(user_id)
        return cache[who]

    return _as


@pytest.fixture
def book(client, clinic, as_):
    async def _book(who="alice", *, doctor=None, when=None, patient=None, reason=None, key=None):
        body = {"doctor_id": str((doctor or clinic.doctor_a).id), "starts_at": iso(when or clinic.slot())}
        if patient is not None:
            body["patient_id"] = str(patient.id)
        if reason:
            body["reason"] = reason
        headers = dict(await as_(who))
        if key:
            headers["Idempotency-Key"] = key
        return await client.post(BASE, json=body, headers=headers)

    return _book


async def status(client, headers, appointment_id, to, **extra):
    return await client.post(f"{BASE}{appointment_id}/status", json={"status": to, **extra}, headers=headers)


# ============================== creation ==============================================


async def test_patient_books_own_appointment(client, clinic, book, as_):
    response = await book("alice", reason="Chest pain when climbing stairs")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["patient"]["id"] == str(clinic.patient_a.id)
    assert body["doctor"]["name"] == "Doctor Alpha"
    assert body["ends_at"] == iso(clinic.slot() + timedelta(minutes=30))
    assert "staff_notes" not in body  # patient view
    assert set(body["allowed_transitions"]) == {"confirmed", "cancelled"}
    assert body["can_reschedule"] is True

    history = await client.get(f"{BASE}{body['id']}/history", headers=await as_("alice"))
    assert [(h["from_status"], h["to_status"]) for h in history.json()] == [
        (None, "requested"),
        ("requested", "scheduled"),
    ]


async def test_receptionist_books_for_walk_in_patient(client, clinic, book):
    response = await book("reception", patient=clinic.walk_in)
    assert response.status_code == 201
    assert response.json()["patient"]["id"] == str(clinic.walk_in.id)
    assert "staff_notes" in response.json()  # staff view


async def test_staff_must_name_the_patient(book):
    response = await book("reception")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "PATIENT_REQUIRED"


async def test_patient_cannot_book_for_someone_else(clinic, book):
    response = await book("alice", patient=clinic.patient_b)
    assert response.status_code == 404


async def test_doctors_cannot_book(clinic, book):
    assert (await book("dr_a", patient=clinic.walk_in)).status_code == 403


async def test_unknown_or_inactive_doctor(client, clinic, as_, make_doctor):
    headers = await as_("alice")
    unknown = await client.post(BASE, json={"doctor_id": str(uuid.uuid4()), "starts_at": iso(clinic.slot())}, headers=headers)
    assert unknown.status_code == 404
    inactive = await make_doctor(is_active=False)
    response = await client.post(BASE, json={"doctor_id": str(inactive.id), "starts_at": iso(clinic.slot())}, headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCTOR_UNAVAILABLE"


async def test_inactive_patient_cannot_be_booked(clinic, book, make_patient):
    inactive = await make_patient(is_active=False)
    response = await book("reception", patient=inactive)
    assert response.json()["error"]["code"] == "PATIENT_INACTIVE"


async def test_times_outside_the_schedule_are_rejected(clinic, book):
    assert (await book("alice", when=clinic.slot(3, "03:00"))).json()["error"]["code"] == "SLOT_UNAVAILABLE"
    assert (await book("alice", when=clinic.slot(3, "10:10"))).json()["error"]["code"] == "SLOT_UNAVAILABLE"
    assert (await book("alice", when=clinic.slot(200, "10:00"))).json()["error"]["code"] == "SLOT_UNAVAILABLE"


async def test_naive_or_malformed_input_is_422(client, clinic, as_):
    headers = await as_("alice")
    naive = {"doctor_id": str(clinic.doctor_a.id), "starts_at": "2026-12-01T10:00:00"}
    assert (await client.post(BASE, json=naive, headers=headers)).status_code == 422
    assert (await client.post(BASE, json={"doctor_id": "not-a-uuid"}, headers=headers)).status_code == 422


async def test_a_taken_slot_cannot_be_booked_again(clinic, book):
    assert (await book("alice")).status_code == 201
    second = await book("bob")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "SLOT_UNAVAILABLE"


async def test_patient_cannot_be_in_two_places_at_once(clinic, book):
    assert (await book("reception", patient=clinic.walk_in, doctor=clinic.doctor_a)).status_code == 201
    clash = await book("reception", patient=clinic.walk_in, doctor=clinic.doctor_b)
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "PATIENT_DOUBLE_BOOKED"


async def test_patients_need_notice_but_staff_can_book_soon(client, clinic, as_, book, freeze_clock):
    """Freeze time 30 minutes before the slot: inside the patient lead time."""
    freeze_clock(clinic.slot() - timedelta(minutes=30))
    too_soon = await book("alice")
    assert too_soon.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    assert (await book("reception", patient=clinic.patient_a)).status_code == 201


async def test_idempotency_key_prevents_double_submission(clinic, book):
    first = await book("alice", key="booking-123")
    again = await book("alice", key="booking-123")
    assert first.status_code == 201 and again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert again.headers["Idempotent-Replayed"] == "true"

    reused = await book("alice", key="booking-123", when=clinic.slot(3, "11:00"))
    assert reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_database_rejects_overlap_even_without_the_service(db_session, clinic):
    """The EXCLUDE constraint is the real guarantee, not the service's pre-check."""
    common = dict(
        doctor_id=clinic.doctor_a.id,
        starts_at=clinic.slot(),
        ends_at=clinic.slot() + timedelta(minutes=30),
        status=AppointmentStatus.scheduled,
        booked_by_user_id=clinic.receptionist.id,
    )
    db_session.add(Appointment(patient_id=clinic.patient_a.id, **common))
    await db_session.flush()
    overlapping = dict(common, starts_at=clinic.slot() + timedelta(minutes=15), ends_at=clinic.slot() + timedelta(minutes=45))
    db_session.add(Appointment(patient_id=clinic.patient_b.id, **overlapping))
    with pytest.raises(IntegrityError, match="ex_appointments_doctor_overlap"):
        await db_session.flush()
    await db_session.rollback()


# ============================== authorization =========================================


async def test_anonymous_requests_are_401(client, clinic):
    assert (await client.get(BASE)).status_code == 401
    body = {"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot())}
    assert (await client.post(BASE, json=body)).status_code == 401


async def test_patient_a_cannot_reach_patient_b_appointment_by_id(client, clinic, book, as_):
    bobs = (await book("bob")).json()["id"]
    alice = await as_("alice")
    assert (await client.get(f"{BASE}{bobs}", headers=alice)).status_code == 404
    assert (await client.get(f"{BASE}{bobs}/history", headers=alice)).status_code == 404
    assert (await status(client, alice, bobs, "cancelled", cancellation_reason="patient_request")).status_code == 404
    moved = await client.post(f"{BASE}{bobs}/reschedule", json={"starts_at": iso(clinic.slot(3, "11:00"))}, headers=alice)
    assert moved.status_code == 404
    assert (await client.patch(f"{BASE}{bobs}", json={"reason": "x"}, headers=alice)).status_code == 403
    listed = await client.get(BASE, headers=alice)
    assert all(a["patient"]["id"] == str(clinic.patient_a.id) for a in listed.json()["items"])


async def test_doctor_sees_only_own_appointments(client, clinic, book, as_):
    with_a = (await book("alice", doctor=clinic.doctor_a)).json()["id"]
    with_b = (await book("bob", doctor=clinic.doctor_b)).json()["id"]
    dr_a = await as_("dr_a")
    assert (await client.get(f"{BASE}{with_a}", headers=dr_a)).status_code == 200
    assert (await client.get(f"{BASE}{with_b}", headers=dr_a)).status_code == 404
    listed = await client.get(BASE, headers=dr_a)
    assert [a["id"] for a in listed.json()["items"]] == [with_a]
    # Asking for the other doctor's list by filter changes nothing.
    other = await client.get(BASE, params={"doctor_id": str(clinic.doctor_b.id)}, headers=dr_a)
    assert other.json()["total"] == 0


async def test_doctor_can_read_patients_they_have_appointments_with(client, clinic, book, as_):
    await book("alice", doctor=clinic.doctor_a)
    dr_a, dr_b = await as_("dr_a"), await as_("dr_b")
    assert (await client.get(f"/api/v1/patients/{clinic.patient_a.id}", headers=dr_a)).status_code == 200
    assert (await client.get(f"/api/v1/patients/{clinic.patient_a.id}", headers=dr_b)).status_code == 404


async def test_staff_notes_are_hidden_from_patients(client, clinic, book, as_):
    appointment = (await book("alice")).json()["id"]
    reception = await as_("reception")
    await client.patch(f"{BASE}{appointment}", json={"staff_notes": "Needs wheelchair access"}, headers=reception)
    assert (await client.get(f"{BASE}{appointment}", headers=await as_("dr_a"))).json()["staff_notes"] == "Needs wheelchair access"
    patient_view = await client.get(f"{BASE}{appointment}", headers=await as_("alice"))
    assert "Needs wheelchair access" not in patient_view.text


# ============================== detail page ===========================================


async def test_detail_carries_patient_profile_and_doctor_facts(client, clinic, book, db_session, make_patient):
    from app.models.doctor import Doctor

    patient = await make_patient(
        first_name="Dana", last_name="Lee", with_account=True, sex_at_birth="female",
        phone="+92 300 1234567", email="dana@example.com", address="12 Mall Road",
    )
    await db_session.execute(update(Doctor).where(Doctor.id == clinic.doctor_a.id).values(license_number="PMC-123"))
    await db_session.commit()
    created = (await book("reception", patient=patient)).json()["id"]

    body = (await client.get(f"{BASE}{created}", headers=await clinic.headers_for(patient.user_id))).json()
    assert body["patient"]["name"] == "Dana Lee"
    assert body["patient_profile"] == {
        "sex_at_birth": "female",
        "phone": "+92 300 1234567",
        "email": "dana@example.com",
        "address": "12 Mall Road",
    }
    assert body["doctor"]["years_of_experience"] == 5
    assert body["doctor"]["is_verified"] is True
    assert "PMC-123" not in str(body)  # the licence itself is never sent
    assert "staff_notes" not in body  # still the patient view


async def test_lists_and_mutations_keep_the_lighter_shape(client, clinic, book, as_):
    appointment = (await book("alice")).json()
    assert "patient_profile" not in appointment
    assert appointment["doctor"]["is_verified"] is False
    listed = (await client.get(BASE, headers=await as_("alice"))).json()["items"]
    assert listed and all("patient_profile" not in a for a in listed)
    changed = await status(client, await as_("alice"), appointment["id"], "confirmed")
    assert "patient_profile" not in changed.json()


async def test_staff_and_doctor_detail_include_profile_and_notes(client, clinic, book, as_):
    appointment = (await book("alice")).json()["id"]
    for who in ("reception", "dr_a"):
        body = (await client.get(f"{BASE}{appointment}", headers=await as_(who))).json()
        assert body["patient_profile"]["sex_at_birth"] == "unknown"
        assert "staff_notes" in body


async def test_appointment_access_alone_does_not_reveal_the_patient_profile(client, clinic, book, make_role, make_user):
    """A custom role that can read appointments but not patients sees the
    booking, never the patient's contact details."""
    from tests.conftest import login

    appointment = (await book("alice")).json()["id"]
    await make_role("appointment_viewer", ["appointment:read_any"])
    viewer = await make_user("appointment_viewer")
    body = (await client.get(f"{BASE}{appointment}", headers=await login(client, viewer.email))).json()
    assert body["id"] == appointment
    assert body["patient_profile"] is None


async def test_unknown_appointment_is_404(client, clinic, as_):
    for who in ("alice", "reception"):
        response = await client.get(f"{BASE}{uuid.uuid4()}", headers=await as_(who))
        assert response.status_code == 404
    assert (await client.get(f"{BASE}not-a-uuid", headers=await as_("alice"))).status_code == 422


async def test_role_without_appointment_permissions_is_403(client, make_role, make_user, clinic):
    from tests.conftest import login

    await make_role("auditor", ["user:read"])
    auditor = await make_user("auditor")
    headers = await login(client, auditor.email)
    assert (await client.get(BASE, headers=headers)).status_code == 403


# ============================== lifecycle =============================================


async def test_full_visit_lifecycle(client, clinic, book, as_, freeze_clock):
    appointment = (await book("alice")).json()["id"]

    assert (await status(client, await as_("alice"), appointment, "confirmed")).json()["status"] == "confirmed"

    freeze_clock(clinic.slot() - timedelta(minutes=20))  # patient arrives on the day
    checked_in = await status(client, await as_("reception"), appointment, "checked_in")
    assert checked_in.json()["status"] == "checked_in"

    freeze_clock(clinic.slot() + timedelta(minutes=2))
    started = await status(client, await as_("dr_a"), appointment, "in_progress")
    assert started.json()["status"] == "in_progress"
    done = await status(client, await as_("dr_a"), appointment, "completed", note="Follow up in 3 months")
    assert done.json()["status"] == "completed"
    assert done.json()["allowed_transitions"] == []

    history = (await client.get(f"{BASE}{appointment}/history", headers=await as_("alice"))).json()
    assert [h["to_status"] for h in history] == [
        "requested", "scheduled", "confirmed", "checked_in", "in_progress", "completed",
    ]


async def test_invalid_transitions_are_409(client, clinic, book, as_):
    appointment = (await book("alice")).json()["id"]
    reception = await as_("reception")
    skip = await status(client, await as_("dr_a"), appointment, "completed")
    assert skip.status_code == 409
    assert skip.json()["error"]["code"] == "INVALID_TRANSITION"

    await status(client, reception, appointment, "cancelled", cancellation_reason="clinic_decision")
    revive = await status(client, reception, appointment, "confirmed")
    assert revive.status_code == 409


async def test_roles_may_only_make_their_own_transitions(client, clinic, book, as_, freeze_clock):
    appointment = (await book("alice")).json()["id"]
    freeze_clock(clinic.slot() - timedelta(minutes=20))
    # A patient cannot check themselves in; reception cannot start a consultation.
    assert (await status(client, await as_("alice"), appointment, "checked_in")).status_code == 403
    await status(client, await as_("reception"), appointment, "checked_in")
    assert (await status(client, await as_("reception"), appointment, "in_progress")).status_code == 403
    # Another doctor cannot even see it.
    assert (await status(client, await as_("dr_b"), appointment, "in_progress")).status_code == 404


async def test_check_in_only_on_the_day(client, clinic, book, as_):
    appointment = (await book("alice")).json()["id"]
    response = await status(client, await as_("reception"), appointment, "checked_in")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_APPOINTMENT_DAY"


async def test_no_show_only_after_grace_period(client, clinic, book, as_, freeze_clock):
    appointment = (await book("alice")).json()["id"]
    reception = await as_("reception")
    freeze_clock(clinic.slot() + timedelta(minutes=5))
    early = await status(client, reception, appointment, "no_show")
    assert early.json()["error"]["code"] == "TOO_EARLY_FOR_NO_SHOW"
    freeze_clock(clinic.slot() + timedelta(minutes=20))
    assert (await status(client, reception, appointment, "no_show")).json()["status"] == "no_show"


async def test_cancellation_needs_a_reason_and_frees_the_slot(client, clinic, book, as_):
    appointment = (await book("alice")).json()["id"]
    alice = await as_("alice")
    assert (await status(client, alice, appointment, "cancelled")).status_code == 422

    cancelled = await status(client, alice, appointment, "cancelled", cancellation_reason="patient_request", note="Feeling better")
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancellation_reason"] == "patient_request"
    # Bob can now take the slot.
    assert (await book("bob")).status_code == 201


async def test_patient_cutoff_applies_to_patients_not_staff(client, clinic, book, as_, freeze_clock):
    appointment = (await book("alice")).json()["id"]
    freeze_clock(clinic.slot() - timedelta(minutes=60))  # cutoff is 120 minutes
    late = await status(client, await as_("alice"), appointment, "cancelled", cancellation_reason="patient_request")
    assert late.json()["error"]["code"] == "PAST_PATIENT_CUTOFF"
    by_staff = await status(client, await as_("reception"), appointment, "cancelled", cancellation_reason="patient_request")
    assert by_staff.json()["status"] == "cancelled"


async def test_doctor_can_cancel_own_appointment(client, clinic, book, as_):
    appointment = (await book("alice")).json()["id"]
    response = await status(client, await as_("dr_a"), appointment, "cancelled", cancellation_reason="doctor_unavailable")
    assert response.json()["status"] == "cancelled"


async def test_cancelling_twice_is_rejected_and_the_first_cancellation_stands(client, clinic, book, as_):
    appointment = (await book("alice")).json()["id"]
    alice = await as_("alice")
    first = await status(client, alice, appointment, "cancelled", cancellation_reason="patient_request", note="Travelling")
    assert first.status_code == 200
    again = await status(client, alice, appointment, "cancelled", cancellation_reason="other")
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "INVALID_TRANSITION"
    current = (await client.get(f"{BASE}{appointment}", headers=alice)).json()
    assert current["cancellation_reason"] == "patient_request"
    assert current["cancellation_note"] == "Travelling"
    assert current["allowed_transitions"] == [] and current["can_reschedule"] is False


async def test_another_patient_cannot_cancel_or_reschedule(client, clinic, book, as_):
    mine = (await book("alice")).json()["id"]
    bob = await as_("bob")
    assert (await status(client, bob, mine, "cancelled", cancellation_reason="patient_request")).status_code == 404
    moved = await client.post(f"{BASE}{mine}/reschedule", json={"starts_at": iso(clinic.slot(4, "11:00"))}, headers=bob)
    assert moved.status_code == 404
    assert (await client.get(f"{BASE}{mine}", headers=await as_("alice"))).json()["status"] == "scheduled"


async def test_cannot_cancel_via_status_with_rescheduled_reason(client, clinic, book, as_):
    appointment = (await book("alice")).json()["id"]
    response = await status(client, await as_("alice"), appointment, "cancelled", cancellation_reason="rescheduled")
    assert response.status_code == 422


# ============================== reschedule ============================================


async def test_reschedule_cancels_old_and_links_new(client, clinic, book, as_):
    old = (await book("alice", reason="Check-up")).json()["id"]
    alice = await as_("alice")
    moved = await client.post(f"{BASE}{old}/reschedule", json={"starts_at": iso(clinic.slot(4, "11:00"))}, headers=alice)
    assert moved.status_code == 201, moved.text
    new = moved.json()
    assert new["status"] == "scheduled"
    assert new["rescheduled_from_id"] == old
    assert new["reason"] == "Check-up"

    previous = (await client.get(f"{BASE}{old}", headers=alice)).json()
    assert previous["status"] == "cancelled"
    assert previous["cancellation_reason"] == "rescheduled"
    assert previous["rescheduled_to_id"] == new["id"]
    # The original slot is free again.
    assert (await book("bob")).status_code == 201


async def test_reschedule_into_a_taken_slot_is_refused(client, clinic, book, as_):
    await book("bob", when=clinic.slot(3, "11:00"))
    mine = (await book("alice")).json()["id"]
    response = await client.post(
        f"{BASE}{mine}/reschedule", json={"starts_at": iso(clinic.slot(3, "11:00"))}, headers=await as_("alice")
    )
    assert response.status_code == 409
    # Nothing changed.
    assert (await client.get(f"{BASE}{mine}", headers=await as_("alice"))).json()["status"] == "scheduled"


async def test_reschedule_to_another_doctor_by_staff(client, clinic, book, as_):
    mine = (await book("alice")).json()["id"]
    response = await client.post(
        f"{BASE}{mine}/reschedule",
        json={"starts_at": iso(clinic.slot()), "doctor_id": str(clinic.doctor_b.id)},
        headers=await as_("reception"),
    )
    assert response.status_code == 201
    assert response.json()["doctor"]["id"] == str(clinic.doctor_b.id)


async def test_reschedule_outside_the_doctors_hours_is_refused(client, clinic, book, as_):
    mine = (await book("alice")).json()["id"]
    alice = await as_("alice")
    for when in (clinic.slot(3, "03:00"), clinic.slot(3, "10:10"), clinic.slot(-1, "10:00")):
        response = await client.post(f"{BASE}{mine}/reschedule", json={"starts_at": iso(when)}, headers=alice)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    assert (await client.get(f"{BASE}{mine}", headers=alice)).json()["status"] == "scheduled"


async def test_finished_appointments_cannot_be_rescheduled(client, clinic, book, as_, freeze_clock):
    appointment = (await book("alice")).json()["id"]
    freeze_clock(clinic.slot() + timedelta(minutes=20))
    await status(client, await as_("reception"), appointment, "no_show")
    response = await client.post(
        f"{BASE}{appointment}/reschedule", json={"starts_at": iso(clinic.slot(5))}, headers=await as_("reception")
    )
    assert response.status_code == 409


# ============================== filtering & pagination ================================


async def test_filters_and_pagination_run_in_sql(client, clinic, book, as_):
    reception = await as_("reception")
    a1 = (await book("alice", when=clinic.slot(3, "09:00"))).json()["id"]
    a2 = (await book("alice", when=clinic.slot(5, "09:00"), doctor=clinic.doctor_b)).json()["id"]
    b1 = (await book("bob", when=clinic.slot(4, "09:00"))).json()["id"]
    await status(client, reception, b1, "cancelled", cancellation_reason="clinic_decision")

    async def ids(**params):
        response = await client.get(BASE, params=params, headers=reception)
        assert response.status_code == 200, response.text
        return [a["id"] for a in response.json()["items"]]

    assert await ids(doctor_id=str(clinic.doctor_a.id)) == [a1, b1]
    assert await ids(patient_id=str(clinic.patient_a.id)) == [a1, a2]
    assert await ids(status="cancelled") == [b1]
    assert await ids(status=["scheduled", "confirmed"]) == [a1, a2]
    day4 = (clinic.today + timedelta(days=4)).isoformat()
    day5 = (clinic.today + timedelta(days=5)).isoformat()
    assert await ids(date_from=day4, date_to=day5) == [b1, a2]
    assert await ids(department_id=str(clinic.department.id), newest_first=True) == [a2, b1, a1]

    page = await client.get(BASE, params={"page_size": 2, "page": 2}, headers=reception)
    assert page.json()["total"] == 3 and [a["id"] for a in page.json()["items"]] == [a2]


async def test_list_rejects_invalid_filters(client, clinic, as_):
    reception = await as_("reception")
    assert (await client.get(BASE, params={"status": "rescheduled"}, headers=reception)).status_code == 422
    assert (await client.get(BASE, params={"page_size": 500}, headers=reception)).status_code == 422


# ============================== related guards ========================================


async def test_doctor_with_upcoming_appointments_cannot_be_deactivated(client, clinic, book, as_):
    await book("alice")
    response = await client.post(f"/api/v1/doctors/{clinic.doctor_a.id}/deactivate", headers=await as_("admin"))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "HAS_UPCOMING_APPOINTMENTS"


async def test_history_is_append_only_per_transition(db_session, client, clinic, book, as_):
    appointment = (await book("alice")).json()["id"]
    await status(client, await as_("alice"), appointment, "confirmed")
    rows = (await db_session.scalars(
        select(AppointmentStatusHistory).where(AppointmentStatusHistory.appointment_id == uuid.UUID(appointment))
    )).all()
    assert len(rows) == 3
    assert rows[-1].changed_by_user_id == clinic.patient_a.user_id
