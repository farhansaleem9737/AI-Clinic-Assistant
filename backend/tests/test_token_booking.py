"""Automatic token booking, custom times, queue positions and the doctor's
appointment length (D120). The clinic fixture's doctors work 09:00-17:00
Asia/Karachi every day; each test saves a policy first."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.main import app
from app.models.schedule import ExceptionKind, ScheduleException, ScheduleTemplate
from app.services.ai.provider import get_provider
from app.services.availability_service import Timing, working_slots
from tests.test_ai_agent import ScriptedProvider, call, text_reply
from tests.test_hybrid_scheduling import POLICY

APPTS = "/api/v1/appointments"
KHI = ZoneInfo("Asia/Karachi")


def local(dt_iso: str) -> str:
    """'09:15' for an API instant, in the clinic's zone."""
    return datetime.fromisoformat(dt_iso.replace("Z", "+00:00")).astimezone(KHI).strftime("%H:%M")


async def set_policy(client, clinic, minutes=15, **extra):
    doctor = await clinic.headers_for(clinic.doctor_a.user_id)
    response = await client.put(
        f"/api/v1/doctors/{clinic.doctor_a.id}/scheduling-policy",
        json={**POLICY, "consultation_minutes": minutes, **extra},
        headers=doctor,
    )
    return response


