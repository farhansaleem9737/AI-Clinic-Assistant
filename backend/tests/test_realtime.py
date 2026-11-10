"""Live updates (D122): tickets, the socket, the hub and the commit hooks.

No database: principals are faked and the commit hooks are exercised on an
in-memory SQLite session with a stand-in model. Runs alone, fast, with
``pytest tests/test_realtime.py --noconftest``; also passes in the full suite.
(tests/test_realtime_events.py checks the real booking path on PostgreSQL.)
"""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.orm.attributes import set_committed_value
from starlette.websockets import WebSocketDisconnect

from app.api.deps.auth import get_current_principal
from app.api.v1.endpoints import realtime as endpoint
from app.core.config import Environment, settings
from app.core.permissions import Perm, Principal
from app.core.rate_limit import limiter
from app.main import app
from app.models.appointment import Appointment, AppointmentStatus
from app.models.doctor_application import ApplicationStatus, DoctorApplication
from app.models.health_record import PatientDiagnosis
from app.models.notification import Notification
from app.models.rbac import UserRole
from app.models.scheduling import QueueEntry
from app.realtime import capture
from app.realtime.events import (
    CLINIC,
    REVIEWERS,
    STAFF,
    Event,
    channels_for,
    doctor_channel,
    patient_channel,
    record_channel,
    user_channel,
)
from app.realtime.hub import GOING_AWAY, POLICY, RECONNECT, TOO_MANY, TOO_SLOW, UNAUTHORIZED, Connection, hub
from app.realtime.tickets import tickets

WS = "/api/v1/ws"
TICKET = "/api/v1/realtime/ticket"

PATIENT_PERMS = {Perm.appointment_read_own, Perm.availability_read}
DOCTOR_PERMS = {Perm.appointment_read_assigned, Perm.availability_read}
STAFF_PERMS = {Perm.appointment_read_any, Perm.availability_read}


def principal(perms=(), *, patient_id=None, doctor_id=None, active=True) -> Principal:
    user = SimpleNamespace(id=uuid.uuid4(), is_active=active, name="Test")
    return Principal(
        user=user, roles=frozenset(), permissions=frozenset(str(p) for p in perms), doctor_id=doctor_id, patient_id=patient_id
    )


@pytest.fixture
def people(monkeypatch):
    """Registered fake accounts: the socket's database lookup reads from here."""
    known: dict[uuid.UUID, Principal | None] = {}

    async def fake_load(user_id, *, require_session=False):
        return known.get(user_id)

    monkeypatch.setattr(endpoint, "load_principal", fake_load)
    monkeypatch.setattr(settings, "environment", Environment.development)
    monkeypatch.setattr(settings, "realtime_enabled", True)
    tickets.clear()
    limiter.reset()

    def add(p: Principal) -> Principal:
        known[p.user_id] = p
        return p

    add.known = known
    yield add
    app.dependency_overrides.pop(get_current_principal, None)
    tickets.clear()
    assert hub.connection_count == 0, "a connection was left registered"


@pytest.fixture
def client():
    return TestClient(app)


def open_socket(client, p: Principal, **kwargs):
    ws = client.websocket_connect(WS, **kwargs).__enter__()
    ws.send_text(json.dumps({"type": "auth", "ticket": tickets.issue(p.user_id)}))
    assert ws.receive_json() == {"type": "ready", "version": 1}
    return ws


def hang_up(ws) -> None:
    """Close from the client and let the server finish before the test client
    tears the session down (its exit cancels the server task immediately)."""
    before = hub.connection_count
    try:
        ws.close(1000)
    except Exception:  # the server already closed it
        pass
    deadline = time.monotonic() + 2
    while hub.connection_count >= before > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    ws.__exit__(None, None, None)


def publish(ws, event: Event) -> None:
    """On the app's own event loop, as a commit hook would."""
    ws.portal.call(hub.publish, event)


