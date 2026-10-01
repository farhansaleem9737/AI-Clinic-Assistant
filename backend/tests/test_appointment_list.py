"""The appointment list behind the patient's Appointments page: upcoming /
past / all tabs and their counts, search, status and date filters, paging,
and who can see what."""

from datetime import datetime, timedelta

import pytest

from app.models.user import User

BASE = "/api/v1/appointments/"
COUNTS = "/api/v1/appointments/counts"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def book(client, headers, doctor, when):
    response = await client.post(BASE, json={"doctor_id": str(doctor.id), "starts_at": iso(when)}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
async def scene(client, db_session, clinic, make_doctor):
    from datetime import time

    from app.models.schedule import ScheduleTemplate

    cardio = await make_doctor(name="Doctor Gamma", department=clinic.department, specialization="Cardiologist")
    for weekday in range(7):
        db_session.add(ScheduleTemplate(
            doctor_id=cardio.id, weekday=weekday, start_time=time(9, 0), end_time=time(17, 0),
            slot_minutes=30, valid_from=clinic.today - timedelta(days=1),
        ))
    await db_session.commit()

    alice = await clinic.headers_for(clinic.patient_a.user_id)
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    cancelled = await book(client, alice, clinic.doctor_a, clinic.slot(2, "10:00"))
    a3 = await book(client, alice, clinic.doctor_a, clinic.slot(3, "10:00"))
    a4 = await book(client, alice, clinic.doctor_b, clinic.slot(4, "11:00"))
    a5 = await book(client, alice, cardio, clinic.slot(5, "12:00"))
    b1 = await book(client, bob, clinic.doctor_a, clinic.slot(3, "15:00"))
    response = await client.post(
        f"{BASE}{cancelled}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"}, headers=alice
    )
    assert response.status_code == 200
    return {"alice": alice, "bob": bob, "cancelled": cancelled, "a3": a3, "a4": a4, "a5": a5, "b1": b1}


