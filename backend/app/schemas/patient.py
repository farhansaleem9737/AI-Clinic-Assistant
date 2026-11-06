import re
import uuid
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.core.config import settings
from app.models.patient import SexAtBirth
from app.schemas.common import LoginEmail, VerificationCode, check_birth_date, clean_name


_PHONE = re.compile(r"\+?[0-9(][0-9 ()\-.]{3,28}")


def _validate_dob(value: date | None) -> date | None:
    return value if value is None else check_birth_date(value)


ContactMethod = Literal["phone", "sms", "email"]
BloodGroup = Literal["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
MaritalStatus = Literal["single", "married", "divorced", "widowed"]


class _Contact(BaseModel):
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=500)
    preferred_language: str | None = Field(default=None, max_length=35)
    emergency_contact_name: str | None = Field(default=None, max_length=100)
    emergency_contact_relationship: str | None = Field(default=None, max_length=50)
    emergency_contact_phone: str | None = Field(default=None, max_length=30)
    preferred_contact_method: ContactMethod | None = None
    # The address in parts (D111); `address` is the street / area.
    city: str | None = Field(default=None, max_length=100)
    province: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, pattern=r"^[A-Z]{2}$", description="ISO 3166-1 alpha-2, e.g. PK")

    @field_validator("country", mode="before")
    @classmethod
    def country_code(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper() or None
        return value

    @field_validator(
        "phone", "address", "preferred_language", "emergency_contact_name",
        "emergency_contact_relationship", "emergency_contact_phone", "city", "province", mode="before",
    )
    @classmethod
    def blank_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("phone", "emergency_contact_phone")
    @classmethod
    def phone_characters(cls, value: str | None) -> str | None:
        # Digits with the usual separators and an optional leading +; any
        # country's format, but not free text.
        if value is not None and not _PHONE.fullmatch(value):
            raise ValueError("Use digits, spaces, dashes, dots or brackets, with an optional leading +")
        return value


class PatientCreate(_Contact):
    """Registration of a patient by staff (walk-in) or completion of one's own profile."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    date_of_birth: date
    sex_at_birth: SexAtBirth = SexAtBirth.unknown

    _dob = field_validator("date_of_birth")(_validate_dob)


class PatientUpdate(_Contact):
    """Staff edit. Omitted fields are left unchanged."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth | None = None

    _dob = field_validator("date_of_birth")(_validate_dob)


class PatientSelfUpdate(_Contact):
    """What patients may change themselves (D99): contact details and their
    personal details (name, date of birth, gender). The MRN, status and
    everything clinical stay with the clinic. Omitted fields are unchanged;
    identity changes are written to the audit log with the previous values."""

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    date_of_birth: date | None = None
    sex_at_birth: SexAtBirth | None = None
    # Personal details (D111). Sending null clears one.
    blood_group: BloodGroup | None = None
    marital_status: MaritalStatus | None = None
    # A CNIC for Pakistan (checked and written 12345-1234567-1), otherwise
    # any national ID as given. Never returned: reads show it masked.
    national_id: str | None = Field(default=None, max_length=30)

    _dob = field_validator("date_of_birth")(_validate_dob)

    @field_validator("first_name", "last_name", "national_id", mode="before")
    @classmethod
    def trimmed(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("national_id", mode="before")
    @classmethod
    def blank_id_is_none(cls, value: object) -> object:
        return None if value == "" else value


class PatientRegistration(BaseModel):
    """Self-registration: login + patient profile, created together.

    These are the *only* fields public registration accepts. Anything else in
    the request (role, permissions, mrn, is_active, ...) is dropped by
    validation and never reaches a model: the account is always a patient,
    and the MRN is always generated by the database.
    """

    # Optional for older clients; "doctor" is a different request shape
    # (schemas.registration).
    account_type: Literal["patient"] = "patient"
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    date_of_birth: date
    email: LoginEmail
    password: str = Field(min_length=8, max_length=128)
    phone: str | None = Field(default=None, max_length=30)
    sex_at_birth: SexAtBirth = SexAtBirth.unknown
    # Required when EMAIL_VERIFICATION_REQUIRED is on (the default).
    verification_code: VerificationCode | None = None

    _dob = field_validator("date_of_birth")(_validate_dob)
    _names = field_validator("first_name", "last_name")(clean_name)

    @model_validator(mode="after")
    def full_name_fits_account_name(self):
        # The display name of the login is "first last" in a 100-character column.
        if len(f"{self.first_name} {self.last_name}") > 100:
            raise ValueError("Full name must be at most 100 characters")
        return self


class LinkAccount(BaseModel):
    user_id: uuid.UUID


class PatientAccountCreate(BaseModel):
    """Create a portal login for an existing (walk-in) patient."""

    email: LoginEmail
    password: str = Field(min_length=8, max_length=128)


class PatientRead(BaseModel):
    """The patient's own view."""

    id: uuid.UUID
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: date
    sex_at_birth: SexAtBirth
    phone: str | None
    email: str | None
    address: str | None
    preferred_language: str | None
    emergency_contact_name: str | None = None
    emergency_contact_relationship: str | None = None
    emergency_contact_phone: str | None = None
    preferred_contact_method: str | None = None
    blood_group: str | None = None
    marital_status: str | None = None
    # Only the last three characters: the full ID never leaves the server.
    national_id_masked: str | None = None
    city: str | None = None
    province: str | None = None
    country: str | None = None
    has_account: bool
    photo_url: str | None = None
    created_at: datetime
    updated_at: datetime


class PatientStaffRead(PatientRead):
    """Administrative view for staff. Still no clinical data: that lives in
    clinical tables with their own, stricter access rules."""

    user_id: uuid.UUID | None
    is_active: bool
    registered_by_user_id: uuid.UUID | None


class PatientSummary(BaseModel):
    """Minimal identification, e.g. embedded in an appointment."""

    id: uuid.UUID
    mrn: str
    name: str
    date_of_birth: date
    sex_at_birth: SexAtBirth | None = None
    # Short-lived link to the patient's photo, when the response carries one.
    photo_url: str | None = None


class PatientBulkStatus(BaseModel):
    """Admin > Patients bulk activation (D91)."""

    model_config = ConfigDict(extra="forbid")

    patient_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    is_active: bool


class PatientBulkResult(BaseModel):
    patient_id: uuid.UUID
    ok: bool
    code: str | None = None
    message: str | None = None