def close_code(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as exc:
        while True:
            ws.receive_text()
    return exc.value.code


def note(channel: str, kind="appointment.created") -> Event:
    return Event(kind, "appointment", str(uuid.uuid4()), frozenset({channel}), {"doctor_id": "d"})


# ============================== tickets and the handshake ================================


def test_the_ticket_needs_a_signed_in_caller(client, people):
    assert client.post(TICKET).status_code == 401
    me = people(principal(PATIENT_PERMS))
    app.dependency_overrides[get_current_principal] = lambda: me
    body = client.post(TICKET).json()
    assert body["expires_in"] == settings.ws_ticket_ttl_seconds and len(body["ticket"]) >= 40


def test_a_valid_ticket_opens_the_socket_and_ping_is_answered(client, people):
    me = people(principal(PATIENT_PERMS, patient_id=uuid.uuid4()))
    app.dependency_overrides[get_current_principal] = lambda: me
    ticket = client.post(TICKET).json()["ticket"]
    ws = client.websocket_connect(WS).__enter__()
    try:
        ws.send_text(json.dumps({"type": "auth", "ticket": ticket}))
        assert ws.receive_json()["type"] == "ready"
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json() == {"type": "pong"}
    finally:
        hang_up(ws)


@pytest.mark.parametrize("first_message", ["not json", '{"type":"auth"}', '{"type":"auth","ticket":"made-up-ticket-value-123456"}', '{"type":"ping"}'])
def test_missing_or_invalid_credentials_are_refused(client, people, first_message):
    with client.websocket_connect(WS) as ws:
        ws.send_text(first_message)
        assert close_code(ws) == UNAUTHORIZED


def test_an_expired_ticket_is_refused(client, people):
    me = people(principal(PATIENT_PERMS))
    with client.websocket_connect(WS) as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": tickets.issue(me.user_id, ttl_seconds=-1)}))
        assert close_code(ws) == UNAUTHORIZED


def test_a_ticket_works_once(client, people):
    me = people(principal(PATIENT_PERMS))
    ticket = tickets.issue(me.user_id)
    ws = client.websocket_connect(WS).__enter__()
    try:
        ws.send_text(json.dumps({"type": "auth", "ticket": ticket}))
        assert ws.receive_json()["type"] == "ready"
        with client.websocket_connect(WS) as again:
            again.send_text(json.dumps({"type": "auth", "ticket": ticket}))
            assert close_code(again) == UNAUTHORIZED
    finally:
        hang_up(ws)


def test_a_deactivated_account_cannot_connect(client, people):
    me = principal(PATIENT_PERMS)
    people.known[me.user_id] = None  # what load_principal answers for an inactive user
    with client.websocket_connect(WS) as ws:
        ws.send_text(json.dumps({"type": "auth", "ticket": tickets.issue(me.user_id)}))
        assert close_code(ws) == UNAUTHORIZED


def test_outside_development_only_listed_origins_may_connect(client, people, monkeypatch):
    monkeypatch.setattr(settings, "environment", Environment.production)
    monkeypatch.setattr(settings, "cors_origins", ["https://clinic.example.com"])
    monkeypatch.setattr(settings, "ws_allowed_origins", [])
    for headers in ({"origin": "https://evil.example.com"}, {}):
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(WS, headers=headers):
                pass
        assert exc.value.code == POLICY
    me = people(principal(PATIENT_PERMS))
    ws = open_socket(client, me, headers={"origin": "https://clinic.example.com"})
    hang_up(ws)


def test_switched_off_means_no_tickets_and_no_sockets(client, people, monkeypatch):
    monkeypatch.setattr(settings, "realtime_enabled", False)
    me = people(principal(PATIENT_PERMS))
    app.dependency_overrides[get_current_principal] = lambda: me
    assert client.post(TICKET).json()["error"]["code"] == "REALTIME_DISABLED"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(WS):
            pass


# ============================== who hears what ===========================================


def test_channels_come_from_verified_identity_and_permissions():
    pid, did = uuid.uuid4(), uuid.uuid4()
    patient = principal(PATIENT_PERMS, patient_id=pid)
    assert channels_for(patient) == {user_channel(patient.user_id), patient_channel(pid), CLINIC}
    doctor = principal(DOCTOR_PERMS, doctor_id=did)
    assert channels_for(doctor) == {user_channel(doctor.user_id), doctor_channel(did), CLINIC}
    reception = principal(STAFF_PERMS)
    assert STAFF in channels_for(reception)
    # An id without the matching permission is not enough.
    assert patient_channel(pid) not in channels_for(principal(patient_id=pid))


def test_each_role_hears_only_its_own_events(client, people):
    pid, other_pid, did, other_did = (uuid.uuid4() for _ in range(4))
    patient = open_socket(client, people(principal(PATIENT_PERMS, patient_id=pid)))
    doctor = open_socket(client, people(principal(DOCTOR_PERMS, doctor_id=did)))
    reception = open_socket(client, people(principal(STAFF_PERMS)))
    admin = open_socket(client, people(principal({Perm.appointment_read_any, Perm.user_read})))
    try:
        # Someone else's appointment: none of them but the staff hear it.
        publish(patient, Event("appointment.created", "appointment", "x", frozenset({patient_channel(other_pid), doctor_channel(other_did), STAFF})))
        mine = Event("appointment.cancelled", "appointment", "y", frozenset({patient_channel(pid), doctor_channel(did), STAFF}))
        publish(patient, mine)
        assert patient.receive_json()["resource_id"] == "y"  # "x" was never sent to them
        assert doctor.receive_json()["resource_id"] == "y"
        assert [reception.receive_json()["resource_id"] for _ in range(2)] == ["x", "y"]
        assert [admin.receive_json()["resource_id"] for _ in range(2)] == ["x", "y"]
    finally:
        for ws in (patient, doctor, reception, admin):
            hang_up(ws)


def test_the_client_cannot_subscribe_itself_to_other_channels(client, people):
    me = people(principal(PATIENT_PERMS, patient_id=uuid.uuid4()))
    ws = open_socket(client, me)
    try:
        ws.send_text(json.dumps({"type": "subscribe", "channel": doctor_channel(uuid.uuid4())}))
        assert ws.receive_json() == {"type": "error", "code": "UNSUPPORTED_MESSAGE"}
        publish(ws, note(STAFF))
        publish(ws, note(user_channel(me.user_id), "notification.created"))
        assert ws.receive_json()["type"] == "notification.created"  # the staff event never came
    finally:
        hang_up(ws)


def test_every_tab_of_a_user_hears_their_events(client, people):
    me = people(principal(PATIENT_PERMS))
    tabs = [open_socket(client, me) for _ in range(3)]
    try:
        assert hub.connections_of(me.user_id) == 3
        publish(tabs[0], note(user_channel(me.user_id), "notification.read"))
        for tab in tabs:
            event = tab.receive_json()
            assert event["type"] == "notification.read" and event["version"] == 1
    finally:
        for tab in tabs:
            hang_up(tab)


# ============================== lifecycle and limits =====================================


def test_closing_unregisters_and_reconnecting_works(client, people):
    me = people(principal(PATIENT_PERMS))
    ws = open_socket(client, me)
    assert hub.connections_of(me.user_id) == 1
    hang_up(ws)
    assert hub.connections_of(me.user_id) == 0 and hub.channel_count() == 0
    again = open_socket(client, me)  # a fresh ticket, a fresh connection
    publish(again, note(user_channel(me.user_id)))
    assert again.receive_json()["type"] == "appointment.created"
    hang_up(again)


def test_connections_per_user_are_limited(client, people, monkeypatch):
    monkeypatch.setattr(settings, "ws_max_connections_per_user", 2)
    me = people(principal(PATIENT_PERMS))
    tabs = [open_socket(client, me) for _ in range(2)]
    with client.websocket_connect(WS) as third:
        third.send_text(json.dumps({"type": "auth", "ticket": tickets.issue(me.user_id)}))
        assert close_code(third) == TOO_MANY
    for tab in tabs:
        hang_up(tab)


def test_oversized_or_flooding_messages_close_the_socket(client, people):
    me = people(principal(PATIENT_PERMS))
    ws = open_socket(client, me)
    ws.send_text("x" * 5000)
    assert close_code(ws) == POLICY
    hang_up(ws)
    ws = open_socket(client, me)
    for _ in range(40):
        ws.send_text('{"type":"ping"}')
    assert close_code(ws) == POLICY
    hang_up(ws)


def test_a_signed_out_or_deactivated_account_is_disconnected(client, people, monkeypatch):
    monkeypatch.setattr(settings, "ws_revalidate_seconds", 0.05)
    me = people(principal(PATIENT_PERMS))
    ws = open_socket(client, me)
    people.known[me.user_id] = None
    assert close_code(ws) == UNAUTHORIZED
    hang_up(ws)


def test_shutdown_closes_every_socket_so_clients_reconnect(client, people):
    me = people(principal(PATIENT_PERMS))
    ws = open_socket(client, me)
    ws.portal.call(hub.shutdown)
    assert close_code(ws) == GOING_AWAY
    hang_up(ws)


def test_a_client_that_falls_behind_is_dropped_without_blocking_others():
    async def scenario():
        slow = Connection(uuid.uuid4(), frozenset({"c"}), queue_size=2)
        fast = Connection(uuid.uuid4(), frozenset({"c"}), queue_size=10)
        for c in (slow, fast):
            assert hub.register(c)
        try:
            for i in range(3):  # publish never waits for anyone
                hub.publish(note("c"))
            assert slow.closed.is_set() and slow.close_code == TOO_SLOW
            assert fast.outbox.qsize() == 3 and not fast.closed.is_set()
        finally:
            hub.unregister(slow)
            hub.unregister(fast)

    asyncio.run(scenario())


def test_a_send_that_hangs_times_out(monkeypatch):
    monkeypatch.setattr(settings, "ws_send_timeout_seconds", 0.05)

    class Stuck:
        async def send_text(self, _):
            await asyncio.sleep(10)

    async def scenario():
        conn = Connection(uuid.uuid4(), frozenset())
        conn.offer("{}")
        await asyncio.wait_for(endpoint._send(Stuck(), conn), timeout=2)
        assert conn.close_code == TOO_SLOW

    asyncio.run(scenario())


# ============================== events from committed changes ============================


class _Base(DeclarativeBase):
    pass


class Thing(_Base):
    __tablename__ = "things"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(20))