async def ids(client, headers, **params) -> list[str]:
    response = await client.get(BASE, params={"page_size": 50, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return [a["id"] for a in response.json()["items"]]


async def counts(client, headers, **params) -> dict:
    response = await client.get(COUNTS, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---- tabs and counts ------------------------------------------------------------------


async def test_tabs_split_upcoming_and_past(client, scene):
    alice = scene["alice"]
    assert await ids(client, alice, scope="upcoming") == [scene["a3"], scene["a4"], scene["a5"]]
    # A cancelled appointment is no longer upcoming, even though its date is ahead.
    assert await ids(client, alice, scope="past") == [scene["cancelled"]]
    assert set(await ids(client, alice, scope="all")) == {scene["cancelled"], scene["a3"], scene["a4"], scene["a5"]}
    assert await counts(client, alice) == {"upcoming": 3, "past": 1, "all": 4}


async def test_finished_appointments_move_to_past(client, clinic, scene, freeze_clock):
    freeze_clock(clinic.slot(3, "10:45"))  # the day +3 visit (10:00-10:30) is over
    alice = scene["alice"]
    assert await ids(client, alice, scope="upcoming") == [scene["a4"], scene["a5"]]
    assert scene["a3"] in await ids(client, alice, scope="past")
    assert await counts(client, alice) == {"upcoming": 2, "past": 2, "all": 4}


async def test_counts_match_the_dashboard(client, scene):
    alice = scene["alice"]
    summary = (await client.get("/api/v1/dashboard/summary", headers=alice)).json()["patient"]
    tabs = await counts(client, alice)
    assert tabs["upcoming"] == summary["upcoming_appointments"]
    assert tabs["all"] == summary["total_appointments"]


async def test_counts_follow_the_filters_but_not_the_scope(client, clinic, scene):
    alice = scene["alice"]
    assert await counts(client, alice, q="gamma") == {"upcoming": 1, "past": 0, "all": 1}
    assert await counts(client, alice, q="gamma", scope="past") == {"upcoming": 1, "past": 0, "all": 1}
    day3 = (clinic.today + timedelta(days=3)).isoformat()
    assert await counts(client, alice, date_from=day3, date_to=day3) == {"upcoming": 1, "past": 0, "all": 1}
    assert await counts(client, alice, status="cancelled") == {"upcoming": 0, "past": 1, "all": 1}


# ---- search and filters -----------------------------------------------------------------


async def test_search_matches_doctor_name_specialization_or_department(client, clinic, scene):
    alice = scene["alice"]
    assert await ids(client, alice, q="beta") == [scene["a4"]]  # doctor name
    assert await ids(client, alice, q="CARDIOLOG") == [scene["a5"]]  # specialization, any case
    department = clinic.department.name[:8]
    assert len(await ids(client, alice, q=department)) == 4  # department name
    assert await ids(client, alice, q="nobody-matches") == []
    assert len(await ids(client, alice, q="   ")) == 4  # blank search is no search


async def test_status_and_date_filters_combine_with_the_tab(client, clinic, scene):
    alice = scene["alice"]
    assert await ids(client, alice, status="cancelled") == [scene["cancelled"]]
    assert await ids(client, alice, status=["scheduled", "confirmed"], scope="past") == []
    day4 = (clinic.today + timedelta(days=4)).isoformat()
    day5 = (clinic.today + timedelta(days=5)).isoformat()
    assert await ids(client, alice, scope="upcoming", date_from=day4, date_to=day5) == [scene["a4"], scene["a5"]]
    assert await ids(client, alice, scope="all", newest_first="true") == [
        scene["a5"], scene["a4"], scene["a3"], scene["cancelled"]
    ]


async def test_invalid_filters_are_rejected(client, clinic, scene):
    alice = scene["alice"]
    later, earlier = (clinic.today + timedelta(days=5)).isoformat(), clinic.today.isoformat()
    for path in (BASE, COUNTS):
        backwards = await client.get(path, params={"date_from": later, "date_to": earlier}, headers=alice)
        assert backwards.status_code == 400
        assert backwards.json()["error"]["code"] == "INVALID_RANGE"
        for bad in ({"status": "teleported"}, {"scope": "someday"}, {"date_from": "2026-02-30"}, {"q": "x" * 101}):
            response = await client.get(path, params=bad, headers=alice)
            assert response.status_code == 422, bad
            assert "error" in response.json()
    for bad in ({"page": 0}, {"page_size": 0}, {"page_size": 101}):
        assert (await client.get(BASE, params=bad, headers=alice)).status_code == 422


async def test_pages_report_totals(client, scene):
    alice = scene["alice"]
    first = (await client.get(BASE, params={"scope": "all", "page_size": 3}, headers=alice)).json()
    second = (await client.get(BASE, params={"scope": "all", "page_size": 3, "page": 2}, headers=alice)).json()
    assert (first["total"], first["total_pages"], len(first["items"])) == (4, 2, 3)
    assert len(second["items"]) == 1
    assert {a["id"] for a in first["items"] + second["items"]} == {
        scene["cancelled"], scene["a3"], scene["a4"], scene["a5"]
    }


# ---- who sees what ----------------------------------------------------------------------


async def test_each_patient_sees_only_their_own(client, clinic, scene):
    assert await ids(client, scene["bob"], scope="all") == [scene["b1"]]
    assert await counts(client, scene["bob"]) == {"upcoming": 1, "past": 0, "all": 1}
    # Naming another patient widens nothing.
    assert await ids(client, scene["alice"], patient_id=str(clinic.patient_b.id)) == []
    assert await counts(client, scene["alice"], patient_id=str(clinic.patient_b.id)) == {"upcoming": 0, "past": 0, "all": 0}
    # Nor does opening another patient's appointment directly.
    response = await client.get(f"{BASE}{scene['b1']}", headers=scene["alice"])
    assert response.status_code == 404


async def test_anonymous_and_inactive_users_get_nothing(client, db_session, clinic, scene):
    assert (await client.get(BASE)).status_code == 401
    assert (await client.get(COUNTS)).status_code == 401
    (await db_session.get(User, clinic.patient_a.user_id)).is_active = False
    await db_session.commit()
    assert (await client.get(COUNTS, headers=scene["alice"])).status_code == 401


async def test_patients_cannot_make_staff_transitions(client, scene):
    response = await client.post(f"{BASE}{scene['a3']}/status", json={"status": "completed"}, headers=scene["alice"])
    assert response.status_code in (403, 409)
    response = await client.post(f"{BASE}{scene['a3']}/status", json={"status": "checked_in"}, headers=scene["alice"])
    assert response.status_code in (403, 409)


async def test_patient_can_cancel_their_own_upcoming_appointment(client, scene):
    response = await client.post(
        f"{BASE}{scene['a4']}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"},
        headers=scene["alice"],
    )
    assert response.status_code == 200
    assert await counts(client, scene["alice"]) == {"upcoming": 2, "past": 2, "all": 4}
    # …but not Bob's.
    response = await client.post(
        f"{BASE}{scene['b1']}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"},
        headers=scene["alice"],
    )
    assert response.status_code == 404


async def test_staff_counts_cover_the_clinic(client, clinic, scene):
    reception = await clinic.headers_for(clinic.receptionist.id)
    assert (await counts(client, reception))["all"] == 5
    doctor_b = await clinic.headers_for(clinic.doctor_b.user_id)
    assert await counts(client, doctor_b) == {"upcoming": 1, "past": 0, "all": 1}

