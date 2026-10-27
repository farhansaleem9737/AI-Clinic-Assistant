"""The public registration request: a patient or a doctor applicant.

``account_type`` chooses the shape. It defaults to "patient", so clients that
predate the doctor option keep working unchanged. Any other value (admin,
receptionist, ...) is a validation error: the allowed account types are a
closed list here, and neither of them grants staff or verified-doctor access.
"""

from typing import Annotated, Any

from pydantic import Discriminator, Tag

from app.schemas.doctor_application import DoctorRegistration
from app.schemas.patient import PatientRegistration


def _account_type(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("account_type", "patient")
    return getattr(value, "account_type", None)


RegistrationRequest = Annotated[
    Annotated[PatientRegistration, Tag("patient")] | Annotated[DoctorRegistration, Tag("doctor")],
    Discriminator(
        _account_type,
        custom_error_type="invalid_account_type",
        custom_error_message="account_type must be 'patient' or 'doctor'",
    ),
]
