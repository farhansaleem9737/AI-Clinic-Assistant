import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

_PHONE = re.compile(r"\+?[0-9(][0-9 ()\-.]{3,28}")


class OperationalSettings(BaseModel):
    """Server configuration, shown read-only (changing it needs a deployment)."""

    timezone: str
    default_slot_minutes: int
    booking_min_lead_minutes: int
    booking_max_advance_days: int
    patient_cancellation_cutoff_minutes: int


class ClinicSettingsRead(BaseModel):
    clinic_name: str | None
    contact_phone: str | None
    contact_email: str | None
    address: str | None
    updated_at: datetime | None
    operational: OperationalSettings


class ClinicSettingsUpdate(BaseModel):
    """Omitted fields are unchanged; an empty value clears one."""

    clinic_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=30)
    contact_email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=500)

    @field_validator("clinic_name", "contact_phone", "address", "contact_email", mode="before")
    @classmethod
    def blank_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("contact_phone")
    @classmethod
    def phone_characters(cls, value: str | None) -> str | None:
        if value is not None and not _PHONE.fullmatch(value):
            raise ValueError("Use digits, spaces, dashes, dots or brackets, with an optional leading +")
        return value


class NotificationRead(BaseModel):
    id: uuid.UUID
    type: str
    title: str
    message: str
    link: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationRead]
    unread: int


class UnreadCount(BaseModel):
    unread: int


# ---- global search (D86) ------------------------------------------------------------------


class SearchPatient(BaseModel):
    id: uuid.UUID
    name: str
    mrn: str


class SearchDoctor(BaseModel):
    id: uuid.UUID
    name: str
    specialization: str


class SearchAppointment(BaseModel):
    id: uuid.UUID
    starts_at: datetime
    timezone: str
    patient_name: str
    doctor_name: str
    status: str


class SearchUser(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    roles: list[str]


class SearchResults(BaseModel):
    """Each section is present only when the caller may list those records;
    within it, only records they may open."""

    query: str
    patients: list[SearchPatient] | None = None
    doctors: list[SearchDoctor] | None = None
    appointments: list[SearchAppointment] | None = None
    users: list[SearchUser] | None = None
