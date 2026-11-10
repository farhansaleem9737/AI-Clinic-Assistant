import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.common import Gender, LoginEmail, adult_birth_date, check_birth_date

# Roles whose holders must be at least 18 years old.
ADULT_ROLES = {"doctor", "receptionist"}


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: EmailStr
    is_active: bool
    roles: list[str]
    created_at: datetime


class AdminUserRead(UserResponse):
    """A user as listed in Admin > Users. Phone and photo come from the
    linked doctor or patient profile, when there is one."""

    phone: str | None = None
    photo_url: str | None = None
    doctor_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None


class BulkStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    is_active: bool


class BulkStatusResult(BaseModel):
    user_id: uuid.UUID
    ok: bool
    code: str | None = None
    message: str | None = None


class MeResponse(UserResponse):
    permissions: list[str]
    doctor_id: uuid.UUID | None = None
    patient_id: uuid.UUID | None = None
    # Short-lived link to the user's own profile photo (doctor or patient), if any.
    photo_url: str | None = None


class UserLogin(BaseModel):
    email: LoginEmail
    password: str = Field(max_length=128)
    # Keep the session after the browser closes. Off by default: a shared
    # clinic computer should not stay signed in.
    remember_me: bool = False


class PasswordChange(BaseModel):
    """The signed-in user's new password (D116). `current_password` is needed
    unless the session was signed in to moments ago (the server decides)."""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=8, max_length=128)
    current_password: str | None = Field(default=None, min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    """Forgot password (D126): the account's email address."""

    model_config = ConfigDict(extra="forbid")

    email: LoginEmail


class PasswordResetToken(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # secrets.token_urlsafe(32) is 43 characters; anything else cannot be a link we sent.
    token: str = Field(min_length=20, max_length=128)


class PasswordReset(PasswordResetToken):
    # The same rule as everywhere else a password is set (registration, change).
    new_password: str = Field(min_length=8, max_length=128)


class MessageResponse(BaseModel):
    message: str


class PasswordChangeStatus(BaseModel):
    current_password_required: bool
    min_length: int = 8
    max_length: int = 128


class AccessTokenResponse(BaseModel):
    """The refresh token never appears in a body: it travels only in an
    HttpOnly cookie that JavaScript cannot read."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class AccountCreate(BaseModel):
    """Admin-created account. Roles are granted in the same transaction."""

    name: str = Field(min_length=1, max_length=100)
    email: LoginEmail
    password: str = Field(min_length=8, max_length=128)
    roles: list[str] = Field(min_length=1)
    date_of_birth: date | None = None
    gender: Gender | None = None

    @model_validator(mode="after")
    def staff_are_adults(self):
        # Clinical and front-desk staff must be at least 18; other dates still need to be plausible.
        if self.date_of_birth is not None:
            check_birth_date(self.date_of_birth)
        if set(self.roles) & ADULT_ROLES:
            if self.date_of_birth is None:
                raise ValueError("Date of birth is required for doctors and receptionists")
            adult_birth_date(self.date_of_birth)
        return self


class UserUpdate(BaseModel):
    # Only these fields; anything else ("roles", "is_active", ...) is a 422.
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    email: LoginEmail | None = None


class RolesUpdate(BaseModel):
    roles: list[str] = Field(min_length=1)


class RoleResponse(BaseModel):
    code: str
    name: str
    description: str | None
    permissions: list[str]
