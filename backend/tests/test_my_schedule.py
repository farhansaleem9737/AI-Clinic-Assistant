"""The doctor's My Schedule page (D78): the week as a whole, single-date
exceptions, their precedence in availability, and protecting booked patients.

The `clinic` fixture's doctors work 09:00-17:00 local (Asia/Karachi) every day
in 30-minute slots.
"""

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.appointment import Appointment
from app.models.schedule import ExceptionKind, ScheduleTemplate
from app.services.availability_service import working_slots
from tests.conftest import login_as


def weekly_url(doctor_id):
    return f"/api/v1/doctors/{doctor_id}/weekly-schedule"


def exceptions_url(doctor_id, exception_id=None):
    base = f"/api/v1/doctors/{doctor_id}/date-exceptions"
    return base if exception_id is None else f"{base}/{exception_id}"


def week(**overrides) -> dict:
    """Every day 09:00-17:00 (the fixture's hours), with per-weekday overrides:
    a list of (start, end) pairs, or [] for a day off."""
    days = []
    for weekday in range(7):
        hours = overrides.get(str(weekday), [("09:00", "17:00")])
        days.append(
            {
                "weekday": weekday,
                "enabled": bool(hours),
                "intervals": [{"start_time": s, "end_time": e} for s, e in hours],
            }
        )
    return {"days": days}


async def local_slots(client, clinic, doctor_id, day: date) -> list[str]:
    """Free slots on `day` as local HH:MM, from the public booking calendar."""
    response = await client.get(
        f"/api/v1/public/doctors/{doctor_id}/availability",
        params={"date_from": day.isoformat(), "date_to": day.isoformat()},
    )
    assert response.status_code == 200, response.text
    slots = [s for d in response.json()["days"] for s in d["slots"]]
    return [datetime.fromisoformat(s["starts_at"]).astimezone(clinic.tz).strftime("%H:%M") for s in slots]


async def book(client, clinic, days_ahead=3, hhmm="10:00"):
    headers = await clinic.headers_for(clinic.patient_a.user_id)
    response = await client.post(
        "/api/v1/appointments/",
        json={"doctor_id": str(clinic.doctor_a.id), "starts_at": clinic.slot(days_ahead, hhmm).isoformat()},
        headers=headers,
    )
    return response


@pytest.fixture
async def doctor(clinic):
    return await clinic.headers_for(clinic.doctor_a.user_id)


# ---- the precedence rule (no database) ------------------------------------------------


def _exception(kind, start, end):
    return SimpleNamespace(kind=kind, starts_at=start, ends_at=end)


def test_custom_hours_replace_the_weekly_hours_of_that_date_only():
    tz = ZoneInfo("Asia/Karachi")
    day = date(2026, 11, 5)
    template = SimpleNamespace(
        weekday=day.weekday(), start_time=time(8), end_time=time(16), slot_minutes=30,
        valid_from=date(2026, 1, 1), valid_until=None,
    )
    custom = _exception(
        ExceptionKind.custom_hours, datetime.combine(day, time(10), tz), datetime.combine(day, time(12), tz)
    )
    slots = working_slots([template], [custom], tz, day, day + timedelta(days=7))
    on_day = [s.starts_at.astimezone(tz).strftime("%H:%M") for s in slots if s.starts_at.astimezone(tz).date() == day]
    assert on_day == ["10:00", "10:30", "11:00", "11:30"]  # not merged with 08:00-16:00
    next_week = [s for s in slots if s.starts_at.astimezone(tz).date() == day + timedelta(days=7)]
    assert len(next_week) == 16  # the weekly hours still apply on other dates


def test_unavailable_wins_over_custom_hours_on_the_same_day():
    tz = ZoneInfo("UTC")
    day = date(2026, 11, 5)
    start, end = datetime.combine(day, time(10), tz), datetime.combine(day, time(12), tz)
    exceptions = [
        _exception(ExceptionKind.custom_hours, start, end),
        _exception(ExceptionKind.leave, datetime.combine(day, time.min, tz), datetime.combine(day, time.max, tz)),
    ]
    assert working_slots([], exceptions, tz, day, day) == []


# ---- weekly hours -------------------------------------------------------------------------


