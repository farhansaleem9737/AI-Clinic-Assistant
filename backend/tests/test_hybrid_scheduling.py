"""Hybrid scheduling (D117): doctor policies, dynamic slots, audited staff
overrides with capacity lanes, and the day's queue with stable tokens.

The `clinic` fixture's doctors work 09:00-17:00 (Asia/Karachi) every day in
30-minute template slots, with no saved policy (the legacy behaviour)."""

import asyncio
import os
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.admin import AuditLog
from app.models.appointment import Appointment
from app.models.scheduling import QueueKind
from app.services import queue_service
from app.services.availability_service import slice_window
from app.services.queue_service import Waiting, choose_next, estimate, order

API = "/api/v1"
TZ = ZoneInfo("Asia/Karachi")


# ---- pure rules ---------------------------------------------------------------------------


def test_slots_follow_the_consultation_length_and_buffer():
    start, end = datetime(2026, 11, 9, 11, tzinfo=TZ), datetime(2026, 11, 9, 12, tzinfo=TZ)
    times = lambda slots: [s.starts_at.astimezone(TZ).strftime("%H:%M") for s in slots]  # noqa: E731
    assert times(slice_window(start, end, 15)) == ["11:00", "11:15", "11:30", "11:45"]
    assert times(slice_window(start, end, 20)) == ["11:00", "11:20", "11:40"]
    assert times(slice_window(start, end, 15, 20)) == ["11:00", "11:20", "11:40"]  # 5-minute buffer
    assert all(s.ends_at - s.starts_at == timedelta(minutes=15) for s in slice_window(start, end, 15, 20))


def _entry(token, kind="walk_in", checked_in=None, deferred=None, prioritized=None):
    return SimpleNamespace(
        token_number=token, kind=QueueKind(kind), checked_in_at=checked_in, deferred_until=deferred, prioritized_at=prioritized
    )


NOW = datetime(2026, 11, 9, 10, 0, tzinfo=TZ)


def test_walk_ins_are_first_in_first_out_and_ties_go_by_token():
    a = Waiting(_entry(5, checked_in=NOW - timedelta(minutes=10)), None)
    b = Waiting(_entry(3, checked_in=NOW - timedelta(minutes=20)), None)
    c = Waiting(_entry(4, checked_in=NOW - timedelta(minutes=10)), None)
    assert [w.entry.token_number for w in order([a, b, c], NOW)] == [3, 4, 5]


def test_a_booked_patient_keeps_their_reserved_time():
    walk_in = Waiting(_entry(1, checked_in=NOW - timedelta(minutes=30)), None)
    booked = Waiting(_entry(2, "scheduled", checked_in=NOW - timedelta(minutes=5)), NOW - timedelta(minutes=1))
    assert choose_next([walk_in, booked], NOW, 15, None)[0] is booked  # their time has come


def test_walk_ins_fill_only_genuinely_free_time():
    walk_in = Waiting(_entry(1, checked_in=NOW - timedelta(minutes=5)), None)
    early = Waiting(_entry(2, "scheduled", checked_in=NOW - timedelta(minutes=2)), NOW + timedelta(minutes=10))
    # 30 minutes before the next booked time: the walk-in fits.
    assert choose_next([walk_in], NOW, 15, NOW + timedelta(minutes=30)) == (walk_in, False)
    # 10 minutes: the booked patient who is already here goes first instead.
    assert choose_next([walk_in, early], NOW, 15, NOW + timedelta(minutes=10)) == (early, False)
    # Nobody booked is here yet: the walk-in is called, flagged as possibly delaying them.
    assert choose_next([walk_in], NOW, 15, NOW + timedelta(minutes=10)) == (walk_in, True)


def test_staff_adjustments_come_first_or_wait():
    first = Waiting(_entry(1, checked_in=NOW - timedelta(minutes=30)), None)
    urgent = Waiting(_entry(2, checked_in=NOW, prioritized=NOW), None)
    away = Waiting(_entry(3, checked_in=NOW - timedelta(minutes=40), deferred=NOW + timedelta(minutes=10)), None)
    assert [w.entry.token_number for w in order([first, urgent, away], NOW)] == [2, 1, 3]
    assert choose_next([away], NOW, 15, None) == (None, False)  # a deferred patient is not callable yet


