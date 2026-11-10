"""Turn committed database changes into real-time events (D122).

Business services do not know about sockets. This module watches every
SQLAlchemy session:

- after each flush it notes which appointments, queue entries, schedules and
  notifications were added or changed, as events tied to the (sub)transaction
  they were flushed in;
- when the outermost transaction **commits**, the events are published (each
  once), except those of savepoints that were rolled back;
- when it rolls back, they are dropped. A failed booking sends nothing.

Changes made with bulk SQL (``insert()``/``update()`` statements) are not
seen by the session; those few places call ``emit`` themselves (e.g.
``notification_service.mark_all_read``).

Delivery is best effort (in memory, this process): a client that was not
connected re-reads its data when it reconnects, so nothing depends on an
event arriving.
"""

import logging
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import event as sa_event
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from app.core.config import settings
from app.models.appointment import ACTIVE_STATUSES, Appointment, AppointmentStatus
from app.models.doctor_application import DoctorApplication
from app.models.health_record import PatientAllergy, PatientDiagnosis, PatientMedication
from app.models.notification import Notification
from app.models.rbac import UserRole
from app.models.schedule import ScheduleException, ScheduleTemplate
from app.models.scheduling import QueueEntry, SchedulingPolicy
from app.realtime.events import (
    CLINIC,
    REVIEWERS,
    STAFF,
    Event,
    doctor_channel,
    patient_channel,
    record_channel,
    user_channel,
)
from app.realtime.hub import RECONNECT, UNAUTHORIZED, hub

logger = logging.getLogger(__name__)

PENDING = "realtime_pending"  # session.info: [(transaction, event)]
ROLLED_BACK = "realtime_rolled_back"  # session.info: {savepoint transactions rolled back}



@dataclass(frozen=True)
class Disconnect:
    """After commit, close a user's sockets: UNAUTHORIZED (sessions ended) stops
    them; RECONNECT (roles changed) makes them reconnect with fresh channels."""

    user_id: uuid.UUID
    code: int
    reason: str


# A handler turns one changed row into events or disconnects:
# (row, "new" | "dirty" | "deleted", changed attribute names).
Handler = Callable[[object, str, frozenset[str]], list]


# ---- what each kind of row means ------------------------------------------------------


def _local_date(instant: datetime | None) -> str | None:
    if instant is None:
        return None
    return instant.astimezone(ZoneInfo(settings.clinic_timezone)).date().isoformat()


def _previous(row, attribute: str):
    """The value before this transaction's change, if it changed."""
    deleted = inspect(row).attrs[attribute].history.deleted
    return deleted[0] if deleted else None


def _holds_slot(status) -> bool:
    return status in ACTIVE_STATUSES


def appointment_events(appt: Appointment, change: str, changed: frozenset[str]) -> list[Event]:
    date = _local_date(appt.starts_at)
    status = str(appt.status) if appt.status is not None else None
    payload = {"doctor_id": str(appt.doctor_id), "patient_id": str(appt.patient_id), "date": date, "status": status}
    dates_freed_or_taken: set[str | None] = set()

    if change == "new":
        kind = "appointment.rescheduled" if appt.rescheduled_from_id else "appointment.created"
        dates_freed_or_taken.add(date)
    elif change == "deleted":
        kind = "appointment.cancelled"
        dates_freed_or_taken.add(date)
    elif "status" in changed:
        before = _previous(appt, "status")
        kind = "appointment.cancelled" if appt.status == AppointmentStatus.cancelled else "appointment.status_changed"
        if before is not None:
            payload["previous_status"] = str(before)
        if _holds_slot(before) != _holds_slot(appt.status):
            dates_freed_or_taken.add(date)
    elif changed & {"starts_at", "ends_at", "doctor_id"}:
        kind = "appointment.rescheduled"
        dates_freed_or_taken |= {date, _local_date(_previous(appt, "starts_at"))}
    else:
        kind = "appointment.updated"

    channels = frozenset({patient_channel(appt.patient_id), doctor_channel(appt.doctor_id), STAFF})
    events = [Event(kind, "appointment", str(appt.id), channels, payload)]
    # Everyone looking at this doctor's free times: which day changed, nothing about who.
    for day in sorted(d for d in dates_freed_or_taken if d):
        events.append(Event("availability.changed", "availability", str(appt.doctor_id), frozenset({CLINIC}),
                            {"doctor_id": str(appt.doctor_id), "date": day}))
    return events