class EventList(list):
    closed: list


@pytest.fixture
def published(monkeypatch):
    sent = EventList()
    sent.closed = []  # (user_id, code) of sockets closed after commit
    monkeypatch.setattr(capture, "hub", SimpleNamespace(publish=sent.append, close_user=lambda u, c, r: sent.closed.append((u, c))))
    monkeypatch.setitem(
        capture.HANDLERS, Thing, lambda row, change, changed: [Event(f"thing.{change}", "thing", row.name, frozenset({"c"}))]
    )
    return sent


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_events_are_published_only_after_commit(session, published):
    session.add(Thing(name="a"))
    session.flush()
    assert published == []  # flushed, not committed
    session.commit()
    assert [(e.type, e.resource_id) for e in published] == [("thing.new", "a")]


def test_a_rollback_publishes_nothing(session, published):
    session.add(Thing(name="a"))
    session.flush()
    session.rollback()
    session.commit()
    assert published == []


def test_a_rolled_back_savepoint_drops_only_its_own_events(session, published):
    session.add(Thing(name="kept"))
    session.flush()
    savepoint = session.begin_nested()
    session.add(Thing(name="undone"))
    session.flush()
    savepoint.rollback()
    with session.begin_nested():
        session.add(Thing(name="released"))
    session.commit()
    assert [e.resource_id for e in published] == ["kept", "released"]


