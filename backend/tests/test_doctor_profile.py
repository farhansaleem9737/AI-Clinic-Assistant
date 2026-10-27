"""The public doctor profile page: career history, the public booking
calendar, and the booking it hands over to."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.department import Department
from app.models.doctor import Doctor, DoctorEducation, DoctorExperience
from app.models.schedule import ExceptionKind, ScheduleException
from app.models.user import User

PUBLIC = "/api/v1/public/doctors/"
APPOINTMENTS = "/api/v1/appointments/"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def calendar(client, doctor_id, date_from: date, date_to: date):
    return await client.get(
        f"{PUBLIC}{doctor_id}/availability",
        params={"date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )


async def days(client, doctor_id, date_from: date, date_to: date) -> dict[str, list[str]]:
    response = await calendar(client, doctor_id, date_from, date_to)
    assert response.status_code == 200, response.text
    return {d["date"]: [s["starts_at"] for s in d["slots"]] for d in response.json()["days"]}


# ---- career history ------------------------------------------------------------------


async def test_profile_lists_experience_and_education_newest_first(client, db_session, make_doctor):
    doctor = await make_doctor(name="Profile Khan", specialization="Cardiologist")
    db_session.add_all([
        DoctorExperience(doctor_id=doctor.id, title="Consultant Cardiologist", organization="HealthCare Medical Center",
                         location="Lahore", start_year=2016, end_year=2020, description="Outpatient cardiology."),
        DoctorExperience(doctor_id=doctor.id, title="Senior Cardiologist", organization="City General Hospital",
                         location="Lahore", start_year=2020, end_year=None),
        DoctorExperience(doctor_id=doctor.id, title="Registrar", organization="Teaching Hospital",
                         start_year=2014, end_year=2016),
        DoctorEducation(doctor_id=doctor.id, qualification="MBBS", institution="King Edward Medical University",
                        start_year=2006, end_year=2011),
        DoctorEducation(doctor_id=doctor.id, qualification="FCPS", field_of_study="Cardiology",
                        institution="College of Physicians and Surgeons Pakistan", start_year=2012, end_year=2014),
    ])
    await db_session.commit()

    body = (await client.get(f"{PUBLIC}{doctor.id}")).json()
    assert [(e["title"], e["end_year"]) for e in body["experience"]] == [
        ("Senior Cardiologist", None),  # current position first
        ("Consultant Cardiologist", 2020),
        ("Registrar", 2016),
    ]
    assert body["experience"][1] == {
        "title": "Consultant Cardiologist", "organization": "HealthCare Medical Center", "location": "Lahore",
        "start_year": 2016, "end_year": 2020, "description": "Outpatient cardiology.",
    }
    assert [(e["qualification"], e["field_of_study"]) for e in body["education"]] == [("FCPS", "Cardiology"), ("MBBS", None)]
    # No internal identifiers in the history entries.
    assert set(body["education"][0]) == {"qualification", "institution", "field_of_study", "start_year", "end_year"}


async def test_profile_without_history_has_empty_lists(client, make_doctor):
    doctor = await make_doctor(name="Profile Bare")
    body = (await client.get(f"{PUBLIC}{doctor.id}")).json()
    assert body["experience"] == [] and body["education"] == []


async def test_listing_does_not_carry_history(client, make_doctor):
    await make_doctor(name="Profile Listed")
    item = (await client.get(PUBLIC, params={"q": "Profile Listed"})).json()["items"][0]
    assert "experience" not in item and "education" not in item


async def test_database_rejects_impossible_years(db_session, make_doctor):
    doctor = await make_doctor(name="Profile Years")
    db_session.add(DoctorExperience(doctor_id=doctor.id, title="X", organization="Y", start_year=2020, end_year=2019))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
    db_session.add(DoctorEducation(doctor_id=doctor.id, qualification="X", institution="Y", start_year=1800))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ---- who is public -------------------------------------------------------------------


@pytest.mark.parametrize("hidden_by", ["doctor", "login", "department"])
async def test_hidden_doctors_have_no_profile_or_calendar(client, db_session, clinic, make_doctor, hidden_by):
    doctor = await make_doctor(name=f"Profile Hidden {hidden_by}", department=clinic.department)
    if hidden_by == "doctor":
        (await db_session.get(Doctor, doctor.id)).is_active = False
    elif hidden_by == "login":
        (await db_session.get(User, doctor.user_id)).is_active = False
    else:
        department = await db_session.get(Department, doctor.department_id)
        department.is_active = False
    await db_session.commit()

    assert (await client.get(f"{PUBLIC}{doctor.id}")).status_code == 404
    response = await calendar(client, doctor.id, clinic.today, clinic.today + timedelta(days=6))
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Doctor not found"


async def test_a_doctor_whose_login_is_disabled_cannot_be_booked(client, db_session, clinic):
    (await db_session.get(User, clinic.doctor_b.user_id)).is_active = False
    await db_session.commit()
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    response = await client.post(
        APPOINTMENTS, json={"doctor_id": str(clinic.doctor_b.id), "starts_at": iso(clinic.slot())}, headers=headers
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCTOR_UNAVAILABLE"


# ---- the public calendar -------------------------------------------------------------


async def test_calendar_needs_no_login_and_groups_slots_by_local_date(client, clinic):
    start = clinic.today + timedelta(days=2)
    response = await calendar(client, clinic.doctor_a.id, start, start + timedelta(days=1))
    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "Asia/Karachi"
    assert [d["date"] for d in body["days"]] == [start.isoformat(), (start + timedelta(days=1)).isoformat()]
    first_day = body["days"][0]["slots"]
    # 09:00-17:00 local in 30-minute slots, returned as UTC instants.
    assert len(first_day) == 16
    assert first_day[0] == {"starts_at": iso(clinic.slot(2, "09:00")), "ends_at": iso(clinic.slot(2, "09:30"))}
    assert first_day[-1]["starts_at"] == iso(clinic.slot(2, "16:30"))


async def test_calendar_matches_what_a_signed_in_patient_sees(client, clinic):
    start, end = clinic.today, clinic.today + timedelta(days=6)
    public = [s for slots in (await days(client, clinic.doctor_a.id, start, end)).values() for s in slots]
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    private = await client.get(
        f"/api/v1/doctors/{clinic.doctor_a.id}/availability",
        params={"date_from": start.isoformat(), "date_to": end.isoformat()},
        headers=headers,
    )
    assert public == [s["starts_at"] for s in private.json()["slots"]]


async def test_calendar_hides_past_times_and_respects_the_booking_notice(client, clinic, freeze_clock):
    # Pretend it is 12:10 local today: 12:30 is inside the patient notice
    # period (60 minutes), 13:30 is the first bookable time.
    now = clinic.slot(0, "12:10")
    freeze_clock(now)
    today = (await days(client, clinic.doctor_a.id, clinic.today, clinic.today))[clinic.today.isoformat()]
    assert today[0] == iso(clinic.slot(0, "13:30"))
    assert all(s > iso(now) for s in today)

    yesterday = clinic.today - timedelta(days=1)
    assert await days(client, clinic.doctor_a.id, yesterday, yesterday) == {}


async def test_calendar_leaves_out_booked_times_and_leave(client, db_session, clinic):
    headers = await clinic.headers_for(clinic.patient_b.user_id)
    booked = await client.post(
        APPOINTMENTS, json={"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot(3, "10:00"))}, headers=headers
    )
    assert booked.status_code == 201
    db_session.add(ScheduleException(
        doctor_id=clinic.doctor_a.id, kind=ExceptionKind.leave,
        starts_at=clinic.slot(4, "00:00"), ends_at=clinic.slot(5, "00:00"),
    ))
    await db_session.commit()

    result = await days(client, clinic.doctor_a.id, clinic.today + timedelta(days=3), clinic.today + timedelta(days=5))
    day3, day4, day5 = (clinic.today + timedelta(days=n) for n in (3, 4, 5))
    assert iso(clinic.slot(3, "10:00")) not in result[day3.isoformat()]
    assert iso(clinic.slot(3, "10:30")) in result[day3.isoformat()]
    assert day4.isoformat() not in result  # on leave: no entry at all
    assert len(result[day5.isoformat()]) == 16
    # Nothing about the booking itself is returned.
    response = await calendar(client, clinic.doctor_a.id, day3, day3)
    assert "patient" not in response.text and str(clinic.patient_b.id) not in response.text
    # The taken time is listed as unavailable (greyed out), never as free.
    [entry] = response.json()["days"]
    assert [s["starts_at"] for s in entry["unavailable"]] == [iso(clinic.slot(3, "10:00"))]


async def test_calendar_greys_out_times_inside_the_booking_notice(client, clinic, freeze_clock):
    freeze_clock(clinic.slot(0, "12:00"))  # one hour's notice: 13:00 is the first bookable time today
    response = await calendar(client, clinic.doctor_a.id, clinic.today, clinic.today)
    [today] = response.json()["days"]
    assert today["slots"][0]["starts_at"] == iso(clinic.slot(0, "13:00"))
    unavailable = [s["starts_at"] for s in today["unavailable"]]
    assert iso(clinic.slot(0, "09:00")) in unavailable and iso(clinic.slot(0, "12:30")) in unavailable
    assert iso(clinic.slot(0, "13:00")) not in unavailable


async def test_calendar_stops_at_the_booking_horizon(client, clinic):
    body = (await calendar(client, clinic.doctor_a.id, clinic.today, clinic.today)).json()
    horizon = date.fromisoformat(body["bookable_until"])
    assert horizon == clinic.today + timedelta(days=settings.booking_max_advance_days)

    beyond = await days(client, clinic.doctor_a.id, horizon + timedelta(days=1), horizon + timedelta(days=10))
    assert beyond == {}


async def test_doctor_without_hours_has_an_empty_calendar(client, clinic, make_doctor):
    doctor = await make_doctor(name="Profile No Hours", department=clinic.department)
    assert await days(client, doctor.id, clinic.today, clinic.today + timedelta(days=30)) == {}


@pytest.mark.parametrize(
    ("offset_from", "offset_to", "code"),
    [(5, 4, "INVALID_RANGE"), (0, 31, "RANGE_TOO_LARGE")],
)
async def test_calendar_range_is_validated(client, clinic, offset_from, offset_to, code):
    response = await calendar(
        client, clinic.doctor_a.id, clinic.today + timedelta(days=offset_from), clinic.today + timedelta(days=offset_to)
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == code


async def test_calendar_rejects_malformed_input(client, clinic):
    assert (await client.get(f"{PUBLIC}{clinic.doctor_a.id}/availability")).status_code == 422
    bad_date = await client.get(
        f"{PUBLIC}{clinic.doctor_a.id}/availability", params={"date_from": "2026-02-30", "date_to": "2026-03-01"}
    )
    assert bad_date.status_code == 422
    assert (await client.get(f"{PUBLIC}not-a-uuid/availability")).status_code == 422


# ---- from the calendar to a booking --------------------------------------------------


async def test_a_slot_from_the_calendar_books_once_and_then_disappears(client, clinic):
    day = clinic.today + timedelta(days=2)
    chosen = (await days(client, clinic.doctor_a.id, day, day))[day.isoformat()][3]

    alice = await clinic.headers_for(clinic.patient_a.user_id)
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    body = {"doctor_id": str(clinic.doctor_a.id), "starts_at": chosen}

    # Both patients saw the slot as free; only the first booking gets it.
    first = await client.post(APPOINTMENTS, json=body, headers=alice)
    assert first.status_code == 201
    assert first.json()["status"] in {"requested", "scheduled"}
    stale = await client.post(APPOINTMENTS, json=body, headers=bob)
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "SLOT_UNAVAILABLE"

    assert chosen not in (await days(client, clinic.doctor_a.id, day, day))[day.isoformat()]


async def test_booking_still_requires_a_signed_in_patient(client, clinic):
    body = {"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot())}
    assert (await client.post(APPOINTMENTS, json=body)).status_code == 401

    doctor = await clinic.headers_for(clinic.doctor_b.user_id)
    assert (await client.post(APPOINTMENTS, json=body, headers=doctor)).status_code == 403

    # A patient cannot name someone else as the patient.
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    other = await client.post(APPOINTMENTS, json={**body, "patient_id": str(clinic.patient_b.id)}, headers=alice)
    assert other.status_code == 404


async def test_times_not_offered_by_the_calendar_cannot_be_booked(client, clinic, freeze_clock):
    freeze_clock(clinic.slot(0, "12:10"))
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    for when in (clinic.slot(0, "11:00"), clinic.slot(0, "12:30"), clinic.slot(2, "10:10"), clinic.slot(2, "20:00")):
        response = await client.post(
            APPOINTMENTS, json={"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(when)}, headers=alice
        )
        assert response.status_code == 409, when
        assert response.json()["error"]["code"] == "SLOT_UNAVAILABLE"



# ---- career history management ---------------------------------------------------------

CAREER = {
    "experience": [
        {"title": "Resident", "organization": "  Teaching Hospital ", "start_year": 2014, "end_year": 2016},
        {"title": "Senior Cardiologist", "organization": "City General", "location": "Lahore", "start_year": 2020},
        {"title": "Consultant", "organization": "Heart Centre", "start_year": 2016, "end_year": 2020, "description": ""},
    ],
    "education": [
        {"qualification": "MBBS", "institution": "King Edward Medical University", "end_year": 2011},
        {"qualification": "FCPS", "field_of_study": "Cardiology", "institution": "CPSP", "start_year": 2012, "end_year": 2014},
    ],
}


async def test_doctor_replaces_own_career_and_the_profile_shows_it_newest_first(client, db_session, make_doctor):
    from tests.conftest import login_as

    doctor = await make_doctor(name="Career Owner")
    headers = await login_as(client, db_session, doctor.user_id)
    saved = await client.put("/api/v1/doctors/me/career", json=CAREER, headers=headers)
    assert saved.status_code == 200, saved.text
    assert [e["title"] for e in saved.json()["experience"]] == ["Senior Cardiologist", "Consultant", "Resident"]
    assert saved.json()["experience"][2]["organization"] == "Teaching Hospital"  # trimmed
    assert saved.json()["experience"][1]["description"] is None  # blank -> none

    public = (await client.get(f"{PUBLIC}{doctor.id}")).json()
    assert [e["qualification"] for e in public["education"]] == ["FCPS", "MBBS"]
    assert (await client.get("/api/v1/doctors/me/career", headers=headers)).json() == saved.json()

    # Replacing again removes what is no longer listed.
    cleared = await client.put("/api/v1/doctors/me/career", json={"experience": [], "education": []}, headers=headers)
    assert cleared.json() == {"experience": [], "education": []}


@pytest.mark.parametrize(
    "bad",
    [
        {"experience": [{"title": "X", "organization": "Y", "start_year": 2020, "end_year": 2019}]},
        {"experience": [{"title": " ", "organization": "Y", "start_year": 2020}]},
        {"experience": [{"title": "X", "organization": "Y", "start_year": 1900}]},
        {"education": [{"qualification": "MBBS", "institution": "Z", "start_year": 2011, "end_year": 2006}]},
    ],
)
async def test_invalid_career_entries_are_422(client, db_session, make_doctor, bad):
    from tests.conftest import login_as

    doctor = await make_doctor(name="Career Invalid")
    headers = await login_as(client, db_session, doctor.user_id)
    assert (await client.put("/api/v1/doctors/me/career", json=bad, headers=headers)).status_code == 422


async def test_only_the_doctor_or_staff_with_doctor_update_can_edit_a_career(client, auth_headers, make_doctor, db_session):
    from app.core.permissions import RoleCode
    from tests.conftest import login_as

    owner = await make_doctor(name="Career Target")
    other = await make_doctor(name="Career Other")
    url = f"/api/v1/doctors/{owner.id}/career"
    other_headers = await login_as(client, db_session, other.user_id)
    assert (await client.put(url, json=CAREER, headers=other_headers)).status_code == 403
    assert (await client.put(url, json=CAREER, headers=await auth_headers(RoleCode.patient))).status_code == 403
    assert (await client.put(url, json=CAREER)).status_code == 401
    assert (await client.put("/api/v1/doctors/me/career", json=CAREER, headers=await auth_headers(RoleCode.patient))).status_code == 403

    admin = await client.put(url, json=CAREER, headers=await auth_headers(RoleCode.admin))
    assert admin.status_code == 200 and len(admin.json()["experience"]) == 3