def test_waits_are_ranges_and_never_before_a_booked_time():
    assert estimate(0, 15, NOW, None).model_dump() == {"min_minutes": 0, "max_minutes": 5}
    two_ahead = estimate(2, 15, NOW, None)
    assert two_ahead.min_minutes < 30 < two_ahead.max_minutes
    assert estimate(0, 15, NOW, NOW + timedelta(minutes=40)).min_minutes == 40


# ---- policies and slots -------------------------------------------------------------------


async def free_times(client, doctor_id, day):
    body = (await client.get(f"{API}/public/doctors/{doctor_id}/availability", params={"date_from": day, "date_to": day})).json()
    slots = body["days"][0]["slots"] if body["days"] else []
    return body, [datetime.fromisoformat(s["starts_at"]).astimezone(TZ).strftime("%H:%M") for s in slots]


POLICY = {
    "mode": "hybrid", "consultation_minutes": 15, "buffer_minutes": 0, "accept_walk_ins": True, "walk_in_capacity": None,
    "late_grace_minutes": 10, "max_overbook": 1, "allow_receptionist_overrides": True,
}


async def set_policy(client, clinic, **changes):
    headers = await clinic.headers_for(clinic.doctor_a.user_id)
    response = await client.put(f"{API}/doctors/{clinic.doctor_a.id}/scheduling-policy", json={**POLICY, **changes}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_the_doctors_policy_sets_the_times_and_never_moves_bookings(client, clinic):
    day = (clinic.today + timedelta(days=2)).isoformat()
    patient = await clinic.headers_for(clinic.patient_a.user_id)
    _, legacy = await free_times(client, clinic.doctor_a.id, day)
    assert legacy[:3] == ["09:00", "09:30", "10:00"]  # no policy yet: the templates' 30 minutes
    booked = await client.post(f"{API}/appointments/", json={"doctor_id": str(clinic.doctor_a.id), "starts_at": clinic.slot(2, "09:00").isoformat()}, headers=patient)
    assert booked.status_code == 201, booked.text

    # D120: the 30-minute booking does not fit 15-minute appointments, so saving
    # needs the explicit choice to keep it as it is (it is never moved).
    headers = await clinic.headers_for(clinic.doctor_a.user_id)
    refused = await client.put(f"{API}/doctors/{clinic.doctor_a.id}/scheduling-policy", json=POLICY, headers=headers)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "SCHEDULE_CONFLICTS"
    policy = await set_policy(client, clinic, keep_existing_appointments=True)
    assert policy["configured"] is True and policy["consultation_minutes"] == 15
    body, times = await free_times(client, clinic.doctor_a.id, day)
    assert body["scheduling_mode"] == "hybrid" and body["consultation_minutes"] == 15
    assert times[:4] == ["09:30", "09:45", "10:00", "10:15"] and len(times) == 30  # 09:00-09:30 stays booked
    appointment = (await client.get(f"{API}/appointments/{booked.json()['id']}", headers=patient)).json()
    assert appointment["duration_minutes"] == 30  # the existing booking keeps its own length

    await set_policy(client, clinic, consultation_minutes=20, keep_existing_appointments=True)
    _, twenty = await free_times(client, clinic.doctor_a.id, day)
    assert twenty[:3] == ["09:40", "10:00", "10:20"]


async def test_only_the_doctor_or_an_administrator_sets_the_policy(client, clinic, db_session):
    url = f"{API}/doctors/{clinic.doctor_a.id}/scheduling-policy"
    reception = await clinic.headers_for(clinic.receptionist.id)
    assert (await client.put(url, json=POLICY, headers=reception)).status_code == 403
    assert (await client.get(url, headers=reception)).json()["configured"] is False  # staff may read it
    other_doctor = await clinic.headers_for(clinic.doctor_b.user_id)
    assert (await client.put(url, json=POLICY, headers=other_doctor)).status_code == 403
    patient = await clinic.headers_for(clinic.patient_a.user_id)
    assert (await client.get(url, headers=patient)).status_code == 403
    admin = await clinic.headers_for(clinic.admin.id)
    assert (await client.put(url, json={**POLICY, "consultation_minutes": 45}, headers=admin)).status_code == 200
    assert (await client.put(url, json={**POLICY, "consultation_minutes": 3}, headers=admin)).status_code == 422
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.action == "doctor.scheduling_policy_changed"))
    assert audit is not None and audit.details["after"]["consultation_minutes"] == 45


