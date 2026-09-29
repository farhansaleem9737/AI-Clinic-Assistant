"""Record-level access decisions (authorization layer 2, architecture §5).

Permissions say what *kind* of thing a caller may do; these functions decide
whether they may touch *this particular row*. Every read of a protected
record goes through them — there is no other path.

Denials surface as NotFoundError (404), not 403: for patients and their
appointments, even confirming that a record exists is a disclosure.
"""

import uuid

from sqlalchemy import ColumnElement, false, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.permissions import Perm, Principal
from app.models.patient import Patient


def patient_visibility(principal: Principal) -> ColumnElement[bool]:
    """SQL condition limiting Patient rows to those the caller may see.
    Used for lists and single reads alike, so the two can never disagree."""
    if principal.has(Perm.patient_read_any):
        return true()
    conditions = []
    if principal.has(Perm.patient_read_own):
        conditions.append(Patient.user_id == principal.user_id)
    return or_(*conditions) if conditions else false()


async def get_readable_patient(db: AsyncSession, principal: Principal, patient_id: uuid.UUID) -> Patient:
    patient = await db.scalar(select(Patient).where(Patient.id == patient_id, patient_visibility(principal)))
    if patient is None:
        raise NotFoundError("Patient not found")
    return patient
