"""Notification emails through a PostgreSQL outbox (D109).

    event (booking, reminder, …) ── same transaction ──▶ email_outbox row
    outbox run ── claims due rows (SKIP LOCKED), commits ──▶ SMTP, outside any transaction
                └─ records sent / retry with backoff / failed / expired

- **Queued with the event**, so it exists exactly when the event does, and a
  slow or failing SMTP server can never delay or undo a booking.
- **Who:** the recipient is always an account the event is about (the
  patient's, the doctor's (D124) or the applicant's own login and address, or
  the reviewers for a new application), active, and wanting it: the
  notification category is on and so is email.
- **When:** after a commit that queued email, this process starts a run at
  once (best effort); the scheduled reminder run (Cloud Scheduler) also runs
  the outbox, so nothing waits longer than its interval if that was cut short.
  A temporary failure also sets a wake-up in this process for its retry (D124),
  so a short outage heals without a scheduler.
- **Safety:** a claim is a lease (status "sending" until a deadline), so
  concurrent runs on several Cloud Run instances never take the same row,
  and an instance that died mid-send gives its rows back after the deadline.
  That makes delivery at-least-once, not exactly-once: an SMTP server may have
  accepted a message whose acknowledgement was lost.
- **Not configured** (EMAIL_BACKEND=none / no SMTP_HOST): nothing is queued,
  and nothing is ever reported as sent.
"""

import asyncio
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import event, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import EmailBackend, settings
from app.models.appointment import Appointment
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.email import EmailOutbox
from app.models.notification import NotificationPreference
from app.models.patient import Patient
from app.models.user import User
from app.services import email_service, email_templates, notification_service

logger = logging.getLogger(__name__)

# Which preference category an email belongs to; None = always (given the 'emails' switch).
CATEGORY = {
    "appointment_booked": "appointment_updates",
    "appointment_confirmed": "appointment_updates",
    "appointment_rescheduled": "appointment_updates",
    "appointment_cancelled": "appointment_updates",
    "doctor_appointment_booked": "appointment_updates",
    "doctor_appointment_cancelled": "appointment_updates",
    "doctor_appointment_rescheduled": "appointment_updates",
    "appointment_reminder": "reminders",
    "follow_up_due": "follow_ups",
    "doctor_application_approved": None,
    "doctor_application_rejected": None,
    "doctor_application_submitted": None,  # reviewers: work waiting for them
}
BATCH = 25
LEASE = timedelta(minutes=10)  # how long a claimed row is reserved for the run that claimed it
BACKOFF_MINUTES = (1, 5, 15, 60, 180)


@dataclass
class OutboxResult:
    sent: int = 0
    written: int = 0  # development: written to a file, not sent
    retrying: int = 0
    failed: int = 0
    expired: int = 0


def _mark_queued(db: AsyncSession) -> None:
    db.info["email_queued"] = True


async def wants_email(db: AsyncSession, user_id: uuid.UUID, kind: str) -> bool:
    prefs = await db.get(NotificationPreference, user_id)
    if prefs is None:
        return True
    category = CATEGORY.get(kind)
    return prefs.emails and (category is None or getattr(prefs, category))


