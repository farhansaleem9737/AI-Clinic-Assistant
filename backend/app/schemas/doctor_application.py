import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.doctor_application import ApplicationStatus, CredentialType
from app.schemas.common import LoginEmail, clean_name
from app.schemas.doctor import FEE_FIELD

_TEXT_FIELDS = (
    "license_number",
    "registration_authority",
    "specialization",
    "qualifications",
    "institution",
    "bio",
    "languages",
    "phone",
)


class ProfessionalDetails(BaseModel):
    """What a doctor may tell us about themselves before verification.

    Every field is optional: registration never requires credentials (D77).
    What approval requires is ``doctor_application_service.missing_for_approval``.
    """

    license_number: str | None = Field(default=None, max_length=50)
    # Who issued the licence, e.g. "PMDC" or "General Medical Council". Free text: not limited to one country.
    registration_authority: str | None = Field(default=None, max_length=150)
    specialization: str | None = Field(default=None, max_length=150)
    department_id: uuid.UUID | None = None
    years_of_experience: int | None = Field(default=None, ge=0, le=80)
    qualifications: str | None = Field(default=None, max_length=500)
    institution: str | None = Field(default=None, max_length=200)
    bio: str | None = Field(default=None, max_length=1000)
    consultation_fee: Decimal | None = Field(default=None, **FEE_FIELD)
    languages: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=30)

    @field_validator(*_TEXT_FIELDS, mode="before")
    @classmethod
    def blank_is_none(cls, value: object) -> object:
        # An empty box means "not provided", never an empty string in the database.
        if isinstance(value, str):
            return value.strip() or None
        return value


class DoctorRegistration(ProfessionalDetails):
    """Public sign-up as a doctor. Creates a login with the doctor_applicant
    role and a pending application — never a verified doctor. Fields not
    listed here (role, status, is_verified, ...) are dropped by validation."""

    account_type: Literal["doctor"]
    name: str = Field(min_length=1, max_length=100)
    email: LoginEmail
    password: str = Field(min_length=8, max_length=128)

    _name = field_validator("name")(clean_name)


class DoctorApplicationUpdate(ProfessionalDetails):
    """The applicant completing their details. Omitted fields are unchanged;
    an explicit null (or empty text) clears one."""


class ApplicationDocumentRead(BaseModel):
    id: uuid.UUID
    document_type: CredentialType
    # As the applicant named it; shown back to them and to reviewers only.
    filename: str | None
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class DoctorApplicationRead(BaseModel):
    id: uuid.UUID
    status: ApplicationStatus
    name: str
    email: str
    license_number: str | None
    registration_authority: str | None
    specialization: str | None
    department_id: uuid.UUID | None
    department_name: str | None
    years_of_experience: int | None
    qualifications: str | None
    institution: str | None
    bio: str | None
    consultation_fee: Decimal | None
    languages: str | None
    phone: str | None
    submitted_at: datetime
    reviewed_at: datetime | None
    review_notes: str | None
    doctor_id: uuid.UUID | None
    documents: list[ApplicationDocumentRead]
    # What an administrator still needs before approving (field or document names).
    missing_for_approval: list[str]


class DoctorApplicationSummary(BaseModel):
    id: uuid.UUID
    status: ApplicationStatus
    name: str
    email: str
    specialization: str | None
    department_name: str | None
    document_count: int
    submitted_at: datetime


class ApplicationApproval(BaseModel):
    notes: str | None = Field(default=None, max_length=1000)


class ApplicationRejection(BaseModel):
    # The applicant sees this: say what is wrong or missing.
    notes: str = Field(min_length=1, max_length=1000)

    @field_validator("notes")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Give the reason for the rejection")
        return value
