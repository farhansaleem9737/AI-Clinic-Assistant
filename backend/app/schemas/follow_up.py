"""Follow-up visits recorded as due by a date (D108)."""

import uuid
from datetime import date

from pydantic import BaseModel


class FollowUpRead(BaseModel):
    id: uuid.UUID
    due_date: date
    doctor_id: uuid.UUID | None


class FollowUpState(BaseModel):
    """The appointment's open follow-up (or none), and whether the caller may record or change it."""

    follow_up: FollowUpRead | None
    can_manage: bool


class FollowUpWrite(BaseModel):
    due_date: date


class ReminderRunRead(BaseModel):
    appointments_checked: int
    reminders_created: int
    follow_ups_checked: int
    follow_up_reminders_created: int
    duration_ms: float
    # The email outbox, run after the reminders (D109).
    emails_sent: int = 0
    emails_written: int = 0
    emails_retrying: int = 0
    emails_failed: int = 0
    emails_expired: int = 0