async def enqueue(
    db: AsyncSession, user_id: uuid.UUID | None, kind: str, ctx: dict, *, dedupe_key: str, expires_at: datetime | None = None
) -> bool:
    """Queue one email for `user_id` (their own address). Does not commit. Returns whether it was queued."""
    if user_id is None or settings.effective_email_backend is EmailBackend.none:
        return False
    user = (await db.execute(select(User.email, User.name, User.is_active).where(User.id == user_id))).one_or_none()
    if user is None or not user.is_active or not user.email or not await wants_email(db, user_id, kind):
        return False
    rendered = email_templates.render(kind, {"name": user.name, **ctx})
    queued = await db.scalar(
        insert(EmailOutbox)
        .values(
            id=uuid.uuid7(), user_id=user_id, to_address=user.email, kind=kind, subject=rendered.subject[:200],
            text_body=rendered.text, html_body=rendered.html, dedupe_key=dedupe_key[:160], status="pending",
            attempts=0, next_attempt_at=clock.utcnow(), expires_at=expires_at, created_at=clock.utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
        .returning(EmailOutbox.id)
    )
    if queued is not None:
        _mark_queued(db)
    return queued is not None


# ---- appointment emails: to the patient's and the doctor's own logins ---------------------

# Doctors (D124) hear about bookings, cancellations and moves made by someone
# else, as in the app; never the patient's name or the reason for the visit.
DOCTOR_KIND = {
    "appointment_booked": "doctor_appointment_booked",
    "appointment_cancelled": "doctor_appointment_cancelled",
    "appointment_rescheduled": "doctor_appointment_rescheduled",
}


async def _appointment_facts(db: AsyncSession, appt: Appointment) -> tuple[uuid.UUID | None, uuid.UUID, dict, ZoneInfo]:
    patient_user, doctor_user, title, doctor_name, department, tz = (
        await db.execute(
            select(Patient.user_id, Doctor.user_id, Doctor.title, User.name, Department.name, Department.timezone)
            .select_from(Appointment)
            .join(Patient, Patient.id == Appointment.patient_id)
            .join(Doctor, Doctor.id == Appointment.doctor_id)
            .join(User, User.id == Doctor.user_id)
            .join(Department, Department.id == Doctor.department_id)
            .where(Appointment.id == appt.id)
        )
    ).one()
    zone = ZoneInfo(tz)
    local = appt.starts_at.astimezone(zone)
    ctx = {
        "when": notification_service.when(appt.starts_at, zone),
        "date": local.strftime("%A %d %B %Y"),
        "time": f"{local:%H:%M} ({tz})",
        "doctor": f"{title or 'Dr.'} {doctor_name}",
        "department": department,
        "status": str(appt.status),  # as stored, never assumed
        "link": f"/appointments/{appt.id}",
    }
    return patient_user, doctor_user, ctx, zone


# Emails about an appointment that make no sense once it is cancelled or moved.
_STALE_KINDS = ("appointment_booked", "appointment_confirmed", "appointment_rescheduled",
                "doctor_appointment_booked", "doctor_appointment_rescheduled")


async def withdraw(db: AsyncSession, appointment_id: uuid.UUID) -> None:
    """Drop this appointment's unsent confirmations and reminders (D124). Rows already
    claimed by a run ("sending") may still go out: delivery is at least once."""
    await db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.status == "pending",
            or_(
                EmailOutbox.dedupe_key.in_([f"{k}:{appointment_id}" for k in _STALE_KINDS]),
                EmailOutbox.dedupe_key.startswith(f"reminder:{appointment_id}:", autoescape=True),
            ),
        )
        .values(status="expired", text_body="", html_body="")
    )


async def appointment_email(
    db: AsyncSession, appt: Appointment, kind: str, *, old: Appointment | None = None, actor: uuid.UUID | None = None
) -> None:
    """The patient's email, and (for bookings, cancellations and moves) the doctor's unless they did it."""
    if kind == "appointment_cancelled":
        await withdraw(db, appt.id)
    if old is not None:
        await withdraw(db, old.id)
    patient_user, doctor_user, ctx, zone = await _appointment_facts(db, appt)
    if old is not None:
        ctx["old_when"] = notification_service.when(old.starts_at, zone)
    # Not worth sending once the appointment has started (a cancellation is still news).
    expires = None if kind == "appointment_cancelled" else appt.starts_at
    await enqueue(db, patient_user, kind, ctx, dedupe_key=f"{kind}:{appt.id}", expires_at=expires)
    doctor_kind = DOCTOR_KIND.get(kind)
    if doctor_kind and doctor_user != actor:
        await enqueue(db, doctor_user, doctor_kind, ctx, dedupe_key=f"{doctor_kind}:{appt.id}", expires_at=expires)
    if kind == "appointment_rescheduled" and old is not None and old.doctor_id != appt.doctor_id:
        # Moved to another doctor: for the previous one it is a cancellation.
        _, old_doctor, old_ctx, _ = await _appointment_facts(db, old)
        if old_doctor != actor:
            cancelled = DOCTOR_KIND["appointment_cancelled"]
            await enqueue(db, old_doctor, cancelled, old_ctx, dedupe_key=f"{cancelled}:{old.id}")


async def reminder_email(db: AsyncSession, appointment_id: uuid.UUID, patient_user: uuid.UUID, dedupe_key: str) -> None:
    appt = await db.get(Appointment, appointment_id)
    _, _, ctx, _ = await _appointment_facts(db, appt)
    await enqueue(db, patient_user, "appointment_reminder", ctx, dedupe_key=dedupe_key, expires_at=appt.starts_at)


async def status_counts(db: AsyncSession) -> dict[str, int]:
    """Emails per status, for monitoring (e.g. failed > 0 needs a look)."""
    rows = await db.execute(select(EmailOutbox.status, func.count()).group_by(EmailOutbox.status))
    return {status: count for status, count in rows.all()}


# ---- the outbox run ---------------------------------------------------------------------


