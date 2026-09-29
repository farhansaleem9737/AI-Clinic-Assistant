"""Record-level access decisions (authorization layer 2, architecture §5).

Permissions say what *kind* of thing a caller may do; these functions decide
whether they may touch *this particular row*. Each returns one SQL condition
used by both list and single-record queries, so the two can never disagree.

Denials surface as NotFoundError (404), not 403: for patients and their
appointments, even confirming that a record exists is a disclosure.
"""

import uuid

from sqlalchemy import ColumnElement, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import Perm, Principal
from app.models.appointment import Appointment
from app.models.patient import Patient


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


def appointment_visibility(principal: Principal) -> ColumnElement[bool]:
    """Appointments the caller may see: any (staff), their own (patients),
    or those where they are the doctor (doctors)."""
    if principal.has(Perm.appointment_read_any):
        return true()
    conditions = []
    if principal.has(Perm.appointment_read_own) and principal.patient_id is not None:
        conditions.append(Appointment.patient_id == principal.patient_id)
    if principal.has(Perm.appointment_read_assigned) and principal.doctor_id is not None:
        conditions.append(Appointment.doctor_id == principal.doctor_id)
    return or_(*conditions) if conditions else false()


async def get_readable_patient(db: AsyncSession, principal: Principal, patient_id: uuid.UUID) -> Patient:
    patient = await db.scalar(select(Patient).where(Patient.id == patient_id, patient_visibility(principal)))
    if patient is None:
        raise NotFoundError("Patient not found")
    return patient
