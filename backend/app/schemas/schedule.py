import uuid
from datetime import date, datetime, time, timedelta

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models.schedule import ExceptionKind

MAX_EXCEPTION_DAYS = 366


class ScheduleTemplateCreate(BaseModel):
    doctor_id: uuid.UUID
    weekday: int = Field(ge=0, le=6, description="Monday = 0 … Sunday = 6")
    start_time: time = Field(description="Local wall-clock time in the doctor's department timezone")
    end_time: time
    slot_minutes: int = Field(default=30, ge=5, le=240)
    valid_from: date
    valid_until: date | None = None

    @model_validator(mode="after")
    def check_ranges(self):
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be before end_time")
        if self.valid_until is not None and self.valid_until < self.valid_from:
            raise ValueError("valid_until must not be before valid_from")
        return self


class ScheduleTemplateUpdate(BaseModel):
    start_time: time | None = None
    end_time: time | None = None
    slot_minutes: int | None = Field(default=None, ge=5, le=240)
    valid_until: date | None = None


class ScheduleTemplateRead(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    weekday: int
    start_time: time
    end_time: time
    slot_minutes: int
    valid_from: date
    valid_until: date | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class ScheduleExceptionCreate(BaseModel):
    doctor_id: uuid.UUID
    kind: ExceptionKind
    # Timezone offset required: an instant without one is ambiguous.
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def check_interval(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.ends_at - self.starts_at > timedelta(days=MAX_EXCEPTION_DAYS):
            raise ValueError(f"An exception may span at most {MAX_EXCEPTION_DAYS} days")
        return self


class ScheduleExceptionRead(BaseModel):
    id: uuid.UUID
    doctor_id: uuid.UUID
    kind: ExceptionKind
    starts_at: datetime
    ends_at: datetime
    reason: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SlotRead(BaseModel):
    starts_at: datetime
    ends_at: datetime


class AvailabilityRead(BaseModel):
    doctor_id: uuid.UUID
    timezone: str
    slots: list[SlotRead]


class AvailableDay(BaseModel):
    date: date  # local calendar date in `timezone`
    slots: list[SlotRead]


class PublicAvailabilityRead(BaseModel):
    """Free slots for the public booking calendar, grouped by local date.

    Only days with at least one free slot appear. Nothing about existing
    appointments is exposed beyond the absence of a slot."""

    doctor_id: uuid.UUID
    timezone: str
    # Last local date that can be booked at all (maximum advance booking).
    bookable_until: date
    days: list[AvailableDay]