# ---- overrides and double booking ----------------------------------------------------------


def booking(clinic, patient, starts_at, **extra):
    return {"doctor_id": str(clinic.doctor_a.id), "patient_id": str(patient.id), "starts_at": starts_at.isoformat(), **extra}


async def test_double_booking_needs_permission_reason_and_capacity(client, clinic, db_session):
    await set_policy(client, clinic)  # max_overbook = 1
    reception = await clinic.headers_for(clinic.receptionist.id)
    at = clinic.slot(2, "11:00")
    assert (await client.post(f"{API}/appointments/", json=booking(clinic, clinic.patient_a, at), headers=reception)).status_code == 201

    ordinary = await client.post(f"{API}/appointments/", json=booking(clinic, clinic.patient_b, at), headers=reception)
    assert ordinary.status_code == 409 and ordinary.json()["error"]["code"] == "SLOT_UNAVAILABLE"
    no_reason = await client.post(f"{API}/appointments/", json=booking(clinic, clinic.patient_b, at, double_booking=True), headers=reception)
    assert no_reason.json()["error"]["code"] == "OVERRIDE_REASON_REQUIRED"
    extra = await client.post(
        f"{API}/appointments/", json=booking(clinic, clinic.patient_b, at, double_booking=True, override_reason="Urgent review"),
        headers=reception,
    )
    assert extra.status_code == 201, extra.text
    assert extra.json()["capacity_exception"] is True and extra.json()["override_reason"] == "Urgent review"
    full = await client.post(
        f"{API}/appointments/", json=booking(clinic, clinic.walk_in, at, double_booking=True, override_reason="Another"),
        headers=reception,
    )
    assert full.status_code == 409 and full.json()["error"]["code"] == "OVERBOOK_CAPACITY_REACHED"

    lanes = sorted(await db_session.scalars(select(Appointment.capacity_lane).where(Appointment.doctor_id == clinic.doctor_a.id)))
    assert lanes == [0, 1]
    audit = await db_session.scalar(select(AuditLog).where(AuditLog.action == "appointment.override_booked"))
    assert audit.details["double_booking"] is True and audit.details["reason"] == "Urgent review"
    # Ordinary patients see the time as taken and cannot use overrides at all.
    patient = await clinic.headers_for(clinic.patient_b.user_id)
    attempt = await client.post(f"{API}/appointments/", json={"doctor_id": str(clinic.doctor_a.id), "starts_at": clinic.slot(2, "12:00").isoformat(), "double_booking": True, "override_reason": "x" * 5}, headers=patient)
    assert attempt.status_code == 403


async def test_custom_times_and_lengths_stay_inside_working_hours(client, clinic):
    await set_policy(client, clinic)
    reception = await clinic.headers_for(clinic.receptionist.id)
    custom = await client.post(
        f"{API}/appointments/",
        json=booking(clinic, clinic.patient_a, clinic.slot(2, "10:05"), custom_time=True, duration_minutes=25, override_reason="Fits the lab"),
        headers=reception,
    )
    assert custom.status_code == 201, custom.text
    assert custom.json()["duration_minutes"] == 25
    late = await client.post(
        f"{API}/appointments/", json=booking(clinic, clinic.patient_b, clinic.slot(2, "16:50"), custom_time=True, duration_minutes=20), headers=reception
    )
    assert late.json()["error"]["code"] == "OUTSIDE_WORKING_HOURS"
    odd = await client.post(f"{API}/appointments/", json=booking(clinic, clinic.patient_b, clinic.slot(2, "10:07"), custom_time=True), headers=reception)
    assert odd.json()["error"]["code"] == "INVALID_CUSTOM_TIME"
    # The 10:00 and 10:15 slots overlap 10:05-10:30 and are no longer offered.
    _, times = await free_times(client, clinic.doctor_a.id, (clinic.today + timedelta(days=2)).isoformat())
    assert "10:00" not in times and "10:15" not in times and "10:30" in times


