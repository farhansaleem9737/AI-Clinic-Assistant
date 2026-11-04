"""Appointment and follow-up reminders (D108).

Nothing here runs on a timer inside the API: Cloud Scheduler (or the CLI)
calls the reminder run every few minutes, and each run looks at the database
as it is now. That makes a run safe to repeat, to retry and to overlap:

- every reminder has a dedupe key and is inserted with ON CONFLICT DO NOTHING
  against a unique index, so it exists at most once per user;
- appointments are read with their current status and time: cancelled ones
  (including the old row of a rescheduled appointment) are never selected,
  and the key carries the start time, so a moved appointment is reminded anew;
- times are compared as UTC instants (DST cannot shift them) and shown in the
  doctor's department timezone.

Of the configured offsets (e.g. 24 h and 1 h), a run sends the closest one
that has started, and only if the appointment was booked before that
reminder's moment: a booking made 30 minutes ahead gets no "1 hour" reminder,
one made 3 hours ahead gets only the 1-hour one.
"""

import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import exists, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.config import settings
from app.models.appointment import Appointment, AppointmentStatus as S
from app.models.department import Department
from app.models.doctor import Doctor
from app.models.notification import FollowUp
from app.models.patient import Patient
from app.services import email_outbox_service, notification_service

logger = logging.getLogger(__name__)

# Upcoming and still expected to happen.
REMINDABLE = (S.requested, S.scheduled, S.confirmed)
CHUNK = 500
# A follow-up long overdue is not reminded about any more.
FOLLOW_UP_GRACE_DAYS = 30


@dataclass
class RunResult:
    appointments_checked: int = 0
    reminders_created: int = 0
    follow_ups_checked: int = 0
    follow_up_reminders_created: int = 0
    duration_ms: float = 0.0


def due_offset(offsets: list[int], starts_at: datetime, booked_at: datetime, now: datetime) -> int | None:
    """The reminder (minutes before the start) due now, if any; `offsets` largest first."""
    remaining = starts_at - now
    if remaining <= timedelta(0):
        return None
    due = [o for o in offsets if remaining <= timedelta(minutes=o)]
    if not due:
        return None
    offset = min(due)  # the closest reminder that has started
    return offset if booked_at <= starts_at - timedelta(minutes=offset) else None


def _span(minutes: int) -> str:
    if minutes % 1440 == 0:
        days = minutes // 1440
        return "24 hours" if days == 1 else f"{days} days"
    if minutes % 60 == 0:
        hours = minutes // 60
        return "1 hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minutes"


async def _appointment_reminders(db: AsyncSession, now: datetime, result: RunResult) -> None:
    offsets = {"patient": settings.reminder_offsets_minutes, "doctor": settings.doctor_reminder_offsets_minutes}
    horizon = max([*offsets["patient"], *offsets["doctor"], 0])
    if not horizon:
        return
    after: tuple[datetime, uuid.UUID] | None = None
    while True:
        query = (
            select(
                Appointment.id, Appointment.starts_at, Appointment.created_at,
                Patient.user_id.label("patient_user"), Doctor.user_id.label("doctor_user"), Department.timezone,
            )
            .join(Patient, Patient.id == Appointment.patient_id)
            .join(Doctor, Doctor.id == Appointment.doctor_id)
            .join(Department, Department.id == Doctor.department_id)
            .where(
                Appointment.status.in_(REMINDABLE),
                Appointment.starts_at > now,
                Appointment.starts_at <= now + timedelta(minutes=horizon),
            )
            .order_by(Appointment.starts_at, Appointment.id)
            .limit(CHUNK)
        )
        if after is not None:
            query = query.where(tuple_(Appointment.starts_at, Appointment.id) > after)
        rows = (await db.execute(query)).all()
        if not rows:
            return
        after = (rows[-1].starts_at, rows[-1].id)
        result.appointments_checked += len(rows)
        wanted = []  # (user, role, offset, row)
        for row in rows:
            for role, user in (("patient", row.patient_user), ("doctor", row.doctor_user)):
                offset = due_offset(offsets[role], row.starts_at, row.created_at, now) if user else None
                if offset is not None:
                    wanted.append((user, role, offset, row))
        allowed = set(await notification_service.opted_in(db, {w[0] for w in wanted}, "appointment_reminder"))
        for user, role, offset, row in wanted:
            if user not in allowed:
                continue
            at = notification_service.when(row.starts_at, ZoneInfo(row.timezone))
            key = f"reminder:{row.id}:{offset}:{role}:{int(row.starts_at.timestamp())}"
            created = await notification_service.notify_once(
                db,
                user,
                dedupe_key=key,
                type="appointment_reminder",
                title="Upcoming appointment" if role == "patient" else "Upcoming consultation",
                message=(
                    f"Your appointment on {at} is in about {_span(offset)}."
                    if role == "patient"
                    else f"You have a consultation on {at}, in about {_span(offset)}."
                ),
                link=f"/appointments/{row.id}",
            )
            result.reminders_created += created
            # The patient also gets it by email for the EMAIL_REMINDER_OFFSETS_MINUTES ones (D109).
            if created and role == "patient" and offset in settings.email_reminder_offsets_minutes:
                await email_outbox_service.reminder_email(db, row.id, user, key)
        await db.commit()
        if len(rows) < CHUNK:
            return