def test_the_same_change_is_published_once(session, published):
    thing = Thing(name="a")
    session.add(thing)
    session.flush()
    capture.emit(session, Event("thing.new", "thing", "a", frozenset({"c"})))
    session.commit()
    assert len(published) == 1


def test_an_untouched_row_publishes_nothing(session, published):
    session.add(Thing(name="a"))
    session.commit()
    published.clear()
    thing = session.get(Thing, 1)
    thing.name = "a"  # same value
    session.commit()
    assert published == []


# ---- what an appointment change means (no PHI in the payload) ----------------------------


def _appointment(**changes) -> Appointment:
    start = datetime(2026, 11, 10, 4, 0, tzinfo=UTC)  # 09:00 in Karachi
    appt = Appointment(id=uuid.uuid4(), patient_id=uuid.uuid4(), doctor_id=uuid.uuid4(), starts_at=start,
                       ends_at=start + timedelta(minutes=15), status=AppointmentStatus.scheduled, reason="private reason")
    for name in ("starts_at", "ends_at", "status", "reason"):
        set_committed_value(appt, name, getattr(appt, name))
    for name, value in changes.items():
        setattr(appt, name, value)
    return appt


@pytest.fixture
def karachi(monkeypatch):
    monkeypatch.setattr(settings, "clinic_timezone", "Asia/Karachi")