async def test_doctor_reads_their_weekly_schedule(client, clinic, doctor):
    response = await client.get(weekly_url(clinic.doctor_a.id), headers=doctor)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Asia/Karachi"
    assert [d["weekday"] for d in body["days"]] == list(range(7))
    assert all(d["enabled"] and d["slot_minutes"] == 30 for d in body["days"])
    assert body["days"][0]["intervals"] == [{"start_time": "09:00:00", "end_time": "17:00:00"}]


async def test_a_doctor_without_hours_gets_an_empty_week(client, db_session, make_doctor):
    doctor = await make_doctor()
    headers = await login_as(client, db_session, doctor.user_id)
    body = (await client.get(weekly_url(doctor.id), headers=headers)).json()
    assert all(not d["enabled"] and d["intervals"] == [] for d in body["days"])


async def test_saving_the_week_changes_patient_availability(client, clinic, doctor, db_session):
    day = clinic.today + timedelta(days=5)
    later = clinic.today + timedelta(days=6)
    response = await client.put(
        weekly_url(clinic.doctor_a.id),
        json=week(**{str(day.weekday()): [], str(later.weekday()): [("10:00", "12:00"), ("14:00", "15:00")]}),
        headers=doctor,
    )
    assert response.status_code == 200, response.text
    saved = {d["weekday"]: d for d in response.json()["days"]}
    assert saved[day.weekday()]["enabled"] is False
    assert len(saved[later.weekday()]["intervals"]) == 2

    assert await local_slots(client, clinic, clinic.doctor_a.id, day) == []
    assert await local_slots(client, clinic, clinic.doctor_a.id, later) == ["10:00", "10:30", "11:00", "11:30", "14:00", "14:30"]
    # Past dates keep their history: the old templates end yesterday instead of vanishing.
    ended = await db_session.scalars(
        select(ScheduleTemplate).where(
            ScheduleTemplate.doctor_id == clinic.doctor_a.id, ScheduleTemplate.weekday == day.weekday()
        )
    )
    assert [t.valid_until for t in ended] == [clinic.today - timedelta(days=1)]


async def test_saving_an_unchanged_week_changes_nothing(client, clinic, doctor, db_session):
    before = len((await db_session.scalars(select(ScheduleTemplate.id))).all())
    assert (await client.put(weekly_url(clinic.doctor_a.id), json=week(), headers=doctor)).status_code == 200
    assert len((await db_session.scalars(select(ScheduleTemplate.id))).all()) == before


@pytest.mark.parametrize(
    "body",
    [
        week(**{"0": [("12:00", "10:00")]}),
        week(**{"0": [("10:00", "10:00")]}),
        week(**{"0": [("09:00", "12:00"), ("11:00", "13:00")]}),
        {"days": week()["days"][:6]},
        {"days": week()["days"][:6] + [week()["days"][0]]},
        {"days": [{**d, "intervals": []} if d["weekday"] == 0 else d for d in week()["days"]]},
    ],
    ids=["end-before-start", "empty-range", "overlap", "six-days", "duplicate-day", "enabled-without-hours"],
)
async def test_invalid_weeks_are_rejected(client, clinic, doctor, body):
    response = await client.put(weekly_url(clinic.doctor_a.id), json=body, headers=doctor)
    assert response.status_code == 422


async def test_doctors_manage_only_their_own_week(client, clinic, doctor):
    assert (await client.get(weekly_url(clinic.doctor_b.id), headers=doctor)).status_code == 403
    assert (await client.put(weekly_url(clinic.doctor_b.id), json=week(**{"0": []}), headers=doctor)).status_code == 403
    patient = await clinic.headers_for(clinic.patient_a.user_id)
    assert (await client.put(weekly_url(clinic.doctor_a.id), json=week(), headers=patient)).status_code == 403
    # Reception may manage anyone's (schedule:manage_any).
    reception = await clinic.headers_for(clinic.receptionist.id)
    assert (await client.get(weekly_url(clinic.doctor_b.id), headers=reception)).status_code == 200


