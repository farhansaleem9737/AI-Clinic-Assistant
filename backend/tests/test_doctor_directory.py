"""The public doctors directory: search, filters, sorting, pagination,
availability status and the profile."""

from datetime import datetime, time, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event

from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor import Doctor
from app.models.schedule import ExceptionKind, ScheduleException, ScheduleTemplate

PUBLIC = "/api/v1/public/doctors/"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture
async def directory(make_department, make_doctor):
    """Six doctors across three departments, all tagged "Dir" so other
    fixtures' doctors never leak into the assertions."""
    cardio = await make_department("Dir Cardiology")
    neuro = await make_department("Dir Neurology")
    peds = await make_department("Dir Pediatrics")
    specs = [
        ("Dir Sarah Khan", cardio, "Cardiologist", 10, "150.00"),
        ("Dir James Lee", cardio, "Interventional Cardiologist", 8, "120.00"),
        ("Dir Emily Carter", neuro, "Neurologist", 6, "130.00"),
        ("Dir Michael Brown", neuro, "Neurologist", 12, "160.00"),
        ("Dir Ayesha Malik", peds, "Pediatrician", 7, "110.00"),
        ("Dir Robert Wilson", peds, "Pediatrician", 15, None),
    ]
    doctors = {}
    for name, department, specialization, years, fee in specs:
        doctors[name.removeprefix("Dir ")] = await make_doctor(
            name=name,
            department=department,
            specialization=specialization,
            years_of_experience=years,
            consultation_fee=Decimal(fee) if fee else None,
        )
    return {"cardio": cardio, "neuro": neuro, "peds": peds, **doctors}


async def names(client, **params) -> list[str]:
    response = await client.get(PUBLIC, params={"q": "Dir", "page_size": 50, **params})
    assert response.status_code == 200, response.text
    return [d["name"].removeprefix("Dir ") for d in response.json()["items"]]


# ---- search ---------------------------------------------------------------------------


async def test_search_matches_name_specialization_or_department(client, directory):
    assert await names(client, q="sarah") == ["Sarah Khan"]
    assert await names(client, q="NEUROLOG") == ["Emily Carter", "Michael Brown"]  # specialization, any case
    assert await names(client, q="dir pediatrics") == ["Ayesha Malik", "Robert Wilson"]  # department name
    assert await names(client, q="cardiolog") == ["James Lee", "Sarah Khan"]  # partial match


async def test_empty_or_blank_search_returns_everyone(client, directory):
    everyone = await client.get(PUBLIC, params={"page_size": 50})
    blank = await client.get(PUBLIC, params={"q": "   ", "page_size": 50})
    assert everyone.json()["total"] == blank.json()["total"] >= 6


async def test_search_with_no_match_is_an_empty_page_not_an_error(client, directory):
    response = await client.get(PUBLIC, params={"q": "zzz-no-such-doctor"})
    assert response.status_code == 200
    assert response.json()["items"] == [] and response.json()["total"] == 0 and response.json()["total_pages"] == 0


# ---- filters --------------------------------------------------------------------------


async def test_each_filter(client, directory):
    assert await names(client, department_id=str(directory["neuro"].id)) == ["Emily Carter", "Michael Brown"]
    assert await names(client, specialization="Pediatrician") == ["Ayesha Malik", "Robert Wilson"]
    assert await names(client, min_experience=10) == ["Michael Brown", "Robert Wilson", "Sarah Khan"]
    assert await names(client, fee_max="129.99") == ["Ayesha Malik", "James Lee"]
    assert await names(client, fee_min="150") == ["Michael Brown", "Sarah Khan"]


async def test_filters_combine(client, directory):
    assert await names(client, q="cardiolog", department_id=str(directory["cardio"].id), min_experience=9) == ["Sarah Khan"]
    assert await names(
        client, specialization="Neurologist", min_experience=5, fee_min="125", fee_max="159.99"
    ) == ["Emily Carter"]
    assert await names(client, department_id=str(directory["peds"].id), min_experience=20) == []


# ---- sorting --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("name_asc", ["Ayesha Malik", "Emily Carter", "James Lee", "Michael Brown", "Robert Wilson", "Sarah Khan"]),
        ("name_desc", ["Sarah Khan", "Robert Wilson", "Michael Brown", "James Lee", "Emily Carter", "Ayesha Malik"]),
        ("experience_asc", ["Emily Carter", "Ayesha Malik", "James Lee", "Sarah Khan", "Michael Brown", "Robert Wilson"]),
        ("experience_desc", ["Robert Wilson", "Michael Brown", "Sarah Khan", "James Lee", "Ayesha Malik", "Emily Carter"]),
        # A doctor with no listed fee goes last in both directions.
        ("fee_asc", ["Ayesha Malik", "James Lee", "Emily Carter", "Sarah Khan", "Michael Brown", "Robert Wilson"]),
        ("fee_desc", ["Michael Brown", "Sarah Khan", "Emily Carter", "James Lee", "Ayesha Malik", "Robert Wilson"]),
    ],
)
async def test_sorting_happens_in_the_database(client, directory, sort, expected):
    assert await names(client, sort=sort) == expected