async def _claim(db: AsyncSession, now: datetime) -> list[EmailOutbox]:
    """Reserve up to BATCH due rows for this run (a lease), then commit: no transaction stays open while sending."""
    rows = list(
        (
            await db.scalars(
                select(EmailOutbox)
                .where(EmailOutbox.status.in_(("pending", "sending")), EmailOutbox.next_attempt_at <= now)
                .order_by(EmailOutbox.next_attempt_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for row in rows:
        row.status = "sending"
        row.attempts += 1
        row.next_attempt_at = now + LEASE
    await db.commit()
    return rows


async def _record(db: AsyncSession, row_id: uuid.UUID, **values) -> None:
    await db.execute(update(EmailOutbox).where(EmailOutbox.id == row_id).values(**values))
    await db.commit()


async def run(db: AsyncSession, now: datetime | None = None) -> OutboxResult:
    """Send what is due. Safe to run on several instances at once."""
    result = OutboxResult()
    if settings.effective_email_backend is EmailBackend.none:
        return result
    while True:
        started = now or clock.utcnow()
        rows = await _claim(db, started)
        if not rows:
            break
        for row in rows:
            if row.expires_at is not None and row.expires_at <= started:
                await _record(db, row.id, status="expired", text_body="", html_body="")
                result.expired += 1
                continue
            email = email_service.Email(to=row.to_address, subject=row.subject, text=row.text_body, html=row.html_body)
            try:
                delivery = await email_service.deliver(email)
            except email_service.DeliveryError as exc:
                final = exc.permanent or row.attempts >= settings.email_max_attempts
                retry_in = BACKOFF_MINUTES[min(row.attempts - 1, len(BACKOFF_MINUTES) - 1)]
                await _record(
                    db, row.id, last_error=exc.reason[:120],
                    **({"status": "failed"} if final else {"status": "pending", "next_attempt_at": started + timedelta(minutes=retry_in)}),
                )
                logger.warning(
                    "email_delivery_failed",
                    extra={"email_id": str(row.id), "kind": row.kind, "error": exc.reason, "attempt": row.attempts, "final": final},
                )
                if final:
                    result.failed += 1
                else:
                    result.retrying += 1
                continue
            if delivery is email_service.Delivery.not_configured:
                # Switched off since it was queued: keep it, nothing was sent.
                await _record(db, row.id, status="pending", next_attempt_at=started + timedelta(minutes=BACKOFF_MINUTES[-1]))
                continue
            sent = delivery is email_service.Delivery.sent
            # The bodies are no longer needed once delivered.
            await _record(db, row.id, status="sent" if sent else "written", sent_at=clock.utcnow(), text_body="", html_body="", last_error=None)
            if sent:
                result.sent += 1
            else:
                result.written += 1
        if now is not None:
            break  # a test's fixed clock: one pass
    if any(asdict(result).values()):
        logger.info("email_outbox_run", extra=asdict(result))
    return result


# ---- start sending right after the event's commit (best effort) -------------------------

_kick_task: asyncio.Task | None = None
_kick_again = False
_retry_timer: asyncio.TimerHandle | None = None
RETRY_HORIZON = timedelta(hours=6)  # beyond that, the scheduled run takes over


async def _next_due(db: AsyncSession) -> datetime | None:
    return await db.scalar(select(func.min(EmailOutbox.next_attempt_at)).where(EmailOutbox.status == "pending"))


def _retry_at(due: datetime) -> None:
    """Wake this process when the next retry is due, so a short SMTP outage heals by itself
    even without a scheduler (D124). Best effort: lost on restart, which the scheduled run covers."""
    global _retry_timer
    delay = max((due - clock.utcnow()).total_seconds(), 1)
    if delay > RETRY_HORIZON.total_seconds():
        return
    loop = asyncio.get_running_loop()
    if _retry_timer is not None:
        if _retry_timer.when() <= loop.time() + delay:
            return  # an earlier wake-up is already set
        _retry_timer.cancel()
    _retry_timer = loop.call_later(delay, _start_kick)


def _start_kick() -> None:
    global _kick_task, _kick_again, _retry_timer
    _retry_timer = None
    if _kick_task is not None:
        _kick_again = True
        return
    _kick_task = asyncio.get_running_loop().create_task(_kick())


async def _kick() -> None:
    global _kick_task, _kick_again
    from app.db.database import AsyncSessionLocal

    try:
        due = None
        while True:
            _kick_again = False
            async with AsyncSessionLocal() as db:
                await run(db)
                due = await _next_due(db)
            if not _kick_again:
                break
        if due is not None:
            _retry_at(due)
    except Exception:  # the scheduled run will pick it up
        logger.exception("email_outbox_kick_failed")
    finally:
        _kick_task = None


@event.listens_for(Session, "after_commit")
def _after_commit(session: Session) -> None:
    if not session.info.pop("email_queued", False) or not settings.email_send_after_commit:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # no event loop (a script): the scheduled run sends it
    _start_kick()