def test_new_and_cancelled_appointments_also_change_availability(karachi):
    appt = _appointment()
    created = capture.appointment_events(appt, "new", frozenset())
    assert [e.type for e in created] == ["appointment.created", "availability.changed"]
    assert created[0].channels == {patient_channel(appt.patient_id), doctor_channel(appt.doctor_id), STAFF}
    assert created[1].channels == {CLINIC} and created[1].payload == {"doctor_id": str(appt.doctor_id), "date": "2026-11-10"}
    assert "private reason" not in created[0].to_json() and "reason" not in created[0].payload

    cancelled = _appointment(status=AppointmentStatus.cancelled)
    events = capture.appointment_events(cancelled, "dirty", frozenset({"status"}))
    assert [e.type for e in events] == ["appointment.cancelled", "availability.changed"]
    assert events[0].payload["previous_status"] == "scheduled"


def test_status_steps_and_edits_do_not_touch_availability(karachi):
    confirmed = _appointment(status=AppointmentStatus.confirmed)
    assert [e.type for e in capture.appointment_events(confirmed, "dirty", frozenset({"status"}))] == ["appointment.status_changed"]
    edited = _appointment(reason="new")
    assert [e.type for e in capture.appointment_events(edited, "dirty", frozenset({"reason"}))] == ["appointment.updated"]


def test_a_moved_appointment_frees_the_old_date_and_takes_the_new(karachi):
    later = datetime(2026, 11, 12, 4, 0, tzinfo=UTC)
    moved = _appointment(starts_at=later, ends_at=later + timedelta(minutes=15))
    events = capture.appointment_events(moved, "dirty", frozenset({"starts_at", "ends_at"}))
    assert events[0].type == "appointment.rescheduled"
    assert sorted(e.payload["date"] for e in events[1:]) == ["2026-11-10", "2026-11-12"]


def test_queue_and_notification_events_name_no_one():
    entry = QueueEntry(id=uuid.uuid4(), doctor_id=uuid.uuid4(), patient_id=uuid.uuid4(), session_date=datetime(2026, 11, 10).date(), token_number=4)
    own, everyone = capture.queue_events(entry, "new", frozenset())
    assert own.resource_id == str(entry.id) and patient_channel(entry.patient_id) in own.channels and CLINIC not in own.channels
    assert everyone.resource_id is None and everyone.channels == {CLINIC}
    assert own.payload == everyone.payload == {"doctor_id": str(entry.doctor_id), "session_date": "2026-11-10"}
    n = Notification(id=uuid.uuid4(), user_id=uuid.uuid4(), type="x", title="Private", message="Private")
    (created,) = capture.notification_events(n, "new", frozenset())
    assert created.channels == {user_channel(n.user_id)} and "Private" not in created.to_json()


# ============================== ending access at once ====================================


def test_ended_sessions_close_sockets_after_commit_only(session, published):
    user = uuid.uuid4()
    capture.end_sessions(session, user)
    session.rollback()
    session.commit()
    assert published.closed == []  # the deactivation did not happen
    capture.end_sessions(session, user)
    capture.roles_changed(session, user)
    session.commit()
    assert published.closed == [(user, UNAUTHORIZED)]  # ending outranks a reconnect


def test_a_role_change_asks_for_a_reconnect():
    link = UserRole(user_id=uuid.uuid4(), role_id=1)
    (action,) = capture.role_changes(link, "new", frozenset())
    assert (action.user_id, action.code) == (link.user_id, RECONNECT)


def test_closing_a_user_reaches_every_tab_with_the_code(client, people):
    me = people(principal(PATIENT_PERMS))
    tabs = [open_socket(client, me) for _ in range(2)]
    tabs[0].portal.call(hub.close_user, me.user_id, UNAUTHORIZED, "session ended")
    assert [close_code(tab) for tab in tabs] == [UNAUTHORIZED, UNAUTHORIZED]
    for tab in tabs:
        hang_up(tab)
    other = open_socket(client, me)
    other.portal.call(hub.close_user, me.user_id, RECONNECT, "roles changed")
    assert close_code(other) == RECONNECT
    hang_up(other)


# ============================== watching a patient's record ==============================


@pytest.fixture
def allowed(monkeypatch):
    """Patients the (fake) doctor may read; the real check is health_record_service.may_read."""
    ok: set[uuid.UUID] = set()

    async def fake_may_watch(user_id, patient_id):
        return patient_id in ok

    monkeypatch.setattr(endpoint, "may_watch", fake_may_watch)
    return ok