async def next_free(client, clinic, headers, day: date, **params):
    response = await client.get(
        f"{APPTS}/next-available", params={"doctor_id": str(clinic.doctor_a.id), "date": day.isoformat(), **params},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def book(client, clinic, headers, starts_at, mode="custom", **body):
    return await client.post(
        f"{APPTS}/",
        json={"doctor_id": str(clinic.doctor_a.id), "starts_at": starts_at, "booking_mode": mode, **body},
        headers=headers,
    )


# ---- slot generation (pure) -------------------------------------------------------------


def hm(instant, tz=KHI, fmt="%H:%M") -> str:
    return instant.astimezone(tz).strftime(fmt)


def _template(weekday, start, end, today):
    return ScheduleTemplate(weekday=weekday, start_time=start, end_time=end, slot_minutes=30, valid_from=today, is_active=True)


@pytest.mark.parametrize(("minutes", "count", "second"), [(15, 32, "09:15"), (20, 24, "09:20"), (30, 16, "09:30")])
def test_a_nine_to_five_day_in_15_20_or_30_minute_appointments(minutes, count, second):
    day = date(2026, 11, 9)
    slots = working_slots([_template(day.weekday(), time(9), time(17), day)], [], KHI, day, day, Timing(minutes))
    assert len(slots) == count
    assert [hm(s.starts_at) for s in slots[:2]] == ["09:00", second]
    assert hm(slots[-1].ends_at) == "17:00"  # the last one ends at closing, never after


def test_breaks_days_off_custom_hours_and_partial_intervals():
    day = date(2026, 11, 9)
    # A lunch break: 09:00-13:00 and 14:00-17:00.
    split = [_template(day.weekday(), time(9), time(13), day), _template(day.weekday(), time(14), time(17), day)]
    slots = working_slots(split, [], KHI, day, day, Timing(15))
    assert len(slots) == 28 and not any(s.starts_at.astimezone(KHI).hour == 13 for s in slots)
    # A partial interval: 09:00-10:10 holds only four 15-minute appointments (10:00-10:15 would overrun).
    short = working_slots([_template(day.weekday(), time(9), time(10, 10), day)], [], KHI, day, day, Timing(15))
    assert [hm(s.starts_at) for s in short] == ["09:00", "09:15", "09:30", "09:45"]
    # A day off.
    leave = ScheduleException(kind=ExceptionKind.leave, starts_at=datetime.combine(day, time(0), KHI),
                              ends_at=datetime.combine(day + timedelta(days=1), time(0), KHI))
    assert working_slots(split, [leave], KHI, day, day, Timing(15)) == []
    # Custom hours for one date replace the weekly hours.
    custom = ScheduleException(kind=ExceptionKind.custom_hours, starts_at=datetime.combine(day, time(11), KHI),
                               ends_at=datetime.combine(day, time(12), KHI))
    assert [hm(s.starts_at) for s in working_slots(split, [custom], KHI, day, day, Timing(20))] == [
        "11:00", "11:20", "11:40"]
    # 15 minutes + a 5-minute buffer: one every 20 minutes.
    buffered = working_slots(split, [], KHI, day, day, Timing(15, 5))
    assert [hm(s.starts_at) for s in buffered[:3]] == ["09:00", "09:20", "09:40"]


def test_local_hours_hold_across_a_daylight_saving_change():
    ny = ZoneInfo("America/New_York")
    day = date(2026, 3, 8)  # clocks go forward at 02:00
    slots = working_slots([_template(day.weekday(), time(9), time(17), day)], [], ny, day, day, Timing(30))
    assert len(slots) == 16 and hm(slots[0].starts_at, ny, "%H:%M %Z") == "09:00 EDT"


# ---- automatic token booking -------------------------------------------------------------


async def test_automatic_booking_takes_the_earliest_free_time_and_tracks_the_queue(client, clinic):
    assert (await set_policy(client, clinic)).status_code == 200
    day = clinic.today + timedelta(days=2)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    bob = await clinic.headers_for(clinic.patient_b.user_id)

    first = await next_free(client, clinic, alice, day)
    assert local(first["slot"]["starts_at"]) == "09:00" and first["queue_position"] == 1
    assert first["consultation_minutes"] == 15 and first["free_count"] == 32 and first["booked_count"] == 0
    booked = await book(client, clinic, alice, first["slot"]["starts_at"], "auto")
    assert booked.status_code == 201, booked.text
    alices = booked.json()
    assert alices["booking_mode"] == "auto" and alices["queue_position"] == 1 and alices["duration_minutes"] == 15

    # Bob picks a custom time later in the morning; the automatic queue skips nothing it should not.
    custom = await book(client, clinic, bob, clinic.slot(2, "09:30").isoformat())
    assert custom.status_code == 201 and custom.json()["booking_mode"] == "custom"
    assert custom.json()["queue_position"] == 2

    # Reception books the walk-in patient automatically: the gap at 09:15, not "bookings + 1".
    reception = await clinic.headers_for(clinic.receptionist.id)
    gap = await next_free(client, clinic, reception, day, patient_id=str(clinic.walk_in.id))
    assert local(gap["slot"]["starts_at"]) == "09:15" and gap["queue_position"] == 2
    made = await book(client, clinic, reception, gap["slot"]["starts_at"], "auto", patient_id=str(clinic.walk_in.id))
    assert made.status_code == 201
    # Bob's custom 09:30 is now third in the day (positions are recomputed, never stored).
    bobs = (await client.get(f"{APPTS}/{custom.json()['id']}", headers=bob)).json()
    assert bobs["queue_position"] == 3

    # Alice cancels: 09:00 is free again for the next automatic booking, and everyone moves up.
    cancelled = await client.post(f"{APPTS}/{alices['id']}/status", json={"status": "cancelled", "cancellation_reason": "patient_request"}, headers=alice)
    assert cancelled.status_code == 200
    again = await next_free(client, clinic, bob, day)
    assert local(again["slot"]["starts_at"]) == "09:00" and again["queue_position"] == 1
    assert (await client.get(f"{APPTS}/{custom.json()['id']}", headers=bob)).json()["queue_position"] == 2

    # The day now holds the walk-in (09:15) and Bob (09:30).
    assert again["booked_count"] == 2


async def test_queues_are_per_doctor_and_a_taken_preview_names_the_next_time(client, clinic):
    await set_policy(client, clinic)
    day = clinic.today + timedelta(days=2)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    shown = await next_free(client, clinic, alice, day)
    also_shown = await next_free(client, clinic, bob, day)
    assert shown["slot"] == also_shown["slot"]  # both previewed 09:00

    assert (await book(client, clinic, alice, shown["slot"]["starts_at"], "auto")).status_code == 201
    late = await book(client, clinic, bob, also_shown["slot"]["starts_at"], "auto")
    assert late.status_code == 409
    error = late.json()["error"]
    assert error["code"] == "SLOT_UNAVAILABLE"
    assert local(error["details"]["next_available"]["starts_at"]) == "09:15"  # offered, not booked
    assert error["details"]["next_available"]["queue_position"] == 2

    # Doctor Beta's day has its own queue: Alice's booking with Alpha does not count there.
    beta = (await client.get(f"{APPTS}/next-available", params={"doctor_id": str(clinic.doctor_b.id), "date": day.isoformat()}, headers=bob)).json()
    assert beta["queue_position"] == 1 and beta["booked_count"] == 0


async def test_a_full_day_offers_the_next_date(client, clinic, db_session):
    await set_policy(client, clinic, minutes=30)
    day = clinic.today + timedelta(days=2)
    db_session.add(ScheduleException(
        doctor_id=clinic.doctor_a.id, kind=ExceptionKind.custom_hours,
        starts_at=datetime.combine(day, time(9), KHI), ends_at=datetime.combine(day, time(9, 30), KHI),
    ))
    await db_session.commit()
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    only = await next_free(client, clinic, alice, day)
    assert only["free_count"] == 1
    assert (await book(client, clinic, alice, only["slot"]["starts_at"], "auto")).status_code == 201
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    full = await next_free(client, clinic, bob, day)
    assert full["slot"] is None and full["queue_position"] is None
    assert full["next_date"] == (day + timedelta(days=1)).isoformat()


# ---- custom times -------------------------------------------------------------------------


async def test_custom_times_must_be_free_listed_times(client, clinic):
    await set_policy(client, clinic)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    assert (await book(client, clinic, alice, clinic.slot(2, "11:15").isoformat())).status_code == 201
    for when in ("11:15", "08:00", "17:00", "11:07"):  # taken, before hours, at closing, off the grid
        refused = await book(client, clinic, bob, clinic.slot(2, when).isoformat())
        assert refused.status_code == 409 and refused.json()["error"]["code"] == "SLOT_UNAVAILABLE", when
    # Nothing in the request can turn a custom booking into an override.
    assert (await book(client, clinic, bob, clinic.slot(2, "11:15").isoformat(), double_booking=True)).status_code == 403


# ---- the doctor's appointment length -----------------------------------------------------


@pytest.mark.parametrize(("minutes", "count"), [(15, 32), (20, 24), (30, 16)])
async def test_the_preview_shows_the_real_day_for_each_length(client, clinic, minutes, count):
    doctor = await clinic.headers_for(clinic.doctor_a.user_id)
    day = clinic.today + timedelta(days=3)
    response = await client.post(
        f"/api/v1/doctors/{clinic.doctor_a.id}/scheduling-policy/preview",
        json={"date": day.isoformat(), "consultation_minutes": minutes}, headers=doctor,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["slots"]) == count and body["free_count"] == count and body["working_hours"] == [["09:00", "17:00"]]
    assert (await set_policy(client, clinic, minutes)).status_code == 200
    saved = await client.get(f"/api/v1/doctors/{clinic.doctor_a.id}/scheduling-policy", headers=doctor)
    assert saved.json()["consultation_minutes"] == minutes and saved.json()["standard_durations"] == [15, 20, 30]


async def test_a_new_length_never_strands_existing_bookings_silently(client, clinic):
    await set_policy(client, clinic)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    made = await book(client, clinic, alice, clinic.slot(2, "09:15").isoformat())
    assert made.status_code == 201
    doctor = await clinic.headers_for(clinic.doctor_a.user_id)

    preview = (await client.post(
        f"/api/v1/doctors/{clinic.doctor_a.id}/scheduling-policy/preview",
        json={"date": (clinic.today + timedelta(days=2)).isoformat(), "consultation_minutes": 20}, headers=doctor,
    )).json()
    assert preview["affected_count"] == 1 and preview["affected"][0]["id"] == made.json()["id"]
    assert preview["booked_count"] == 2  # 09:00-09:20 and 09:20-09:40 both overlap 09:15-09:30

    refused = await set_policy(client, clinic, 20)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "SCHEDULE_CONFLICTS"
    assert refused.json()["error"]["details"]["count"] == 1
    assert (await client.get(f"/api/v1/doctors/{clinic.doctor_a.id}/scheduling-policy", headers=doctor)).json()["consultation_minutes"] == 15

    kept = await set_policy(client, clinic, 20, keep_existing_appointments=True)
    assert kept.status_code == 200 and kept.json()["consultation_minutes"] == 20
    still = (await client.get(f"{APPTS}/{made.json()['id']}", headers=alice)).json()
    assert local(still["starts_at"]) == "09:15" and still["duration_minutes"] == 15 and still["status"] == "scheduled"


async def test_only_the_doctor_or_an_admin_changes_the_length(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    reception = await clinic.headers_for(clinic.receptionist.id)
    other = await clinic.headers_for(clinic.doctor_b.user_id)
    url = f"/api/v1/doctors/{clinic.doctor_a.id}/scheduling-policy"
    for headers in (alice, reception, other):
        assert (await client.put(url, json={**POLICY, "consultation_minutes": 20}, headers=headers)).status_code == 403
    assert (await client.post(f"{url}/preview", json={"date": clinic.today.isoformat(), "consultation_minutes": 20}, headers=alice)).status_code == 403
    admin = await clinic.headers_for(clinic.admin.id)
    assert (await client.put(url, json={**POLICY, "consultation_minutes": 30}, headers=admin)).status_code == 200


# ---- the assistant ------------------------------------------------------------------------


async def test_the_assistant_books_the_next_available_time_the_server_assigns(client, clinic):
    from tests.test_ai_queue import ask

    await set_policy(client, clinic)
    provider = ScriptedProvider()
    app.dependency_overrides[get_provider] = lambda: provider
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    day = clinic.today + timedelta(days=2)
    sent = await ask(client, alice, provider, "Book me the next available appointment with Doctor Alpha",
                     call("propose_booking", doctor_id=str(clinic.doctor_a.id), earliest_on=day.isoformat()), text_reply("(ignored)"))
    action = sent["assistant_message"]["action"]
    assert action["booking_mode"] == "auto" and action["queue_position"] == 1
    assert local(action["starts_at"]) == "09:00" and "next available" in sent["assistant_message"]["content"]

    confirmed = await ask(client, alice, provider, "yes", conversation_id=sent["conversation"]["id"])
    assert "queue no. that day is 1" in confirmed["assistant_message"]["content"]
    [mine] = (await client.get(f"{APPTS}/", headers=alice)).json()["items"]
    assert mine["booking_mode"] == "auto" and local(mine["starts_at"]) == "09:00"