async def test_unknown_sort_is_422(client):
    assert (await client.get(PUBLIC, params={"sort": "random"})).status_code == 422


# ---- pagination -----------------------------------------------------------------------


async def test_pagination_reports_totals_and_keeps_filter_and_sort(client, directory):
    seen = []
    for page in (1, 2, 3):
        response = await client.get(PUBLIC, params={"q": "Dir", "sort": "experience_desc", "page": page, "page_size": 2})
        body = response.json()
        assert (body["total"], body["total_pages"], body["page"], body["page_size"]) == (6, 3, page, 2)
        seen += [d["name"].removeprefix("Dir ") for d in body["items"]]
    assert seen == ["Robert Wilson", "Michael Brown", "Sarah Khan", "James Lee", "Ayesha Malik", "Emily Carter"]

    beyond = await client.get(PUBLIC, params={"q": "Dir", "page": 9, "page_size": 2})
    assert beyond.status_code == 200 and beyond.json()["items"] == []


async def test_page_size_limits(client):
    assert (await client.get(PUBLIC, params={"page_size": 0})).status_code == 422
    assert (await client.get(PUBLIC, params={"page_size": 101})).status_code == 422
    assert (await client.get(PUBLIC, params={"page": 0})).status_code == 422


# ---- filter options -------------------------------------------------------------------


async def test_specialization_options_come_from_listed_doctors(client, directory, make_doctor):
    await make_doctor(name="Dir Hidden", specialization="Dir Retired Specialty", is_active=False)
    options = (await client.get(f"{PUBLIC}specializations")).json()
    assert options == sorted(options)
    assert {"Cardiologist", "Interventional Cardiologist", "Neurologist", "Pediatrician"} <= set(options)
    assert options.count("Neurologist") == 1  # distinct
    assert "Dir Retired Specialty" not in options


# ---- profile --------------------------------------------------------------------------


