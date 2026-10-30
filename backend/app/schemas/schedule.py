import uuid
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.schedule import ExceptionKind

MAX_EXCEPTION_DAYS = 366
# For models with a field named `date`, whose later annotations would see the field.
LocalDate = date


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
    # custom_hours is date-based: use the date-exception endpoints.
    kind: Literal[
        ExceptionKind.leave, ExceptionKind.holiday, ExceptionKind.block, ExceptionKind.extra_availability
    ]
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
    # Working-hour slots that cannot be booked (taken, or inside the booking
    # notice), so a calendar can show them greyed out. No booking details.
    unavailable: list[SlotRead] = []


class PublicAvailabilityRead(BaseModel):
    """Free slots for the public booking calendar, grouped by local date.

    Only days with at least one free slot appear. Nothing about existing
    appointments is exposed beyond a working-hours slot being unavailable."""

    doctor_id: uuid.UUID
    timezone: str
    # Last local date that can be booked at all (maximum advance booking).
    bookable_until: date
    days: list[AvailableDay]


# ---- the doctor's "My Schedule" page (D78) ------------------------------------------


class WorkingInterval(BaseModel):
    """Local wall-clock times in the doctor's department timezone."""

    start_time: time
    end_time: time

    @model_validator(mode="after")
    def start_before_end(self):
        # No overnight shifts: a working block ends on the day it starts.
        if self.start_time >= self.end_time:
            raise ValueError("The start time must be before the end time")
        return self


class WeeklyDay(BaseModel):
    weekday: int = Field(ge=0, le=6, description="Monday = 0 … Sunday = 6")
    enabled: bool
    # Several blocks per day are allowed (e.g. 09:00–13:00 and 14:00–17:00).
    intervals: list[WorkingInterval] = Field(default_factory=list, max_length=6)
    # Appointment length on this day; omitted keeps the current one.
    slot_minutes: int | None = Field(default=None, ge=5, le=240)

    @model_validator(mode="after")
    def consistent(self):
        if self.enabled and not self.intervals:
            raise ValueError("An available day needs working hours")
        ordered = sorted(self.intervals, key=lambda i: i.start_time)
        for before, after in zip(ordered, ordered[1:]):
            if after.start_time < before.end_time:
                raise ValueError("Working hours on one day must not overlap")
        self.intervals = ordered
        return self


class WeeklyScheduleUpdate(BaseModel):
    """The whole week at once: exactly one entry per weekday."""

    days: list[WeeklyDay] = Field(min_length=7, max_length=7)

    @field_validator("days")
    @classmethod
    def one_per_weekday(cls, days: list[WeeklyDay]) -> list[WeeklyDay]:
        if sorted(d.weekday for d in days) != list(range(7)):
            raise ValueError("Give each weekday exactly once")
        return sorted(days, key=lambda d: d.weekday)


class WeeklyDayRead(BaseModel):
    weekday: int
    enabled: bool
    intervals: list[WorkingInterval]
    slot_minutes: int


class WeeklyScheduleRead(BaseModel):
    doctor_id: uuid.UUID
    timezone: str
    days: list[WeeklyDayRead]


class DateExceptionType(StrEnum):
    unavailable = "unavailable"
    custom_hours = "custom_hours"
    # Older interval exceptions that add time; shown, edited elsewhere.
    extra_hours = "extra_hours"


class DateExceptionWrite(BaseModel):
    """One date that differs from the weekly hours."""

    date: LocalDate = Field(description="Local calendar date in the doctor's department timezone")
    type: Literal[DateExceptionType.unavailable, DateExceptionType.custom_hours]
    start_time: time | None = None
    end_time: time | None = None
    reason: str | None = Field(default=None, max_length=255)

    @field_validator("reason", mode="before")
    @classmethod
    def blank_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def hours_match_type(self):
        if self.type is DateExceptionType.custom_hours:
            if self.start_time is None or self.end_time is None:
                raise ValueError("Custom hours need a start and an end time")
            if self.start_time >= self.end_time:
                raise ValueError("The start time must be before the end time")
        else:
            # An unavailable day is the whole day.
            self.start_time = self.end_time = None
        return self


class DateExceptionRead(BaseModel):
    id: uuid.UUID
    type: DateExceptionType
    kind: ExceptionKind
    date: LocalDate
    # Last local date covered; equals `date` for a one-day exception.
    end_date: LocalDate
    # Null for a whole-day exception.
    start_time: time | None
    end_time: time | None
    reason: str | None
    # Whether the date form can edit it (one day, whole-day or custom hours).
    editable: bool


# ---- the staff schedule view (D83) ----------------------------------------------------


class BoardSlotRead(BaseModel):
    starts_at: datetime
    ends_at: datetime
    # available | booked | blocked | break | past | beyond_horizon. Never who booked it.
    status: str


class DaySummaryRead(BaseModel):
    date: LocalDate
    # available | fully_booked | off | unavailable | past
    status: str
    available_slots: int


class DayScheduleRead(BaseModel):
    doctor_id: uuid.UUID
    timezone: str
    date: LocalDate
    # Today in `timezone`, for "Today" labels and navigation.
    today: LocalDate
    slot_minutes: int
    working_hours: list[WorkingInterval]
    breaks: list[WorkingInterval]
    total_slots: int
    available_slots: int
    slots: list[BoardSlotRead]
    # Sunday to Saturday around `date`.
    week: list[DaySummaryRead]