async def test_a_week_that_would_strand_a_booked_patient_is_refused(client, clinic, doctor, db_session):
    assert (await book(client, clinic, 3, "10:00")).status_code == 201
    weekday = (clinic.today + timedelta(days=3)).weekday()

    response = await client.put(weekly_url(clinic.doctor_a.id), json=week(**{str(weekday): [("12:00", "17:00")]}), headers=doctor)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "SCHEDULE_CONFLICT" and "reschedule or cancel" in error["message"]
    assert error["details"]["dates"] == [(clinic.today + timedelta(days=3)).isoformat()]
    assert "patient" not in str(error["details"]).lower()

    # Nothing changed: the appointment is intact and the old hours still apply.
    assert (await db_session.scalar(select(Appointment.status))).value == "scheduled"
    assert "09:00" in await local_slots(client, clinic, clinic.doctor_a.id, clinic.today + timedelta(days=3))

    # Hours that still contain the appointment are fine.
    ok = await client.put(weekly_url(clinic.doctor_a.id), json=week(**{str(weekday): [("09:00", "12:00")]}), headers=doctor)
    assert ok.status_code == 200, ok.text


# ---- date exceptions ------------------------------------------------------------------------


async def test_an_unavailable_date_removes_its_slots_until_deleted(client, clinic, doctor):
    day = clinic.today + timedelta(days=4)
    created = await client.post(
        exceptions_url(clinic.doctor_a.id),
        json={"date": day.isoformat(), "type": "unavailable", "reason": "Public holiday"},
        headers=doctor,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["type"] == "unavailable" and body["date"] == body["end_date"] == day.isoformat()
    assert body["start_time"] is None and body["editable"] is True and body["reason"] == "Public holiday"
    assert await local_slots(client, clinic, clinic.doctor_a.id, day) == []

    listing = (await client.get(exceptions_url(clinic.doctor_a.id), headers=doctor)).json()
    assert [e["id"] for e in listing] == [body["id"]]

    assert (await client.delete(exceptions_url(clinic.doctor_a.id, body["id"]), headers=doctor)).status_code == 204
    assert len(await local_slots(client, clinic, clinic.doctor_a.id, day)) == 16


async def test_custom_hours_replace_the_weekly_hours_for_patients(client, clinic, doctor):
    day = clinic.today + timedelta(days=4)
    response = await client.post(
        exceptions_url(clinic.doctor_a.id),
        json={"date": day.isoformat(), "type": "custom_hours", "start_time": "10:00", "end_time": "12:00", "reason": "Conference"},
        headers=doctor,
    )
    assert response.status_code == 201, response.text
    assert response.json()["start_time"] == "10:00:00" and response.json()["end_time"] == "12:00:00"
    assert await local_slots(client, clinic, clinic.doctor_a.id, day) == ["10:00", "10:30", "11:00", "11:30"]
    # Other doctors and other days are untouched.
    assert len(await local_slots(client, clinic, clinic.doctor_b.id, day)) == 16


async def test_one_exception_per_date(client, clinic, doctor):
    body = {"date": (clinic.today + timedelta(days=4)).isoformat(), "type": "unavailable"}
    assert (await client.post(exceptions_url(clinic.doctor_a.id), json=body, headers=doctor)).status_code == 201
    again = await client.post(exceptions_url(clinic.doctor_a.id), json=body, headers=doctor)
    assert again.status_code == 409 and again.json()["error"]["code"] == "EXCEPTION_EXISTS"


@pytest.mark.parametrize(
    "body",
    [
        {"type": "custom_hours"},
        {"type": "custom_hours", "start_time": "14:00", "end_time": "10:00"},
        {"type": "extra_hours"},
        {"type": "unavailable", "reason": "x" * 256},
    ],
)
async def test_invalid_exceptions_are_rejected(client, clinic, doctor, body):
    body = {"date": (clinic.today + timedelta(days=4)).isoformat(), **body}
    assert (await client.post(exceptions_url(clinic.doctor_a.id), json=body, headers=doctor)).status_code == 422


async def test_past_dates_cannot_be_changed(client, clinic, doctor):
    body = {"date": (clinic.today - timedelta(days=1)).isoformat(), "type": "unavailable"}
    response = await client.post(exceptions_url(clinic.doctor_a.id), json=body, headers=doctor)
    assert response.status_code == 400 and response.json()["error"]["code"] == "PAST_DATE"


async def test_exceptions_that_would_strand_a_booked_patient_are_refused(client, clinic, doctor):
    assert (await book(client, clinic, 3, "10:00")).status_code == 201
    day = (clinic.today + timedelta(days=3)).isoformat()
    url = exceptions_url(clinic.doctor_a.id)

    off = await client.post(url, json={"date": day, "type": "unavailable"}, headers=doctor)
    assert off.status_code == 409 and off.json()["error"]["code"] == "SCHEDULE_CONFLICT"
    later = await client.post(url, json={"date": day, "type": "custom_hours", "start_time": "12:00", "end_time": "14:00"}, headers=doctor)
    assert later.status_code == 409
    keeps = await client.post(url, json={"date": day, "type": "custom_hours", "start_time": "09:00", "end_time": "12:00"}, headers=doctor)
    assert keeps.status_code == 201, keeps.text


async def test_deleting_custom_hours_is_refused_while_a_booking_needs_them(client, clinic, doctor):
    day = clinic.today + timedelta(days=3)
    custom = await client.post(
        exceptions_url(clinic.doctor_a.id),
        json={"date": day.isoformat(), "type": "custom_hours", "start_time": "18:00", "end_time": "20:00"},
        headers=doctor,
    )
    assert custom.status_code == 201
    assert (await book(client, clinic, 3, "18:00")).status_code == 201  # only bookable thanks to the custom hours

    response = await client.delete(exceptions_url(clinic.doctor_a.id, custom.json()["id"]), headers=doctor)
    assert response.status_code == 409 and response.json()["error"]["code"] == "SCHEDULE_CONFLICT"


async def test_editing_an_exception_changes_availability(client, clinic, doctor):
    day = clinic.today + timedelta(days=4)
    url = exceptions_url(clinic.doctor_a.id)
    created = (await client.post(url, json={"date": day.isoformat(), "type": "unavailable"}, headers=doctor)).json()

    response = await client.put(
        exceptions_url(clinic.doctor_a.id, created["id"]),
        json={"date": day.isoformat(), "type": "custom_hours", "start_time": "15:00", "end_time": "16:00"},
        headers=doctor,
    )
    assert response.status_code == 200, response.text
    assert response.json()["type"] == "custom_hours"
    assert await local_slots(client, clinic, clinic.doctor_a.id, day) == ["15:00", "15:30"]


async def test_doctors_cannot_touch_another_doctors_exceptions(client, clinic, doctor):
    other = await clinic.headers_for(clinic.doctor_b.user_id)
    created = (
        await client.post(
            exceptions_url(clinic.doctor_a.id),
            json={"date": (clinic.today + timedelta(days=4)).isoformat(), "type": "unavailable"},
            headers=doctor,
        )
    ).json()
    # Through their own URL the id does not exist; through Dr A's URL they are refused.
    assert (await client.delete(exceptions_url(clinic.doctor_b.id, created["id"]), headers=other)).status_code == 404
    assert (await client.delete(exceptions_url(clinic.doctor_a.id, created["id"]), headers=other)).status_code == 403
    assert (await client.get(exceptions_url(clinic.doctor_a.id), headers=other)).status_code == 403


async def test_a_booking_made_from_stale_availability_is_refused(client, clinic, doctor):
    """The patient saw the slot before the doctor took the day off."""
    day = clinic.today + timedelta(days=4)
    assert "10:00" in await local_slots(client, clinic, clinic.doctor_a.id, day)
    await client.post(exceptions_url(clinic.doctor_a.id), json={"date": day.isoformat(), "type": "unavailable"}, headers=doctor)
    response = await book(client, clinic, 4, "10:00")
    assert response.status_code == 409 and response.json()["error"]["code"] == "SLOT_UNAVAILABLE"


async def test_the_directory_badge_follows_the_schedule(client, clinic, doctor):
    """With every day of the coming week off, the doctor is unavailable."""
    off = {str(weekday): [] for weekday in range(7)}
    assert (await client.put(weekly_url(clinic.doctor_a.id), json=week(**off), headers=doctor)).status_code == 200
    listing = (await client.get("/api/v1/public/doctors/", params={"q": "Doctor Alpha"})).json()
    [item] = listing["items"]
    assert item["availability"]["status"] == "unavailable"
