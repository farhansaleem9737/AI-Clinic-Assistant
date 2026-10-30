"""The doctor's My Appointments page (D79): a day's list plus Today /
Upcoming / Past counts in the doctor's timezone, patient search scoped to the
doctor's own appointments, paging and the state machine's actions."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

BASE = "/api/v1/appointments/"
DAY_COUNTS = "/api/v1/appointments/day-counts"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def book(client, headers, doctor, when, reason=None):
    body = {"doctor_id": str(doctor.id), "starts_at": iso(when)}
    if reason:
        body["reason"] = reason
    response = await client.post(BASE, json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
async def scene(client, clinic, freeze_clock):
    """Dr Alpha: one visit on day+1, three on day+2 (two Alice, one Bob), one
    on day+4. Dr Beta: one on day+2. The clock is then moved to day+2 08:00,
    so "today" is day+2: day+1 is past, day+4 upcoming."""
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    ids = {
        "past": await book(client, alice, clinic.doctor_a, clinic.slot(1, "10:00")),
        "late": await book(client, alice, clinic.doctor_a, clinic.slot(2, "15:00"), reason="Test results review"),
        "early": await book(client, alice, clinic.doctor_a, clinic.slot(2, "09:00"), reason="Chest pain"),
        "bob": await book(client, bob, clinic.doctor_a, clinic.slot(2, "11:00")),
        "future": await book(client, bob, clinic.doctor_a, clinic.slot(4, "10:00")),
        "other_doctor": await book(client, alice, clinic.doctor_b, clinic.slot(2, "10:00")),
    }
    freeze_clock(clinic.slot(2, "08:00"))
    return {
        "ids": ids,
        "alice": alice,
        "dr_a": await clinic.headers_for(clinic.doctor_a.user_id),
        "dr_b": await clinic.headers_for(clinic.doctor_b.user_id),
        "today": clinic.today + timedelta(days=2),
    }


async def listing(client, headers, **params):
    response = await client.get(BASE, params={"page_size": 50, **params}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def day_counts(client, headers, **params):
    response = await client.get(DAY_COUNTS, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_day_counts_split_by_the_doctors_calendar(client, scene):
    body = await day_counts(client, scene["dr_a"])
    assert body["timezone"] == "Asia/Karachi"
    assert body["today"] == body["day"] == scene["today"].isoformat()
    assert (body["on_day"], body["upcoming"], body["past"]) == (3, 1, 1)

    later = await day_counts(client, scene["dr_a"], day=(scene["today"] + timedelta(days=2)).isoformat())
    assert later["on_day"] == 1 and later["today"] == scene["today"].isoformat()
    # Upcoming / past stay relative to today, whatever day is selected.
    assert (later["upcoming"], later["past"]) == (1, 1)


async def test_the_days_list_is_in_time_order_with_patient_details(client, scene, clinic):
    day = scene["today"].isoformat()
    body = await listing(client, scene["dr_a"], date_from=day, date_to=day)
    assert [a["id"] for a in body["items"]] == [scene["ids"]["early"], scene["ids"]["bob"], scene["ids"]["late"]]
    first = body["items"][0]
    assert first["patient"]["name"].startswith("Alice") and first["patient"]["mrn"].startswith("MRN")
    assert first["patient"]["date_of_birth"] == "1990-05-17"
    assert first["patient"]["photo_url"] is None  # no photo, no storage: the page shows initials
    assert first["reason"] == "Chest pain" and first["timezone"] == "Asia/Karachi"


async def test_doctors_only_see_and_count_their_own_appointments(client, scene):
    day = scene["today"].isoformat()
    mine = [a["id"] for a in (await listing(client, scene["dr_a"], date_from=day, date_to=day))["items"]]
    assert scene["ids"]["other_doctor"] not in mine
    theirs = await day_counts(client, scene["dr_b"])
    assert (theirs["on_day"], theirs["upcoming"], theirs["past"]) == (1, 0, 0)
    # The other doctor's appointment is simply not there.
    response = await client.get(f"{BASE}{scene['ids']['other_doctor']}", headers=scene["dr_a"])
    assert response.status_code == 404


async def test_a_patient_counts_only_their_own(client, scene):
    alice = await day_counts(client, scene["alice"])
    # Alice: two on day+2 with Dr Alpha and one with Dr Beta; one past.
    assert (alice["on_day"], alice["upcoming"], alice["past"]) == (3, 0, 1)


async def test_search_finds_patients_by_name_mrn_or_reason(client, scene, clinic):
    dr_a = scene["dr_a"]
    by_name = await listing(client, dr_a, q="bob")
    assert {a["id"] for a in by_name["items"]} == {scene["ids"]["bob"], scene["ids"]["future"]}
    mrn = by_name["items"][0]["patient"]["mrn"]
    assert {a["id"] for a in (await listing(client, dr_a, q=mrn.lower()))["items"]} == {
        scene["ids"]["bob"],
        scene["ids"]["future"],
    }
    assert [a["id"] for a in (await listing(client, dr_a, q="CHEST"))["items"]] == [scene["ids"]["early"]]
    # Counts follow the search.
    counted = await day_counts(client, dr_a, q="bob")
    assert (counted["on_day"], counted["upcoming"], counted["past"]) == (1, 1, 0)


async def test_search_never_reaches_beyond_the_doctors_appointments(client, scene):
    # Alice has an appointment with Dr Beta, but Dr Beta searching "Alice"
    # only finds that one, never Dr Alpha's.
    found = await listing(client, scene["dr_b"], q="Alice")
    assert [a["id"] for a in found["items"]] == [scene["ids"]["other_doctor"]]
    # A patient's search does not look at patient fields: nothing new to find.
    assert (await listing(client, scene["alice"], q="Bob"))["total"] == 0


async def test_status_filter_combines_with_the_day_and_counts(client, scene):
    dr_a = scene["dr_a"]
    cancel = await client.post(
        f"{BASE}{scene['ids']['bob']}/status",
        json={"status": "cancelled", "cancellation_reason": "doctor_unavailable"},
        headers=dr_a,
    )
    assert cancel.status_code == 200, cancel.text
    day = scene["today"].isoformat()
    cancelled = await listing(client, dr_a, date_from=day, date_to=day, status="cancelled")
    assert [a["id"] for a in cancelled["items"]] == [scene["ids"]["bob"]]
    counted = await day_counts(client, dr_a, status=["scheduled", "confirmed"])
    assert counted["on_day"] == 2
    # A cancelled appointment stays on its date with its real status.
    assert (await day_counts(client, dr_a))["on_day"] == 3


async def test_pages_are_stable_and_complete(client, scene):
    day = scene["today"].isoformat()
    first = (await client.get(BASE, params={"date_from": day, "date_to": day, "page_size": 2, "page": 1}, headers=scene["dr_a"])).json()
    second = (await client.get(BASE, params={"date_from": day, "date_to": day, "page_size": 2, "page": 2}, headers=scene["dr_a"])).json()
    assert first["total"] == second["total"] == 3 and first["total_pages"] == 2
    ids = [a["id"] for a in first["items"] + second["items"]]
    assert ids == [scene["ids"]["early"], scene["ids"]["bob"], scene["ids"]["late"]]


async def test_the_doctor_gets_only_actions_the_state_machine_allows(client, scene):
    day = scene["today"].isoformat()
    [early, *_] = (await listing(client, scene["dr_a"], date_from=day, date_to=day))["items"]
    # Scheduled, before the start: a doctor may cancel; confirming and
    # rescheduling belong to the patient or the front desk.
    assert early["status"] == "scheduled"
    assert early["allowed_transitions"] == ["cancelled"] and early["can_reschedule"] is False
    refused = await client.post(f"{BASE}{early['id']}/status", json={"status": "confirmed"}, headers=scene["dr_a"])
    assert refused.status_code == 403
    nonsense = await client.post(f"{BASE}{early['id']}/status", json={"status": "completed"}, headers=scene["dr_a"])
    assert nonsense.status_code == 409 and nonsense.json()["error"]["code"] == "INVALID_TRANSITION"


async def test_a_second_cancellation_is_refused_not_applied_twice(client, scene):
    url = f"{BASE}{scene['ids']['early']}/status"
    body = {"status": "cancelled", "cancellation_reason": "doctor_unavailable"}
    assert (await client.post(url, json=body, headers=scene["dr_a"])).status_code == 200
    again = await client.post(url, json=body, headers=scene["dr_a"])
    assert again.status_code == 409


async def test_dates_use_the_doctors_timezone_not_utc(client, db_session, make_department, make_doctor, make_patient, clinic):
    """Auckland is UTC+12/13: a 09:00 visit there is the previous day in UTC
    and in the clinic's Asia/Karachi timezone."""
    from app.models.schedule import ScheduleTemplate
    from tests.conftest import login_as

    tz = ZoneInfo("Pacific/Auckland")
    department = await make_department(timezone="Pacific/Auckland")
    doctor = await make_doctor(department=department)
    day = datetime.now(tz).date() + timedelta(days=3)
    db_session.add(
        ScheduleTemplate(
            doctor_id=doctor.id, weekday=day.weekday(), start_time=time(9), end_time=time(10),
            slot_minutes=30, valid_from=day - timedelta(days=1),
        )
    )
    await db_session.commit()
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    starts = datetime.combine(day, time(9), tzinfo=tz)
    appointment = await book(client, alice, doctor, starts)
    assert starts.astimezone(ZoneInfo("UTC")).date() != day  # the boundary case

    headers = await login_as(client, db_session, doctor.user_id)
    found = await listing(client, headers, date_from=day.isoformat(), date_to=day.isoformat())
    assert [a["id"] for a in found["items"]] == [appointment]
    counted = await day_counts(client, headers, day=day.isoformat())
    assert counted["timezone"] == "Pacific/Auckland" and counted["on_day"] == 1


async def test_reschedules_move_between_dates(client, scene, clinic):
    """Reception moves Bob's visit: the old date keeps the original (as
    cancelled), the new date shows the new one."""
    reception = await clinic.headers_for(clinic.receptionist.id)
    moved = await client.post(
        f"{BASE}{scene['ids']['bob']}/reschedule", json={"starts_at": iso(clinic.slot(3, "14:00"))}, headers=reception
    )
    assert moved.status_code in (200, 201), moved.text
    tomorrow = (scene["today"] + timedelta(days=1)).isoformat()
    on_new_day = await listing(client, scene["dr_a"], date_from=tomorrow, date_to=tomorrow)
    assert [a["id"] for a in on_new_day["items"]] == [moved.json()["id"]]
    counted = await day_counts(client, scene["dr_a"])
    assert counted["upcoming"] == 2  # day+3 and day+4