async def test_a_doctor_can_refuse_front_desk_overrides(client, clinic):
    await set_policy(client, clinic, allow_receptionist_overrides=False)
    body = booking(clinic, clinic.patient_a, clinic.slot(2, "10:05"), custom_time=True)
    assert (await client.post(f"{API}/appointments/", json=body, headers=await clinic.headers_for(clinic.receptionist.id))).status_code == 403
    assert (await client.post(f"{API}/appointments/", json=body, headers=await clinic.headers_for(clinic.admin.id))).status_code == 201


async def test_fifo_doctors_give_tokens_not_times(client, clinic, freeze_clock):
    await set_policy(client, clinic, mode="fifo")
    freeze_clock(clinic.slot(1, "09:30"))
    patient = await clinic.headers_for(clinic.patient_a.user_id)
    refused = await client.post(f"{API}/appointments/", json={"doctor_id": str(clinic.doctor_a.id), "starts_at": clinic.slot(1, "11:00").isoformat()}, headers=patient)
    assert refused.json()["error"]["code"] == "FIFO_ONLY"
    token = await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id)}, headers=patient)
    assert token.status_code == 201, token.text
    assert token.json()["state"] == "registered" and token.json()["token_number"] == 1
    again = await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id)}, headers=patient)
    assert again.json()["error"]["code"] == "ALREADY_IN_QUEUE"
    reception = await clinic.headers_for(clinic.receptionist.id)
    arrived = await client.post(f"{API}/queue/entries/{token.json()['id']}/check-in", headers=reception)
    assert arrived.json()["state"] == "waiting" and arrived.json()["position"] == 1


async def test_scheduled_only_doctors_take_no_walk_ins_and_capacity_is_kept(client, clinic, freeze_clock):
    freeze_clock(clinic.slot(1, "09:30"))
    reception = await clinic.headers_for(clinic.receptionist.id)
    await set_policy(client, clinic, mode="scheduled")
    refused = await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_a.id)}, headers=reception)
    assert refused.json()["error"]["code"] == "WALK_INS_NOT_ACCEPTED"
    await set_policy(client, clinic, walk_in_capacity=1)
    ok = await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_a.id)}, headers=reception)
    assert ok.status_code == 201 and ok.json()["state"] == "waiting"
    full = await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_b.id)}, headers=reception)
    assert full.json()["error"]["code"] == "WALK_IN_CAPACITY_REACHED"


# ---- the queue ---------------------------------------------------------------------------


