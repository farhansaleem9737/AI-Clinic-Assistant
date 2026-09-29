import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field, model_validator

# Money is Decimal end to end (Numeric(10, 2) in PostgreSQL), serialised as a
# string in JSON — never a float.
FEE_FIELD = {"ge": 0, "max_digits": 10, "decimal_places": 2}


class NewDoctorAccount(BaseModel):
    """Login to create together with the profile (the doctor role is granted)."""

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
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
    bio: str | None = Field(default=None, max_length=1000)
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    consultation_fee: Decimal | None = Field(default=None, **FEE_FIELD)
    phone: str | None = Field(default=None, max_length=30)
    room_number: str | None = Field(default=None, max_length=20)


class DoctorSelfUpdate(BaseModel):
    """What a doctor may change on their own profile."""

    bio: str | None = Field(default=None, max_length=1000)
    phone: str | None = Field(default=None, max_length=30)


class DoctorPublic(BaseModel):
    """Public directory entry: no contact details, license, or account data."""

    id: uuid.UUID
    name: str
    title: str | None
    specialization: str
    department_id: uuid.UUID
    department_name: str
    bio: str | None
    years_of_experience: int
    consultation_fee: Decimal | None


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
