import uuid
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Display metadata (D89). Keys, not markup: the frontend maps each to a Lucide
# icon and a palette colour.
DepartmentIcon = Literal[
    "heart-pulse", "stethoscope", "brain", "bone", "baby", "ear", "eye", "scan-face",
    "activity", "pill", "microscope", "syringe", "smile", "hospital",
]
DepartmentColor = Literal["red", "pink", "purple", "violet", "blue", "teal", "green", "yellow", "orange", "slate"]


def _check_timezone(value: str | None) -> str | None:
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown IANA timezone: {value}") from exc
    return value


def _blank_is_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class DepartmentCreate(BaseModel):
    # Unknown fields ("is_active", "doctor_count", ...) are refused, not ignored.
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    # Defaults to the clinic timezone when omitted.
    timezone: str | None = Field(default=None, max_length=64)
    icon: DepartmentIcon | None = None
    color: DepartmentColor | None = None
    # Created inactive when false (e.g. prepared before opening).
    is_active: bool = True

    _tz = field_validator("timezone")(_check_timezone)
    _description = field_validator("description")(_blank_is_none)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str | None:
        if value is None:  # update: "name": null leaves the name as it is
            return None
        value = " ".join(value.split())
        if not value:
            raise ValueError("Name must not be blank")
        return value


class DepartmentUpdate(DepartmentCreate):
    """Omitted fields stay as they are. Status changes go through
    activate / deactivate, which apply their own rules."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: None = Field(default=None, exclude=True)


class DepartmentPublic(BaseModel):
    """What anyone may see: no status, no internal timestamps."""

    id: uuid.UUID
    name: str
    description: str | None = None

    model_config = ConfigDict(from_attributes=True)


class DepartmentResponse(DepartmentPublic):
    timezone: str
    is_active: bool
    icon: str | None = None
    color: str | None = None
    created_at: datetime
    updated_at: datetime


class DoctorPreview(BaseModel):
    id: uuid.UUID
    name: str
    title: str | None = None
    photo_url: str | None = None


class DepartmentPublicCard(DepartmentPublic):
    """The patient / visitor card (D94): display metadata and the doctors the
    public directory lists. No status, timezone or timestamps."""

    icon: str | None = None
    color: str | None = None
    doctor_count: int
    doctors_preview: list["DoctorPreview"]


class DepartmentListItem(DepartmentResponse):
    # Practising doctors: active doctor profile with an active login. Doctor
    # profiles exist only after approval, so applicants are never counted.
    doctor_count: int
    # Up to three of those same doctors, by name, for the avatar stack.
    doctors_preview: list[DoctorPreview]


class DepartmentDoctor(DoctorPreview):
    specialization: str
    is_active: bool


class DepartmentDetail(DepartmentListItem):
    # Every doctor profile in the department, practising or not.
    doctors: list[DepartmentDoctor]
    # Booked / confirmed / checked-in appointments from now on. Kept, never
    # cancelled, when the department is deactivated.
    upcoming_appointments: int


class DepartmentSummaryRead(BaseModel):
    total: int
    active: int
    inactive: int
    doctors: int