async def test_a_hybrid_session_from_check_in_to_completion(client, clinic, freeze_clock, db_session):
    await set_policy(client, clinic)
    reception = await clinic.headers_for(clinic.receptionist.id)
    doctor = await clinic.headers_for(clinic.doctor_a.user_id)
    freeze_clock(clinic.slot(1, "09:00"))
    booked = (await client.post(f"{API}/appointments/", json=booking(clinic, clinic.patient_a, clinic.slot(1, "10:30")), headers=reception)).json()

    freeze_clock(clinic.slot(1, "10:00"))
    walk_in = (await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_b.id)}, headers=reception)).json()
    assert walk_in["token_number"] == 1
    checked = await client.post(f"{API}/appointments/{booked['id']}/status", json={"status": "checked_in"}, headers=reception)
    assert checked.status_code == 200, checked.text
    assert checked.json()["token_number"] == 2  # tokens follow check-in order

    board = (await client.get(f"{API}/queue/doctors/{clinic.doctor_a.id}", headers=doctor)).json()
    assert [w["token_number"] for w in board["waiting"]] == [1, 2]  # 30 minutes free before 10:30: the walk-in first
    called = (await client.post(f"{API}/queue/doctors/{clinic.doctor_a.id}/call-next", headers=reception)).json()
    assert called["entry"]["token_number"] == 1 and called["may_delay_scheduled"] is False
    again = await client.post(f"{API}/queue/doctors/{clinic.doctor_a.id}/call-next", headers=reception)
    assert again.json()["error"]["code"] == "ALREADY_CALLED"

    assert (await client.post(f"{API}/queue/entries/{walk_in['id']}/start", headers=reception)).status_code == 403  # the doctor starts it
    assert (await client.post(f"{API}/queue/entries/{walk_in['id']}/start", headers=doctor)).json()["state"] == "in_consultation"
    nxt = (await client.post(f"{API}/queue/doctors/{clinic.doctor_a.id}/call-next", headers=doctor)).json()["entry"]
    assert nxt["appointment_id"] == booked["id"]
    blocked = await client.post(f"{API}/queue/entries/{nxt['id']}/start", headers=doctor)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "CONSULTATION_IN_PROGRESS"
    assert (await client.post(f"{API}/queue/entries/{walk_in['id']}/complete", headers=doctor)).json()["state"] == "completed"
    assert (await client.post(f"{API}/queue/entries/{nxt['id']}/start", headers=doctor)).json()["state"] == "in_consultation"
    assert (await client.post(f"{API}/queue/entries/{nxt['id']}/complete", headers=doctor)).status_code == 200
    appointment = (await client.get(f"{API}/appointments/{booked['id']}", headers=reception)).json()
    assert appointment["status"] == "completed" and appointment["queue_state"] == "completed"
    actions = set(await db_session.scalars(select(AuditLog.action).where(AuditLog.target_type == "queue_entry")))
    assert {"queue.walk_in_registered", "queue.called", "queue.started", "queue.completed"} <= actions


async def test_booked_patients_have_priority_at_their_time_and_nobody_is_auto_no_show(client, clinic, freeze_clock):
    await set_policy(client, clinic)
    reception = await clinic.headers_for(clinic.receptionist.id)
    freeze_clock(clinic.slot(1, "09:00"))
    booked = (await client.post(f"{API}/appointments/", json=booking(clinic, clinic.patient_a, clinic.slot(1, "10:00")), headers=reception)).json()
    absent = (await client.post(f"{API}/appointments/", json=booking(clinic, clinic.walk_in, clinic.slot(1, "09:30")), headers=reception)).json()
    freeze_clock(clinic.slot(1, "09:50"))
    await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_b.id)}, headers=reception)
    freeze_clock(clinic.slot(1, "10:05"))
    await client.post(f"{API}/appointments/{booked['id']}/status", json={"status": "checked_in"}, headers=reception)
    called = (await client.post(f"{API}/queue/doctors/{clinic.doctor_a.id}/call-next", headers=reception)).json()
    assert called["entry"]["appointment_id"] == booked["id"]  # reserved 10:00 beats the 09:50 walk-in

    board = (await client.get(f"{API}/queue/doctors/{clinic.doctor_a.id}", headers=reception)).json()
    late = next(a for a in board["not_arrived"] if a["appointment_id"] == absent["id"])
    assert late["late"] is True and late["status"] == "scheduled"  # late, but not marked a no-show


async def test_staff_adjust_the_queue_and_every_change_is_audited(client, clinic, freeze_clock, db_session):
    await set_policy(client, clinic)
    reception = await clinic.headers_for(clinic.receptionist.id)
    freeze_clock(clinic.slot(1, "10:00"))
    first = (await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_a.id)}, headers=reception)).json()
    freeze_clock(clinic.slot(1, "10:05"))
    second = (await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_b.id)}, headers=reception)).json()
    assert second["position"] == 2

    assert (await client.post(f"{API}/queue/entries/{second['id']}/prioritize", json={"note": "Severe pain"}, headers=reception)).json()["position"] == 1
    assert (await client.post(f"{API}/queue/entries/{second['id']}/defer", json={"minutes": 20}, headers=reception)).json()["position"] == 2
    absent = (await client.post(f"{API}/queue/entries/{first['id']}/absent", headers=reception)).json()
    assert absent["state"] == "absent" and absent["position"] is None
    freeze_clock(clinic.slot(1, "10:30"))
    back = (await client.post(f"{API}/queue/entries/{first['id']}/check-in", headers=reception)).json()
    assert back["state"] == "waiting" and back["checked_in_at"].startswith(clinic.slot(1, "10:30").isoformat()[:16])  # rejoins by the new time
    gone = (await client.post(f"{API}/queue/entries/{second['id']}/no-show", headers=reception)).json()
    assert gone["state"] == "no_show"
    actions = list(await db_session.scalars(select(AuditLog.action).where(AuditLog.target_type == "queue_entry")))
    for action in ("queue.prioritized", "queue.deferred", "queue.marked_absent", "queue.checked_in", "queue.marked_no_show"):
        assert action in actions


