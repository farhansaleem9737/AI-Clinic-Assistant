import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.common import LoginEmail
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
    """Admin edit. Omitted fields are left unchanged."""

    department_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=20)
    specialization: str | None = Field(default=None, min_length=1, max_length=150)
    license_number: str | None = Field(default=None, max_length=50)
    qualifications: str | None = Field(default=None, max_length=500)
    bio: str | None = Field(default=None, max_length=1000)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    consultation_fee: Decimal | None = Field(default=None, **FEE_FIELD)
    phone: str | None = Field(default=None, max_length=30)
    room_number: str | None = Field(default=None, max_length=20)


class DoctorSelfUpdate(BaseModel):
    """What a doctor may change on their own profile."""

    bio: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=30)


class DoctorAvailabilityRead(BaseModel):
    """Coarse availability over the coming days. The exact free slots are
    only shown to signed-in users (availability endpoint)."""

    status: AvailabilityStatus
    # Start of the earliest bookable slot, when there is one.
    next_available: datetime | None


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
    years_of_experience: int
    consultation_fee: Decimal | None
    # The clinic holds a medical license number for this doctor. The number
    # itself is never published.
    is_verified: bool
    availability: DoctorAvailabilityRead


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