async def test_profile_shows_public_fields_and_never_the_license_number(client, make_doctor):
    doctor = await make_doctor(
        name="Dir Profiled",
        title="Dr.",
        license_number="PMC-SECRET-123",
        qualifications="MBBS, FCPS (Cardiology)",
        bio="Interested in preventive cardiology.",
        phone="555-0100",
        room_number="B-12",
    )
    response = await client.get(f"{PUBLIC}{doctor.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["is_verified"] is True
    assert body["qualifications"] == "MBBS, FCPS (Cardiology)"
    assert body["bio"] == "Interested in preventive cardiology."
    assert set(body["availability"]) == {"status", "next_available"}
    for private in ("license_number", "phone", "room_number", "email", "user_id"):
        assert private not in body
    assert "PMC-SECRET-123" not in response.text and "555-0100" not in response.text


async def test_doctor_without_a_license_on_file_is_not_verified(client, make_doctor):
    doctor = await make_doctor(name="Dir Unverified")
    assert (await client.get(f"{PUBLIC}{doctor.id}")).json()["is_verified"] is False


async def test_unknown_or_malformed_doctor_id(client):
    assert (await client.get(f"{PUBLIC}00000000-0000-0000-0000-000000000000")).status_code == 404
    assert (await client.get(f"{PUBLIC}not-a-uuid")).status_code == 422


# ---- availability status --------------------------------------------------------------


async def _status(client, doctor_id) -> dict:
    return (await client.get(f"{PUBLIC}{doctor_id}")).json()["availability"]


async def test_doctor_with_free_slots_is_available_and_matches_the_slot_list(client, clinic):
    availability = await _status(client, clinic.doctor_a.id)
    assert availability["status"] == "available"

    # The badge and the bookable slots come from the same computation.
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    day = availability["next_available"][:10]
    slots = await client.get(
        f"/api/v1/doctors/{clinic.doctor_a.id}/availability",
        params={"date_from": day, "date_to": (clinic.today + timedelta(days=8)).isoformat()},
        headers=headers,
    )
    assert slots.json()["slots"][0]["starts_at"] == availability["next_available"]


async def test_doctor_without_a_schedule_is_unavailable_and_cannot_be_booked(client, clinic, make_doctor):
    doctor = await make_doctor(name="Dir No Schedule")
    assert await _status(client, doctor.id) == {"status": "unavailable", "next_available": None}

    headers = await clinic.headers_for(clinic.patient_a.user_id)
    booking = await client.post(
        "/api/v1/appointments/", json={"doctor_id": str(doctor.id), "starts_at": iso(clinic.slot())}, headers=headers
    )
    assert booking.status_code == 409
    assert booking.json()["error"]["code"] == "SLOT_UNAVAILABLE"


async def test_doctor_on_leave_for_the_whole_window_is_unavailable(client, db_session, clinic):
    db_session.add(
        ScheduleException(
            doctor_id=clinic.doctor_b.id,
            kind=ExceptionKind.leave,
            starts_at=clinic.slot(0, "00:00") - timedelta(days=1),
            ends_at=clinic.slot(30, "00:00"),
        )
    )
    await db_session.commit()
    assert (await _status(client, clinic.doctor_b.id))["status"] == "unavailable"
    assert (await _status(client, clinic.doctor_a.id))["status"] == "available"


async def test_fully_booked_doctor_is_busy(client, db_session, clinic, make_doctor):
    """One 30-minute working slot in the coming week, and it is taken."""
    doctor = await make_doctor(name="Dir Fully Booked", department=clinic.department)
    day = clinic.today + timedelta(days=3)
    db_session.add(
        ScheduleTemplate(
            doctor_id=doctor.id, weekday=day.weekday(), start_time=time(10, 0), end_time=time(10, 30),
            slot_minutes=30, valid_from=clinic.today,
        )
    )
    await db_session.commit()
    assert (await _status(client, doctor.id))["status"] == "available"

    db_session.add(
        Appointment(
            patient_id=clinic.walk_in.id, doctor_id=doctor.id, starts_at=clinic.slot(3, "10:00"),
            ends_at=clinic.slot(3, "10:30"), status=AppointmentStatus.scheduled,
            booked_by_user_id=clinic.receptionist.id,
        )
    )
    await db_session.commit()
    assert await _status(client, doctor.id) == {"status": "busy", "next_available": None}


async def test_cancelled_appointments_do_not_make_a_doctor_busy(client, db_session, clinic, make_doctor):
    doctor = await make_doctor(name="Dir Freed Up", department=clinic.department)
    day = clinic.today + timedelta(days=3)
    db_session.add_all([
        ScheduleTemplate(
            doctor_id=doctor.id, weekday=day.weekday(), start_time=time(10, 0), end_time=time(10, 30),
            slot_minutes=30, valid_from=clinic.today,
        ),
        Appointment(
            patient_id=clinic.walk_in.id, doctor_id=doctor.id, starts_at=clinic.slot(3, "10:00"),
            ends_at=clinic.slot(3, "10:30"), status=AppointmentStatus.cancelled, cancellation_reason="other",
            booked_by_user_id=clinic.receptionist.id,
        ),
    ])
    await db_session.commit()
    assert (await _status(client, doctor.id))["status"] == "available"


async def test_listing_carries_each_doctors_status(client, clinic, make_doctor):
    await make_doctor(name="Dir Idle", department=clinic.department)
    response = await client.get(PUBLIC, params={"department_id": str(clinic.department.id), "page_size": 50})
    statuses = {d["name"]: d["availability"]["status"] for d in response.json()["items"]}
    assert statuses == {"Doctor Alpha": "available", "Doctor Beta": "available", "Dir Idle": "unavailable"}


async def test_availability_is_computed_in_a_fixed_number_of_queries(client, db_session, directory):
    """Listing six doctors must not run more queries than listing two."""
    statements = []

    def count(conn, cursor, statement, *args):
        statements.append(statement)

    sync_connection = (await db_session.connection()).sync_connection
    event.listen(sync_connection, "before_cursor_execute", count)
    try:
        await client.get(PUBLIC, params={"q": "Dir", "page_size": 2})
        small = len(statements)
        statements.clear()
        await client.get(PUBLIC, params={"q": "Dir", "page_size": 6})
        large = len(statements)
    finally:
        event.remove(sync_connection, "before_cursor_execute", count)
    assert small == large
    assert large <= 8, statements


# ---- staff view ------------------------------------------------------------------------


async def test_staff_listing_supports_the_same_search_and_sort(client, auth_headers, directory, db_session):
    from app.core.permissions import RoleCode

    (await db_session.get(Doctor, directory["Emily Carter"].id)).is_active = False
    await db_session.commit()
    admin = await auth_headers(RoleCode.admin)

    response = await client.get(
        "/api/v1/doctors/", params={"q": "neurolog", "sort": "experience_desc", "page_size": 50}, headers=admin
    )
    listed = [(d["name"].removeprefix("Dir "), d["is_active"]) for d in response.json()["items"]]
    assert listed == [("Michael Brown", True), ("Emily Carter", False)]
    # …while the public directory no longer lists the deactivated doctor.
    assert await names(client, q="neurolog") == ["Michael Brown"]
