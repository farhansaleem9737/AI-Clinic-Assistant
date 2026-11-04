"""Notification events, reminders, follow-ups and preferences (D108)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.config import settings
from app.models.notification import Notification
from app.services import notification_service, reminder_service
from app.services.reminder_service import due_offset

NOTIFICATIONS = "/api/v1/notifications"
RUN = "/api/v1/internal/reminders/run"


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def book(client, clinic, headers, patient=None, days=2, hhmm="10:00"):
    body = {"doctor_id": str(clinic.doctor_a.id), "starts_at": iso(clinic.slot(days, hhmm))}
    if patient is not None:
        body["patient_id"] = str(patient.id)
    response = await client.post("/api/v1/appointments/", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def types_for(client, headers) -> list[str]:
    return [n["type"] for n in (await client.get(NOTIFICATIONS, headers=headers)).json()["items"]]


async def count(db, user_id, type_) -> int:
    return await db.scalar(
        select(func.count()).select_from(Notification).where(Notification.user_id == user_id, Notification.type == type_)
    )


# ---- appointment events --------------------------------------------------------------------


async def test_booked_on_the_patients_behalf_tells_the_patient_but_not_when_they_book_themselves(client, clinic):
    reception = await clinic.headers_for(clinic.receptionist.id)
    appt = await book(client, clinic, reception, patient=clinic.patient_a)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    [note] = (await client.get(NOTIFICATIONS, headers=alice)).json()["items"]
    assert note["type"] == "appointment_booked_for_you" and note["link"] == f"/appointments/{appt['id']}"
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    await book(client, clinic, bob, days=3)
    assert await types_for(client, bob) == []  # their own action


async def test_confirmation_tells_the_patient_and_check_in_tells_the_doctor(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice)
    reception = await clinic.headers_for(clinic.receptionist.id)
    url = f"/api/v1/appointments/{appt['id']}/status"
    assert (await client.post(url, json={"status": "confirmed"}, headers=reception)).status_code == 200
    assert await types_for(client, alice) == ["appointment_confirmed"]
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    assert "appointment_confirmed" not in await types_for(client, dr_a)


async def test_a_patient_reschedule_tells_the_doctor_and_front_desk_with_the_new_time(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=3)
    moved = await client.post(
        f"/api/v1/appointments/{appt['id']}/reschedule", json={"starts_at": iso(clinic.slot(4, "11:00"))}, headers=alice
    )
    assert moved.status_code == 201, moved.text
    new_id = moved.json()["id"]
    for user_id in (clinic.doctor_a.user_id, clinic.receptionist.id):
        items = (await client.get(NOTIFICATIONS, headers=await clinic.headers_for(user_id))).json()["items"]
        [note] = [n for n in items if n["type"] == "appointment_rescheduled"]
        assert note["link"] == f"/appointments/{new_id}" and "11:00" in note["message"]
    assert await types_for(client, alice) == []  # whoever moved it is not told


async def test_a_patient_cancellation_reaches_the_front_desk_too(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice)
    cancelled = await client.post(
        f"/api/v1/appointments/{appt['id']}/status",
        json={"status": "cancelled", "cancellation_reason": "patient_request"},
        headers=alice,
    )
    assert cancelled.status_code == 200, cancelled.text
    reception = await clinic.headers_for(clinic.receptionist.id)
    assert await types_for(client, reception) == ["appointment_cancelled"]


async def test_switched_off_updates_are_not_sent_but_essential_ones_are(client, clinic):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    prefs = await client.put(f"{NOTIFICATIONS}/preferences", json={"appointment_updates": False}, headers=alice)
    assert prefs.json() == {"appointment_updates": False, "reminders": True, "follow_ups": True, "emails": True}
    reception = await clinic.headers_for(clinic.receptionist.id)
    await book(client, clinic, reception, patient=clinic.patient_a)
    assert await types_for(client, alice) == []
    # Another user's preferences are untouched and their own.
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    assert (await client.get(f"{NOTIFICATIONS}/preferences", headers=bob)).json()["appointment_updates"] is True
    # A doctor's new booking is essential.
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    await client.put(f"{NOTIFICATIONS}/preferences", json={"appointment_updates": False}, headers=dr_a)
    assert "appointment_booked" in await types_for(client, dr_a)


async def test_schedule_changes_by_the_clinic_tell_the_doctor(client, clinic):
    admin = await clinic.headers_for(clinic.admin.id)
    day = (datetime.now(ZoneInfo("Asia/Karachi")).date() + timedelta(days=10)).isoformat()
    created = await client.post(
        f"/api/v1/doctors/{clinic.doctor_a.id}/date-exceptions", json={"date": day, "type": "unavailable"}, headers=admin
    )
    assert created.status_code == 201, created.text
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    [note] = (await client.get(NOTIFICATIONS, headers=dr_a)).json()["items"]
    assert note["type"] == "schedule_changed" and note["link"] == "/schedule"


# ---- appointment reminders ---------------------------------------------------------------


async def test_reminders_24h_for_the_patient_then_1h_for_patient_and_doctor_once_each(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=2)
    starts = datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))
    patient_user, doctor_user = clinic.patient_a.user_id, clinic.doctor_a.user_id

    day_before = await reminder_service.run(db_session, now=starts - timedelta(hours=23))
    assert day_before.reminders_created == 1
    assert await count(db_session, patient_user, "appointment_reminder") == 1
    assert await count(db_session, doctor_user, "appointment_reminder") == 0  # doctors: 1 hour only

    # The same run again (a retry, an overlap): nothing new.
    assert (await reminder_service.run(db_session, now=starts - timedelta(hours=22))).reminders_created == 0

    hour_before = await reminder_service.run(db_session, now=starts - timedelta(minutes=50))
    assert hour_before.reminders_created == 2
    assert await count(db_session, patient_user, "appointment_reminder") == 2
    assert await count(db_session, doctor_user, "appointment_reminder") == 1
    assert (await reminder_service.run(db_session, now=starts - timedelta(minutes=40))).reminders_created == 0
    # Started: nothing more.
    assert (await reminder_service.run(db_session, now=starts + timedelta(minutes=5))).reminders_created == 0

    items = (await client.get(NOTIFICATIONS, headers=alice)).json()["items"]
    assert [n["title"] for n in items] == ["Upcoming appointment", "Upcoming appointment"]
    assert items[0]["link"] == f"/appointments/{appt['id']}" and "1 hour" in items[0]["message"]
    assert "24 hours" in items[1]["message"]


async def test_cancelled_appointments_get_no_reminder_and_moved_ones_use_the_new_time(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    cancelled = await book(client, clinic, alice, days=2, hhmm="10:00")
    await client.post(
        f"/api/v1/appointments/{cancelled['id']}/status",
        json={"status": "cancelled", "cancellation_reason": "patient_request"},
        headers=alice,
    )
    moving = await book(client, clinic, alice, days=3, hhmm="10:00")
    moved = (
        await client.post(
            f"/api/v1/appointments/{moving['id']}/reschedule", json={"starts_at": iso(clinic.slot(3, "15:00"))}, headers=alice
        )
    ).json()
    old_start = clinic.slot(3, "10:00")
    new_start = clinic.slot(3, "15:00")

    # The cancelled one at its own 1-hour mark: nothing (the moved one is still more than a day away).
    assert (await reminder_service.run(db_session, now=clinic.slot(2, "10:00") - timedelta(minutes=50))).reminders_created == 0
    # At the old time's 1-hour mark the old row is cancelled; the new one, 6 hours
    # away, gets the patient's 24-hour reminder.
    assert (await reminder_service.run(db_session, now=old_start - timedelta(minutes=50))).reminders_created == 1
    result = await reminder_service.run(db_session, now=new_start - timedelta(minutes=50))
    assert result.reminders_created == 2  # patient and doctor 1-hour reminders, for the new appointment
    links = {n.link for n in await db_session.scalars(select(Notification).where(Notification.type == "appointment_reminder"))}
    assert links == {f"/appointments/{moved['id']}"}


async def test_a_late_booking_gets_only_the_reminders_still_ahead(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=2)
    starts = datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))
    booked = starts - timedelta(hours=3)  # as if it had been booked 3 hours ahead
    assert due_offset([1440, 60], starts, booked, starts - timedelta(hours=2)) is None  # 24 h mark already past
    assert due_offset([1440, 60], starts, booked, starts - timedelta(minutes=30)) == 60
    assert due_offset([1440, 60], starts, starts - timedelta(minutes=30), starts - timedelta(minutes=10)) is None


def test_reminder_times_are_elapsed_time_across_a_daylight_saving_change():
    # US clocks went back on 1 Nov 2026 at 02:00 local: 24 hours before 09:00 on
    # 1 Nov is 10:00 on 31 Oct local, not 09:00. UTC arithmetic gets this right.
    ny = ZoneInfo("America/New_York")
    starts = datetime(2026, 11, 1, 9, 0, tzinfo=ny).astimezone(UTC)
    booked = starts - timedelta(days=5)
    assert due_offset([1440, 60], starts, booked, datetime(2026, 10, 31, 9, 30, tzinfo=ny).astimezone(UTC)) is None
    assert due_offset([1440, 60], starts, booked, datetime(2026, 10, 31, 10, 0, tzinfo=ny).astimezone(UTC)) == 1440
    assert notification_service.when(starts, ny) == "Sun 01 Nov 2026, 09:00"


async def test_reminders_respect_the_patients_preference(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    await client.put(f"{NOTIFICATIONS}/preferences", json={"reminders": False}, headers=alice)
    appt = await book(client, clinic, alice, days=2)
    starts = datetime.fromisoformat(appt["starts_at"].replace("Z", "+00:00"))
    await reminder_service.run(db_session, now=starts - timedelta(minutes=50))
    assert await count(db_session, clinic.patient_a.user_id, "appointment_reminder") == 0
    assert await count(db_session, clinic.doctor_a.user_id, "appointment_reminder") == 1


async def test_notify_once_never_duplicates(db_session, clinic):
    kwargs = dict(dedupe_key="reminder:test", type="appointment_reminder", title="t", message="m")
    assert await notification_service.notify_once(db_session, clinic.patient_a.user_id, **kwargs) is True
    assert await notification_service.notify_once(db_session, clinic.patient_a.user_id, **kwargs) is False
    assert await notification_service.notify_once(db_session, clinic.patient_b.user_id, **kwargs) is True  # per user


# ---- follow-ups ----------------------------------------------------------------------------


async def test_follow_ups_are_recorded_by_the_doctor_reminded_once_and_dismissable(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=2)
    url = f"/api/v1/appointments/{appt['id']}/follow-up"
    tz = ZoneInfo("Asia/Karachi")
    due = datetime.now(tz).date() + timedelta(days=30)

    # The patient can see it but not record one; nobody records one in the past.
    assert (await client.get(url, headers=alice)).json() == {"follow_up": None, "can_manage": False}
    assert (await client.put(url, json={"due_date": due.isoformat()}, headers=alice)).status_code == 403
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    past = (datetime.now(tz).date() - timedelta(days=1)).isoformat()
    assert (await client.put(url, json={"due_date": past}, headers=dr_a)).status_code == 400
    recorded = await client.put(url, json={"due_date": due.isoformat()}, headers=dr_a)
    assert recorded.status_code == 200, recorded.text
    follow_up_id = recorded.json()["id"]
    # Another doctor cannot see the appointment at all.
    dr_b = await clinic.headers_for(clinic.doctor_b.user_id)
    assert (await client.get(url, headers=dr_b)).status_code == 404

    # The patient's existing appointment was booked before: it does not count as booking the follow-up.
    now = datetime.combine(due - timedelta(days=5), datetime.min.time(), tzinfo=tz).astimezone(UTC)
    too_early = datetime.combine(due - timedelta(days=10), datetime.min.time(), tzinfo=tz).astimezone(UTC)
    assert (await reminder_service.run(db_session, now=too_early)).follow_up_reminders_created == 0
    assert (await reminder_service.run(db_session, now=now)).follow_up_reminders_created == 1
    assert (await reminder_service.run(db_session, now=now + timedelta(hours=1))).follow_up_reminders_created == 0
    note = next(n for n in (await client.get(NOTIFICATIONS, headers=alice)).json()["items"] if n["type"] == "follow_up_due")
    assert note["link"] == f"/appointments/book?doctor={clinic.doctor_a.id}" and "not booked" in note["message"]

    # Dismissed by the patient: gone, and a later run adds nothing.
    assert (await client.post(f"/api/v1/follow-ups/{follow_up_id}/dismiss", headers=alice)).status_code == 204
    assert (await client.get(url, headers=alice)).json()["follow_up"] is None
    bob = await clinic.headers_for(clinic.patient_b.user_id)
    assert (await client.post(f"/api/v1/follow-ups/{follow_up_id}/dismiss", headers=bob)).status_code == 404


async def test_a_follow_up_already_booked_is_not_reminded(client, clinic, db_session):
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    appt = await book(client, clinic, alice, days=2)
    dr_a = await clinic.headers_for(clinic.doctor_a.user_id)
    tz = ZoneInfo("Asia/Karachi")
    due = datetime.now(tz).date() + timedelta(days=5)
    await client.put(f"/api/v1/appointments/{appt['id']}/follow-up", json={"due_date": due.isoformat()}, headers=dr_a)
    await book(client, clinic, alice, days=4)  # the follow-up visit, booked after it was recorded
    assert (await reminder_service.run(db_session)).follow_up_reminders_created == 0


# ---- the notification center and the run endpoint ----------------------------------------


async def test_pages_of_notifications_and_unsafe_links(client, clinic):
    reception = await clinic.headers_for(clinic.receptionist.id)
    for days in (2, 3, 4):
        await book(client, clinic, reception, patient=clinic.patient_a, days=days)
    alice = await clinic.headers_for(clinic.patient_a.user_id)
    first = (await client.get(f"{NOTIFICATIONS}?limit=2", headers=alice)).json()
    assert len(first["items"]) == 2 and first["has_more"] is True and first["unread"] == 3
    rest = (await client.get(f"{NOTIFICATIONS}?limit=2&offset=2", headers=alice)).json()
    assert len(rest["items"]) == 1 and rest["has_more"] is False
    assert notification_service.safe_link("/appointments/book?doctor=x") is None
    assert notification_service.safe_link("https://evil.example") is None
    assert notification_service.safe_link("/admin/users") == "/admin/users"


async def test_the_reminder_run_is_closed_unless_configured_and_needs_its_credential(client, monkeypatch):
    monkeypatch.setattr(settings, "reminders_cron_secret", None)
    monkeypatch.setattr(settings, "reminders_oidc_audience", None)
    assert (await client.post(RUN)).status_code == 404
    monkeypatch.setattr(settings, "reminders_cron_secret", SecretStr("s3cret-value"))
    assert (await client.post(RUN, headers={"X-Reminders-Secret": "wrong"})).status_code == 401
    assert (await client.post(RUN, headers={"Authorization": "Bearer not-a-google-token"})).status_code == 401
    ok = await client.post(RUN, headers={"X-Reminders-Secret": "s3cret-value"})
    assert ok.status_code == 200 and set(ok.json()) >= {"reminders_created", "follow_up_reminders_created"}


@pytest.mark.parametrize("offsets", ["1440,60", "60,1440,60"])
def test_reminder_offsets_are_configurable(offsets):
    from app.core.config import Settings

    assert Settings(database_url="postgresql+asyncpg://u:p@h/db", reminder_offsets_minutes=offsets).reminder_offsets_minutes == [1440, 60]