async def _follow_up_reminders(db: AsyncSession, now: datetime, result: RunResult) -> None:
    lead = settings.follow_up_reminder_days
    clinic_today = now.date()
    query = (
        select(FollowUp.id, FollowUp.due_date, FollowUp.doctor_id, Patient.user_id.label("patient_user"), Department.timezone)
        .join(Patient, Patient.id == FollowUp.patient_id)
        .outerjoin(Doctor, Doctor.id == FollowUp.doctor_id)
        .outerjoin(Department, Department.id == Doctor.department_id)
        .where(
            FollowUp.dismissed_at.is_(None),
            Patient.user_id.is_not(None),
            # Bounds in UTC dates, a day wider than any timezone; refined per row below.
            FollowUp.due_date <= clinic_today + timedelta(days=lead + 1),
            FollowUp.due_date >= clinic_today - timedelta(days=FOLLOW_UP_GRACE_DAYS + 1),
            # Already booked: an active appointment made after the follow-up was recorded.
            ~exists().where(
                Appointment.patient_id == FollowUp.patient_id,
                Appointment.status.in_(REMINDABLE),
                Appointment.created_at >= FollowUp.created_at,
                or_(FollowUp.doctor_id.is_(None), Appointment.doctor_id == FollowUp.doctor_id),
            ),
        )
        .order_by(FollowUp.due_date)
    )
    rows = (await db.execute(query)).all()
    result.follow_ups_checked = len(rows)
    allowed = set(await notification_service.opted_in(db, {r.patient_user for r in rows}, "follow_up_due"))
    for row in rows:
        today = now.astimezone(ZoneInfo(row.timezone or settings.clinic_timezone)).date()
        if not (row.due_date - timedelta(days=lead) <= today <= row.due_date + timedelta(days=FOLLOW_UP_GRACE_DAYS)):
            continue
        if row.patient_user not in allowed:
            continue
        key = f"follow_up:{row.id}:{row.due_date.isoformat()}"
        link = f"/appointments/book?doctor={row.doctor_id}" if row.doctor_id else "/appointments/book"
        created = await notification_service.notify_once(
            db,
            row.patient_user,
            dedupe_key=key,
            type="follow_up_due",
            title="Follow-up visit due",
            message=(
                f"Your follow-up appointment is due by {row.due_date:%a %d %b %Y}. "
                "It is not booked yet: you can review available appointment times."
            ),
            link=link,
        )
        result.follow_up_reminders_created += created
        if created:
            await email_outbox_service.enqueue(
                db, row.patient_user, "follow_up_due", {"due_date": f"{row.due_date:%a %d %b %Y}", "link": link}, dedupe_key=key,
                expires_at=datetime.combine(row.due_date + timedelta(days=FOLLOW_UP_GRACE_DAYS), datetime.min.time(), tzinfo=UTC),
            )
    await db.commit()


async def run(db: AsyncSession, now: datetime | None = None) -> RunResult:
    """One reminder run. Safe to repeat or overlap (see the module docstring)."""
    started = time.perf_counter()
    now = now or clock.utcnow()
    result = RunResult()
    await _appointment_reminders(db, now, result)
    await _follow_up_reminders(db, now, result)
    result.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.info("reminder_run", extra=asdict(result))
    return result

