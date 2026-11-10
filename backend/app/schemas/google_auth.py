"""Continue with Google (D123): the request and response shapes.

A Google registration is the normal registration form (same fields, same
rules, same closed list of account types: patient or doctor applicant) minus
what Google already proved: the email address comes from the verified Google
identity, and there is no password and no emailed code. Sending any of those is
refused rather than ignored.
"""

from typing import Annotated, Any

from pydantic import BaseModel, Discriminator, Field, Tag

from app.schemas.doctor_application import DoctorRegistration
from app.schemas.patient import PatientRegistration


class GooglePatientSignup(PatientRegistration):
    email: None = None
    password: None = None
    verification_code: None = None


class GoogleDoctorSignup(DoctorRegistration):
    email: None = None
    password: None = None
    verification_code: None = None


def _account_type(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("account_type", "patient")
    return getattr(value, "account_type", None)


GoogleSignupRequest = Annotated[
    Annotated[GooglePatientSignup, Tag("patient")] | Annotated[GoogleDoctorSignup, Tag("doctor")],
    Discriminator(
        _account_type,
        custom_error_type="invalid_account_type",
        custom_error_message="account_type must be 'patient' or 'doctor'",
    ),
]


class SignInProviders(BaseModel):
    google: bool


class GooglePrefill(BaseModel):
    """What Google shared, to prefill the registration form."""

    email: str
    given_name: str | None
    family_name: str | None


class GoogleIdentityStatus(BaseModel):
    enabled: bool
    linked: bool
    email: str | None
    # False: Google is this account's only sign-in method (unlinking is refused).
    has_password: bool


class GoogleLinkStart(BaseModel):
    authorize_url: str


class Reauthentication(BaseModel):
    # Needed unless this session signed in within the last few minutes.
    current_password: str | None = Field(default=None, max_length=128)
