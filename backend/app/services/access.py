"""Record-level access decisions (authorization layer 2, architecture §5).

Permissions say what *kind* of thing a caller may do; these functions decide
whether they may touch *this particular row*. Each returns one SQL condition
used by both list and single-record queries, so the two can never disagree.

Denials surface as NotFoundError (404), not 403: for patients and their
appointments, even confirming that a record exists is a disclosure.
"""

import uuid

from sqlalchemy import ColumnElement, and_, exists, false, not_, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import AssignmentPermission, Perm, Principal
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.patient_document import PatientDocument


def _delegated_patients(principal: Principal) -> ColumnElement[bool] | None:
    """A doctor's receptionist (D131) sees that doctor's patients (anyone with an
    appointment with them), plus patients they registered themselves who have
    no appointment with anyone yet, so a new patient can be booked. A patient
    seen by another doctor only is never visible through this doctor."""
    d = principal.delegation
    if d is None or not d.allows(AssignmentPermission.patients_view):
        return None
    return or_(
        Patient.id.in_(select(Appointment.patient_id).where(Appointment.doctor_id == d.doctor_id)),
        and_(
            Patient.registered_by_user_id == principal.user_id,
            not_(exists().where(Appointment.patient_id == Patient.id)),
        ),
    )


def patient_visibility(principal: Principal) -> ColumnElement[bool]:
    """Patients the caller may see: everyone (reception/admin), themselves
    (patients), people they have an appointment with (doctors), or the patients
    of the doctor a receptionist is working for (D131)."""
    if principal.has(Perm.patient_read_any):
        return true()
    conditions = []
    if (delegated := _delegated_patients(principal)) is not None:
        conditions.append(delegated)
    if principal.has(Perm.patient_read_own):
        conditions.append(Patient.user_id == principal.user_id)
    if principal.has(Perm.patient_read_assigned) and principal.doctor_id is not None:
        conditions.append(
            Patient.id.in_(select(Appointment.patient_id).where(Appointment.doctor_id == principal.doctor_id))
        )
    return or_(*conditions) if conditions else false()


def own_appointments(principal: Principal) -> ColumnElement[bool]:
    """Appointments where the caller is the patient."""
    if principal.has(Perm.appointment_read_own) and principal.patient_id is not None:
        return Appointment.patient_id == principal.patient_id
    return false()


def assigned_appointments(principal: Principal) -> ColumnElement[bool]:
    """Appointments where the caller is the doctor."""
    if principal.has(Perm.appointment_read_assigned) and principal.doctor_id is not None:
        return Appointment.doctor_id == principal.doctor_id
    return false()


def delegated_appointments(principal: Principal) -> ColumnElement[bool]:
    """Appointments of the doctor a receptionist is working for (D131)."""
    d = principal.delegation
    if d is not None and d.allows(AssignmentPermission.appointments_view):
        return Appointment.doctor_id == d.doctor_id
    return false()


def appointment_visibility(principal: Principal) -> ColumnElement[bool]:
    """Appointments the caller may see: any (staff), their own (patients),
    those where they are the doctor (doctors), or those of the doctor a
    receptionist is working for (D131). Every appointment change loads its row
    through this, so lent permissions never reach another doctor's rows."""
    if principal.has(Perm.appointment_read_any):
        return true()
    return or_(own_appointments(principal), assigned_appointments(principal), delegated_appointments(principal))


def ensure_delegated_doctor(principal: Principal, doctor_id: uuid.UUID) -> None:
    """A receptionist working for one doctor can only book or move appointments
    with that doctor, whatever doctor id the request names (D131)."""
    if principal.delegation is not None and doctor_id != principal.delegation.doctor_id:
        raise NotFoundError("Doctor not found")


async def get_readable_patient(db: AsyncSession, principal: Principal, patient_id: uuid.UUID) -> Patient:
    patient = await db.scalar(select(Patient).where(Patient.id == patient_id, patient_visibility(principal)))
    if patient is None:
        raise NotFoundError("Patient not found")
    return patient


# ---- Patient documents -------------------------------------------------------
# Clinical content: the patient, and doctors with an appointment with them.
# Each scope takes the patient-id column it filters (Patient.id or
# PatientDocument.patient_id), so the same rule serves both queries.

def _treated_patient_ids(doctor_id: uuid.UUID):
    return select(Appointment.patient_id).where(Appointment.doctor_id == doctor_id)


def _patient_scope(principal: Principal, patient_id, *, own: Perm, assigned: Perm) -> ColumnElement[bool]:
    conditions=[]
    if principal.has(own) and principal.patient_id is not None:
        conditions.append(patient_id == principal.patient_id)
    if principal.has(assigned) and principal.doctor_id is not None:
        conditions.append(patient_id.in_(_treated_patient_ids(principal.doctor_id)))
    return or_(*conditions) if conditions else false()

def document_read_scope(principal: Principal, patient_id) -> ColumnElement[bool]:
    return _patient_scope(
        principal, patient_id, own=Perm.document_read_own, assigned=Perm.document_read_assigned
    )

def document_upload_scope(principal: Principal, patient_id) -> ColumnElement[bool]:
    return _patient_scope(
        principal, patient_id, own=Perm.document_upload_own, assigned=Perm.document_upload_assigned
    )

def  document_retract_scope(principal: Principal) -> ColumnElement[bool]:
    """Patients retract only what they uploaded themselves; doctors anything
    in the record of a patient they treat."""
    conditions=[]
    if principal.has(Perm.document_retract_own) and principal.patient_id is not None:
        conditions.append(
            and_(
                PatientDocument.patient_id==principal.patient_id,
                PatientDocument.uploaded_by_user_id==principal.user_id
            )
        )
    if principal.has(Perm.document_retract_assigned) and principal.doctor_id is not None:
        conditions.append(PatientDocument.patient_id.in_(_treated_patient_ids(principal.doctor_id)))
    return or_(*conditions) if conditions else false()


async def get_patient_in_scope(db: AsyncSession, patient_id: uuid.UUID, scope: ColumnElement[bool]) -> Patient:
    patient=await db.scalar(select(Patient).where(Patient.id==patient_id, scope))
    if patient is None:
        raise NotFoundError("Patient not found")
    return patient