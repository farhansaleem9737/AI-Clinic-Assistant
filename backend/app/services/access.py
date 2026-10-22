"""Record-level access decisions (authorization layer 2, architecture §5).

Permissions say what *kind* of thing a caller may do; these functions decide
whether they may touch *this particular row*. Each returns one SQL condition
used by both list and single-record queries, so the two can never disagree.

Denials surface as NotFoundError (404), not 403: for patients and their
appointments, even confirming that a record exists is a disclosure.
"""

import uuid

from sqlalchemy import ColumnElement, false, or_, select, true, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import Perm, Principal
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.patient_document import PatientDocument


def patient_visibility(principal: Principal) -> ColumnElement[bool]:
    """Patients the caller may see: everyone (reception/admin), themselves
    (patients), or people they have an appointment with (doctors)."""
    if principal.has(Perm.patient_read_any):
        return true()
    conditions = []
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


def appointment_visibility(principal: Principal) -> ColumnElement[bool]:
    """Appointments the caller may see: any (staff), their own (patients),
    or those where they are the doctor (doctors)."""
    if principal.has(Perm.appointment_read_any):
        return true()
    return or_(own_appointments(principal), assigned_appointments(principal))


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