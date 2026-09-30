from datetime import date

from pydantic import BaseModel


class AccountSummary(BaseModel):
    is_active: bool
    roles: list[str]


class PatientSummary(BaseModel):
    """The caller's own appointments as a patient."""

    has_profile: bool
    # False when reception has deactivated the patient record.
    profile_active: bool
    upcoming_appointments: int
    total_appointments: int
    # Distinct doctors the patient has (non-cancelled) appointments with.
    my_doctors: int


class TodayCounts(BaseModel):
    """Appointments on one local calendar day, by where they are in the visit."""

    date: date
    timezone: str
    total: int
    awaiting_check_in: int
    checked_in: int
    in_progress: int
    completed: int
    cancelled: int
    no_show: int


class DoctorSummary(BaseModel):
    """Appointments where the caller is the doctor."""

    has_profile: bool
    today: TodayCounts | None
    upcoming_appointments: int
    # Distinct patients with (non-cancelled) appointments with this doctor.
    my_patients: int


class FrontDeskSummary(BaseModel):
    """Clinic-wide appointment workload (needs appointment:read_any)."""

    today: TodayCounts
    upcoming_appointments: int


class OverviewSummary(BaseModel):
    """Clinic totals. Each figure is present only if the caller holds the
    permission that lets them list those records; otherwise it is null."""

    users_total: int | None = None
    users_active: int | None = None
    doctors_active: int | None = None
    departments_active: int | None = None
    patients_total: int | None = None
    patients_active: int | None = None
    appointments_total: int | None = None


class DashboardSummary(BaseModel):
    """Sections the caller is not entitled to are null."""

    account: AccountSummary
    patient: PatientSummary | None = None
    doctor: DoctorSummary | None = None
    front_desk: FrontDeskSummary | None = None
    overview: OverviewSummary | None = None