def test_a_treating_doctor_watches_a_record_and_hears_its_changes(client, people, allowed):
    mine, not_mine = uuid.uuid4(), uuid.uuid4()
    allowed.add(mine)
    doctor = open_socket(client, people(principal(DOCTOR_PERMS, doctor_id=uuid.uuid4())))
    try:
        doctor.send_json({"type": "watch", "patient_id": str(not_mine)})
        assert doctor.receive_json() == {"type": "error", "code": "WATCH_DENIED", "patient_id": str(not_mine)}
        doctor.send_json({"type": "watch", "patient_id": str(mine)})
        assert doctor.receive_json() == {"type": "watching", "patient_id": str(mine)}
        other = PatientDiagnosis(id=uuid.uuid4(), patient_id=not_mine, condition="x")
        publish(doctor, capture.health_record_events(other, "new", frozenset())[0])
        diagnosis = PatientDiagnosis(id=uuid.uuid4(), patient_id=mine, condition="Private condition")
        publish(doctor, capture.health_record_events(diagnosis, "new", frozenset())[0])
        event = doctor.receive_json()  # the other patient's change never came
        assert event["payload"] == {"patient_id": str(mine), "kind": "diagnoses"}
        assert "Private" not in json.dumps(event)
        doctor.send_json({"type": "unwatch", "patient_id": str(mine)})
        publish(doctor, capture.health_record_events(diagnosis, "dirty", frozenset({"status"}))[0])
        doctor.send_text('{"type":"ping"}')
        assert doctor.receive_json() == {"type": "pong"}  # nothing in between
    finally:
        hang_up(doctor)


def test_watches_are_limited_and_checked(client, people, allowed, monkeypatch):
    monkeypatch.setattr(endpoint, "MAX_WATCHES", 1)
    first, second = uuid.uuid4(), uuid.uuid4()
    allowed.update({first, second})
    ws = open_socket(client, people(principal(DOCTOR_PERMS, doctor_id=uuid.uuid4())))
    try:
        ws.send_json({"type": "watch", "patient_id": "not-an-id"})
        assert ws.receive_json()["code"] == "INVALID_MESSAGE"
        ws.send_json({"type": "watch", "patient_id": str(first)})
        assert ws.receive_json()["type"] == "watching"
        ws.send_json({"type": "watch", "patient_id": str(second)})
        assert ws.receive_json()["code"] == "WATCH_LIMIT"
    finally:
        hang_up(ws)


def test_a_watch_is_dropped_when_access_ends(client, people, allowed, monkeypatch):
    monkeypatch.setattr(settings, "ws_revalidate_seconds", 0.05)
    patient = uuid.uuid4()
    allowed.add(patient)
    ws = open_socket(client, people(principal(DOCTOR_PERMS, doctor_id=uuid.uuid4())))
    try:
        ws.send_json({"type": "watch", "patient_id": str(patient)})
        assert ws.receive_json()["type"] == "watching"
        allowed.clear()  # e.g. no longer this patient's doctor
        time.sleep(0.3)  # a few revalidations
        change = Event("health_record.updated", "health_record", "r", frozenset({record_channel(patient)}), {"patient_id": str(patient)})
        publish(ws, change)
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json() == {"type": "pong"}
    finally:
        hang_up(ws)


def test_the_patient_hears_their_own_record_without_watching():
    pid = uuid.uuid4()
    row = PatientDiagnosis(id=uuid.uuid4(), patient_id=pid, condition="x")
    (event,) = capture.health_record_events(row, "new", frozenset())
    assert event.channels == {patient_channel(pid), record_channel(pid)}


# ============================== doctor applications ======================================


def test_application_changes_reach_reviewers_and_the_applicant_only():
    application = DoctorApplication(id=uuid.uuid4(), user_id=uuid.uuid4(), status=ApplicationStatus.approved)
    (event,) = capture.application_events(application, "dirty", frozenset({"status"}))
    assert event.channels == {REVIEWERS, user_channel(application.user_id)} and event.payload == {"status": "approved"}
    assert capture.application_events(application, "dirty", frozenset({"bio"})) == []
    reviewer = principal({Perm.doctor_application_review})
    assert REVIEWERS in channels_for(reviewer) and REVIEWERS not in channels_for(principal(PATIENT_PERMS))
