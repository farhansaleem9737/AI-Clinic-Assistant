import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.models.appointment import AppointmentStatus, CancellationReason
from app.models.patient import SexAtBirth
from app.schemas.patient import PatientSummary


class AppointmentCreate(BaseModel):
    doctor_id: uuid.UUID
    # Must be the start of a free slot returned by the availability endpoint.
    starts_at: AwareDatetime
    # Staff must name the patient; patients book for themselves and may omit it.
    patient_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)


class AppointmentUpdate(BaseModel):
    """Staff annotations. Time, doctor and patient change only via reschedule."""

    reason: str | None = Field(default=None, max_length=500)
    staff_notes: str | None = Field(default=None, max_length=1000)


class StatusChange(BaseModel):
    status: AppointmentStatus
    # Required when cancelling.
    cancellation_reason: CancellationReason | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def cancellation_needs_reason(self):
        if self.status is AppointmentStatus.cancelled:
            if self.cancellation_reason is None:
                raise ValueError("cancellation_reason is required when cancelling")
            if self.cancellation_reason is CancellationReason.rescheduled:
                raise ValueError("Use the reschedule endpoint to reschedule")
        elif self.cancellation_reason is not None:
            raise ValueError("cancellation_reason is only valid when cancelling")
        return self


class Reschedule(BaseModel):
    starts_at: AwareDatetime
    # Defaults to the same doctor.
    doctor_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class AppointmentDoctor(BaseModel):
    """The doctor as shown on an appointment. Appointment responses only ever
    reach people authorised for that appointment, so the room (where to go)
    is included here even though it is not part of the public directory.
    ``is_verified`` follows the directory's rule (a licence is on file); the
    licence number itself is never sent."""

    id: uuid.UUID
    name: str
    title: str | None
    room_number: str | None
    specialization: str
    department_id: uuid.UUID
    department_name: str
    years_of_experience: int
    is_verified: bool


class AppointmentRead(BaseModel):
    """Patient view. Includes what the caller may do next, so the UI can show
    only valid actions (the API re-checks every action anyway)."""

    id: uuid.UUID
    status: AppointmentStatus
    starts_at: datetime
    ends_at: datetime
    timezone: str
    reason: str | None
    doctor: AppointmentDoctor
    patient: PatientSummary
    cancellation_reason: CancellationReason | None
    cancellation_note: str | None
    cancelled_at: datetime | None
    rescheduled_from_id: uuid.UUID | None
    rescheduled_to_id: uuid.UUID | None
    allowed_transitions: list[AppointmentStatus]
    can_reschedule: bool
    created_at: datetime
    updated_at: datetime


class AppointmentStaffRead(AppointmentRead):
    """Staff and doctor view: adds internal notes and booking provenance."""

    staff_notes: str | None
    booked_by_user_id: uuid.UUID


class AppointmentPatientProfile(BaseModel):
    """The patient's details beyond identification, for the appointment page.
    Never clinical data, never the login."""

    sex_at_birth: SexAtBirth
    phone: str | None
    email: str | None
    address: str | None


class _WithPatientProfile(BaseModel):
    # Null when the caller may see the appointment but not the patient's
    # record (a custom role with appointment but no patient permissions).
    patient_profile: AppointmentPatientProfile | None


class AppointmentDetailRead(AppointmentRead, _WithPatientProfile):
    """Single-appointment view (patient). Lists keep the lighter shape."""


class AppointmentStaffDetailRead(AppointmentStaffRead, _WithPatientProfile):
    """Single-appointment view (staff and doctors)."""


class StatusHistoryRead(BaseModel):
    from_status: AppointmentStatus | None
    to_status: AppointmentStatus
    changed_by_user_id: uuid.UUID | None
    reason: str | None
    changed_at: datetime


class AppointmentCounts(BaseModel):
    """Totals per tab of the appointment list."""

    upcoming: int
    past: int
    all: int
