import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.common import LoginEmail
from app.schemas.schedule import WorkingInterval
from app.services.availability_service import AvailabilityStatus

# Money is Decimal end to end (Numeric(10, 2) in PostgreSQL), serialised as a
# string in JSON — never a float.
FEE_FIELD = {"ge": 0, "max_digits": 10, "decimal_places": 2}


class NewDoctorAccount(BaseModel):
    """Login to create together with the profile (the doctor role is granted)."""

    name: str = Field(min_length=1, max_length=100)
    email: LoginEmail
    password: str = Field(min_length=8, max_length=128)


class DoctorCreate(BaseModel):
    """Either link an existing user who holds the doctor role (`user_id`) or
    create their login in the same step (`account`) — exactly one."""

    user_id: uuid.UUID | None = None
    account: NewDoctorAccount | None = None
    department_id: uuid.UUID
    title: str | None = Field(default=None, max_length=20)
    specialization: str = Field(min_length=1, max_length=150)
    license_number: str | None = Field(default=None, max_length=50)
    qualifications: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=1000)
    languages: str | None = Field(default=None, max_length=200)
    years_of_experience: int = Field(default=0, ge=0, le=80)
    consultation_fee: Decimal | None = Field(default=None, **FEE_FIELD)
    phone: str | None = Field(default=None, max_length=30)
    room_number: str | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def exactly_one_identity(self) -> "DoctorCreate":
        if (self.user_id is None) == (self.account is None):
            raise ValueError("Provide exactly one of user_id or account")
        return self


class DoctorUpdate(BaseModel):
    """Admin edit. Omitted fields are left unchanged. Status and the login
    are changed elsewhere; unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")

    department_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=20)
    specialization: str | None = Field(default=None, min_length=1, max_length=150)
    license_number: str | None = Field(default=None, max_length=50)
    qualifications: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=1000)
    languages: str | None = Field(default=None, max_length=200)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    consultation_fee: Decimal | None = Field(default=None, **FEE_FIELD)
    phone: str | None = Field(default=None, max_length=30)
    room_number: str | None = Field(default=None, max_length=20)


class DoctorSelfUpdate(BaseModel):
    """What a doctor may change on their own profile. Name, specialization,
    department, fee, license number, room and status are managed by the
    clinic administration (DoctorUpdate); anything else sent is ignored."""

    bio: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=30)
    languages: str | None = Field(default=None, max_length=200)
    qualifications: str | None = Field(default=None, max_length=500)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)

    @field_validator("bio", "phone", "languages", "qualifications", mode="before")
    @classmethod
    def blank_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class DoctorAvailabilityRead(BaseModel):
    """Coarse availability over the coming days. The exact free slots are
    only shown to signed-in users (availability endpoint)."""

    status: AvailabilityStatus
    # Start of the earliest bookable slot, when there is one.
    next_available: datetime | None
    # A free slot remains today (clinic-local date).
    available_today: bool = False
    # Only a few free slots left in the window.
    limited: bool = False
    # Today's working hours in the doctor's timezone; empty when not working today.
    today_hours: list[WorkingInterval] = []


class DoctorPublic(BaseModel):
    """Public directory entry: no contact details, license number, or account data."""

    id: uuid.UUID
    name: str
    title: str | None
    specialization: str
    department_id: uuid.UUID
    department_name: str
    qualifications: str | None
    bio: str | None
    languages: str | None = None
    years_of_experience: int
    consultation_fee: Decimal | None
    # The clinic holds a medical license number for this doctor. The number
    # itself is never published.
    is_verified: bool
    availability: DoctorAvailabilityRead
    # short_lived signed link to the profile photo; None shows the default avatar.
    photo_url: str | None = None


class DoctorExperienceRead(BaseModel):
    title: str
    organization: str
    location: str | None
    start_year: int
    end_year: int | None  # None: current position
    description: str | None

    model_config = ConfigDict(from_attributes=True)


class DoctorEducationRead(BaseModel):
    qualification: str
    institution: str
    field_of_study: str | None
    start_year: int | None
    end_year: int | None

    model_config = ConfigDict(from_attributes=True)


# ---- career history (edited by the doctor or an admin) -------------------------------

# Same bounds as the database check constraints on doctor_experiences/doctor_education.
YEAR = {"ge": 1940, "le": 2100}


def _clean_text(value: object) -> object:
    """Trim text; an optional field left blank is stored as NULL."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class DoctorExperienceWrite(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    organization: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=150)
    start_year: int = Field(**YEAR)
    end_year: int | None = Field(default=None, **YEAR)  # None: current position
    description: str | None = Field(default=None, max_length=1000)

    _clean = field_validator("title", "organization", "location", "description", mode="before")(_clean_text)

    @model_validator(mode="after")
    def end_not_before_start(self) -> "DoctorExperienceWrite":
        if self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("end_year must not be before start_year")
        return self


class DoctorEducationWrite(BaseModel):
    qualification: str = Field(min_length=1, max_length=150)
    institution: str = Field(min_length=1, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=150)
    start_year: int | None = Field(default=None, **YEAR)
    end_year: int | None = Field(default=None, **YEAR)  # year of completion

    _clean = field_validator("qualification", "institution", "field_of_study", mode="before")(_clean_text)

    @model_validator(mode="after")
    def end_not_before_start(self) -> "DoctorEducationWrite":
        if self.start_year is not None and self.end_year is not None and self.end_year < self.start_year:
            raise ValueError("end_year must not be before start_year")
        return self


class DoctorCareerUpdate(BaseModel):
    """The doctor's whole public career history; it replaces what is stored."""

    experience: list[DoctorExperienceWrite] = Field(default_factory=list, max_length=30)
    education: list[DoctorEducationWrite] = Field(default_factory=list, max_length=30)


class DoctorCareerRead(BaseModel):
    experience: list[DoctorExperienceRead]
    education: list[DoctorEducationRead]


class DoctorProfilePublic(DoctorPublic):
    """The public profile page: the directory entry plus career history."""

    experience: list[DoctorExperienceRead]
    education: list[DoctorEducationRead]


class DoctorResponse(DoctorPublic):
    """Full profile for authorised staff and the doctor themselves."""

    user_id: uuid.UUID
    email: EmailStr
    license_number: str | None
    phone: str | None
    room_number: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Only on GET /doctors/{id}: upcoming appointments (D90).
    upcoming_appointments: int | None = None