def schedule_events(row, change: str, changed: frozenset[str]) -> list[Event]:
    doctor = str(row.doctor_id)
    return [
        Event("schedule.updated", "schedule", doctor, frozenset({doctor_channel(row.doctor_id), STAFF}), {"doctor_id": doctor}),
        # Working hours or leave changed: any of this doctor's dates may have changed.
        Event("availability.changed", "availability", doctor, frozenset({CLINIC}), {"doctor_id": doctor, "date": None}),
    ]


def queue_events(entry: QueueEntry, change: str, changed: frozenset[str]) -> list[Event]:
    # Positions are worked out by the API when each page re-reads the queue,
    # so no position or patient is sent. The entry's own patient, the doctor and
    # the front desk get the entry id; everyone else only "this session changed"
    # (patients waiting in the same queue re-read their place).
    payload = {"doctor_id": str(entry.doctor_id), "session_date": entry.session_date.isoformat()}
    own = frozenset({doctor_channel(entry.doctor_id), STAFF, patient_channel(entry.patient_id)})
    return [
        Event("queue.updated", "queue", str(entry.id), own, payload),
        Event("queue.updated", "queue", None, frozenset({CLINIC}), payload),
    ]


def notification_events(note: Notification, change: str, changed: frozenset[str]) -> list[Event]:
    if change == "new":
        kind = "notification.created"
    elif "read_at" in changed:
        kind = "notification.read"
    else:
        return []
    return [Event(kind, "notification", str(note.id), frozenset({user_channel(note.user_id)}))]


def health_record_events(row, change: str, changed: frozenset[str]) -> list[Event]:
    # The patient's own page, and treating doctors watching this patient (a
    # "watch" the server authorized). Which list changed; never its content.
    kind = {PatientAllergy: "allergies", PatientDiagnosis: "diagnoses", PatientMedication: "medications"}[type(row)]
    channels = frozenset({patient_channel(row.patient_id), record_channel(row.patient_id)})
    payload = {"patient_id": str(row.patient_id), "kind": kind}
    return [Event("health_record.updated", "health_record", str(row.id), channels, payload)]


def application_events(application: DoctorApplication, change: str, changed: frozenset[str]) -> list[Event]:
    # The reviewers' queue and the applicant's own page: the status only.
    if change == "dirty" and "status" not in changed:
        return []
    channels = frozenset({REVIEWERS, user_channel(application.user_id)})
    status = str(application.status) if application.status is not None else None
    return [Event("doctor_application.updated", "doctor_application", str(application.id), channels, {"status": status})]


def role_changes(link: UserRole, change: str, changed: frozenset[str]) -> list[Disconnect]:
    # Roles decide what a socket may hear: reconnect it to re-read them.
    return [Disconnect(link.user_id, RECONNECT, "roles changed")]


HANDLERS: dict[type, Handler] = {
    PatientAllergy: health_record_events,
    PatientDiagnosis: health_record_events,
    PatientMedication: health_record_events,
    DoctorApplication: application_events,
    UserRole: role_changes,
    Appointment: appointment_events,
    ScheduleTemplate: schedule_events,
    ScheduleException: schedule_events,
    SchedulingPolicy: schedule_events,
    QueueEntry: queue_events,
    Notification: notification_events,
}


# ---- the session hooks ------------------------------------------------------------------


def _sync(db: AsyncSession | Session) -> Session:
    return db.sync_session if isinstance(db, AsyncSession) else db