async def test_patients_see_only_their_own_place(client, clinic, freeze_clock):
    await set_policy(client, clinic)
    reception = await clinic.headers_for(clinic.receptionist.id)
    freeze_clock(clinic.slot(1, "10:00"))
    await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_b.id)}, headers=reception)
    await client.post(f"{API}/queue/walk-ins", json={"doctor_id": str(clinic.doctor_a.id), "patient_id": str(clinic.patient_a.id)}, headers=reception)
    patient = await clinic.headers_for(clinic.patient_a.user_id)
    [mine] = (await client.get(f"{API}/queue/me", headers=patient)).json()
    assert mine["position"] == 2 and mine["estimated_wait"]["min_minutes"] < mine["estimated_wait"]["max_minutes"]
    assert "patient_name" not in mine and "Bob" not in str(mine)
    assert (await client.get(f"{API}/queue/doctors/{clinic.doctor_a.id}", headers=patient)).status_code == 403
    assert (await client.get(f"{API}/queue/sessions", headers=patient)).status_code == 403
    sessions = (await client.get(f"{API}/queue/sessions", headers=reception)).json()
    mine_session = next(s for s in sessions if s["doctor_id"] == str(clinic.doctor_a.id))
    assert mine_session["waiting"] == 2 and mine_session["hours"] == [["09:00", "17:00"]]


# ---- tokens under concurrency (separate connections, committed data) --------------------------


async def test_concurrent_check_ins_never_share_a_token():
    """Ten sessions ask for a token for one doctor and day at the same moment."""
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    day = date(2099, 1, int.from_bytes(os.urandom(1), "big") % 28 + 1)
    doctor_id = await _committed_doctor(engine)
    try:
        async def take() -> int:
            async with AsyncSession(engine) as session:
                token = await queue_service.next_token(session, doctor_id, day)
                await asyncio.sleep(0.05)
                await session.commit()
                return token

        tokens = await asyncio.gather(*(take() for _ in range(10)))
        assert sorted(tokens) == list(range(1, 11))
    finally:
        await _drop_committed_doctor(engine, doctor_id)
        await engine.dispose()


async def _committed_doctor(engine) -> uuid.UUID:
    from app.models import Department, Doctor, User
    from tests.conftest import TEST_PASSWORD_HASH

    tag = os.urandom(3).hex()
    async with AsyncSession(engine, expire_on_commit=False) as s:
        dept = Department(name=f"Token {tag}", timezone="Asia/Karachi")
        user = User(name="Token Doctor", email=f"token-{tag}@example.com", password_hash=TEST_PASSWORD_HASH)
        s.add_all([dept, user])
        await s.flush()
        doctor = Doctor(user_id=user.id, department_id=dept.id, specialization="GP")
        s.add(doctor)
        await s.commit()
        return doctor.id


async def _drop_committed_doctor(engine, doctor_id: uuid.UUID) -> None:
    from app.models import Department, Doctor, TokenCounter, User

    async with AsyncSession(engine) as s:
        doctor = await s.get(Doctor, doctor_id)
        await s.execute(delete(TokenCounter).where(TokenCounter.doctor_id == doctor_id))
        await s.execute(delete(Doctor).where(Doctor.id == doctor_id))
        await s.execute(delete(User).where(User.id == doctor.user_id))
        await s.execute(delete(Department).where(Department.id == doctor.department_id))
        await s.commit()