def _current_transaction(session: Session) -> SessionTransaction | None:
    return session.get_nested_transaction() or session.get_transaction()


def emit(db: AsyncSession | Session, *events: "Event | Disconnect") -> None:
    """Queue events with the current transaction: published on commit, dropped on rollback."""
    session = _sync(db)
    if not session.in_transaction():
        session.begin()  # so a rollback before the commit drops these too
    transaction = _current_transaction(session)
    session.info.setdefault(PENDING, []).extend((transaction, e) for e in events)


def end_sessions(db: AsyncSession | Session, user_id: uuid.UUID) -> None:
    """Once committed, close this user's sockets for good (deactivated, password
    changed or reset: their sessions were revoked in the same transaction)."""
    emit(db, Disconnect(user_id, UNAUTHORIZED, "session ended"))


def roles_changed(db: AsyncSession | Session, user_id: uuid.UUID) -> None:
    """For role changes made with bulk SQL (the session hooks see ORM rows only)."""
    emit(db, Disconnect(user_id, RECONNECT, "roles changed"))


def _changed(row) -> frozenset[str]:
    return frozenset(a.key for a in inspect(row).attrs if a.history.has_changes())


def _rows(session: Session) -> Iterable[tuple[object, str]]:
    for row in session.new:
        yield row, "new"
    for row in session.dirty:
        yield row, "dirty"
    for row in session.deleted:
        yield row, "deleted"


def _after_flush(session: Session, flush_context) -> None:
    # Still the pre-flush view here: new / dirty / deleted and attribute history.
    events: list = []
    for row, change in _rows(session):
        handler = HANDLERS.get(type(row))
        if handler is None:
            continue
        changed = _changed(row) if change == "dirty" else frozenset()
        if change == "dirty" and not changed:
            continue  # touched, not modified
        try:
            events.extend(handler(row, change, changed))
        except Exception:  # an event must never break the business transaction
            logger.exception("realtime_capture_failed", extra={"model": type(row).__name__})
    if events:
        emit(session, *events)


def _after_soft_rollback(session: Session, previous_transaction: SessionTransaction) -> None:
    if previous_transaction.parent is None:  # the whole transaction: nothing happened
        session.info.pop(PENDING, None)
        session.info.pop(ROLLED_BACK, None)
    else:  # a savepoint: only its own events go (checked at commit)
        session.info.setdefault(ROLLED_BACK, set()).add(previous_transaction)


def _survived(transaction: SessionTransaction | None, rolled_back: set) -> bool:
    while transaction is not None:
        if transaction in rolled_back:
            return False
        transaction = transaction.parent
    return True


def _after_commit(session: Session) -> None:
    pending = session.info.pop(PENDING, None)
    rolled_back = session.info.pop(ROLLED_BACK, None) or set()
    if not pending:
        return
    seen: set = set()
    disconnects: dict[uuid.UUID, Disconnect] = {}
    for transaction, item in pending:
        if not _survived(transaction, rolled_back):
            continue
        if isinstance(item, Disconnect):
            # Ending the sessions outranks a mere reconnect for the same user.
            if item.code == UNAUTHORIZED or item.user_id not in disconnects:
                disconnects[item.user_id] = item
            continue
        if item.key in seen:
            continue
        seen.add(item.key)
        try:
            hub.publish(item)
        except Exception:  # the data is committed; a lost event is re-read on reconnect
            logger.exception("realtime_publish_failed", extra={"type": item.type})
    for item in disconnects.values():
        hub.close_user(item.user_id, item.code, item.reason)


def install() -> None:
    """Attach the hooks to every Session (idempotent)."""
    for name, fn in (("after_flush", _after_flush), ("after_soft_rollback", _after_soft_rollback), ("after_commit", _after_commit)):
        if not sa_event.contains(Session, name, fn):
            sa_event.listen(Session, name, fn)


install()
