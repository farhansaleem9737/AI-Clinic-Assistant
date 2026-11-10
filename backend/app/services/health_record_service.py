"""Allergies, diagnoses and medications in a patient's record (D112).

Who may do what (the API checks every request; the UI only follows `can_edit`
and the `can_add_*` flags it gets back):

- **read:** the patient (their own record) and doctors who have an appointment
  with them (as for documents). Reception and admins: nothing (clinical).
- **allergies, medications:** the patient adds their own ("reported by you")
  and edits or removes only what they added; a treating doctor adds, edits
  and removes any entry, including a patient-reported one they correct.
- **diagnoses:** treating doctors only; the patient reads them.

Removing hides an entry and keeps the row (who, when): clinical history is
never deleted. Denials are 404 like the rest of the patient record.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.core.permissions import Perm, Principal
from app.models.appointment import Appointment
from app.models.doctor import Doctor
from app.models.health_record import HealthRecordMixin, PatientAllergy, PatientDiagnosis, PatientMedication
from app.models.patient import Patient
from app.models.user import User

logger = logging.getLogger(__name__)

Kind = Literal["allergies", "diagnoses", "medications"]
MODELS: dict[str, type[HealthRecordMixin]] = {
    "allergies": PatientAllergy,
    "diagnoses": PatientDiagnosis,
    "medications": PatientMedication,
}
# What a patient may report about themselves.
PATIENT_REPORTED = ("allergies", "medications")


@dataclass(frozen=True)
class Access:
    own: bool  # the caller's own record, and they may report in it
    clinician: bool  # a treating doctor who may record

    def may_add(self, kind: str) -> bool:
        return self.clinician or (self.own and kind in PATIENT_REPORTED)

    def may_edit(self, kind: str, entry: HealthRecordMixin, user_id: uuid.UUID) -> bool:
        if self.clinician:
            return True
        return self.own and kind in PATIENT_REPORTED and entry.recorded_by_user_id == user_id


async def may_read(db: AsyncSession, principal: Principal, patient_id: uuid.UUID) -> bool:
    """Whether this caller may read the patient's record (the same rule as the API):
    used to authorize watching it for live updates (D122)."""
    try:
        await _access(db, principal, patient_id)
    except NotFoundError:
        return False
    return True


async def _access(db: AsyncSession, principal: Principal, patient_id: uuid.UUID) -> Access:
    own_patient = principal.patient_id is not None and principal.patient_id == patient_id
    reads_own = own_patient and principal.has(Perm.health_record_read_own)
    treats = False
    if principal.doctor_id is not None and principal.has_any(
        Perm.health_record_read_assigned, Perm.health_record_write_assigned
    ):
        treats = bool(
            await db.scalar(
                select(
                    exists().where(Appointment.patient_id == patient_id, Appointment.doctor_id == principal.doctor_id)
                )
            )
        )
    if not (reads_own or (treats and principal.has(Perm.health_record_read_assigned))):
        raise NotFoundError("Patient not found")
    if await db.get(Patient, patient_id) is None:
        raise NotFoundError("Patient not found")
    return Access(
        own=reads_own and principal.has(Perm.health_record_report_own),
        clinician=treats and principal.has(Perm.health_record_write_assigned),
    )


async def _recorder_names(db: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    rows = await db.execute(
        select(User.id, User.name, Doctor.id.label("doctor_id"), Doctor.title)
        .outerjoin(Doctor, Doctor.user_id == User.id)
        .where(User.id.in_(user_ids))
    )
    return {r.id: f"{r.title or 'Dr.'} {r.name}" if r.doctor_id else r.name for r in rows}


def _sort_key(entry: HealthRecordMixin):
    # Current ones (allergies always are) first, then the newest.
    return (getattr(entry, "status", "active") != "active", -entry.created_at.timestamp())


@dataclass
class Records:
    entries: dict[str, list[HealthRecordMixin]]
    names: dict[uuid.UUID, str]  # clinicians who recorded entries
    access: Access


async def list_records(db: AsyncSession, principal: Principal, patient_id: uuid.UUID) -> Records:
    access = await _access(db, principal, patient_id)
    entries: dict[str, list[HealthRecordMixin]] = {}
    for kind, model in MODELS.items():
        rows = await db.scalars(select(model).where(model.patient_id == patient_id, model.removed_at.is_(None)))
        entries[kind] = sorted(rows, key=_sort_key)
    names = await _recorder_names(
        db, {e.recorded_by_user_id for rows in entries.values() for e in rows if e.source == "clinician"}
    )
    return Records(entries, names, access)


async def _entry(db: AsyncSession, kind: str, patient_id: uuid.UUID, entry_id: uuid.UUID) -> HealthRecordMixin:
    model = MODELS[kind]
    entry = await db.scalar(
        select(model).where(model.id == entry_id, model.patient_id == patient_id, model.removed_at.is_(None))
    )
    if entry is None:
        raise NotFoundError("Entry not found")
    return entry


async def _save(db: AsyncSession, kind: str) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if kind == "allergies" and "uq_patient_allergies_current_substance" in str(exc.orig):
            raise ConflictError("This allergy is already in the record", code="ALLERGY_EXISTS") from None
        raise


async def add(
    db: AsyncSession, principal: Principal, patient_id: uuid.UUID, kind: Kind, data: BaseModel
) -> tuple[HealthRecordMixin, Access]:
    access = await _access(db, principal, patient_id)
    if not access.may_add(kind):
        raise PermissionDeniedError(
            "Only a doctor treating this patient can record a diagnosis"
            if kind == "diagnoses"
            else "You cannot add to this record"
        )
    # A patient's own entry is "reported"; a doctor's (even about themselves as
    # a patient) is clinical only when they record it as the treating doctor.
    source = "patient" if access.own and kind in PATIENT_REPORTED and not access.clinician else "clinician"
    entry = MODELS[kind](
        patient_id=patient_id, source=source, recorded_by_user_id=principal.user_id, **data.model_dump()
    )
    db.add(entry)
    await _save(db, kind)
    await db.refresh(entry)
    logger.info("health_record_added", extra={"kind": kind, "entry_id": str(entry.id), "by": str(principal.user_id)})
    return entry, access


async def update(
    db: AsyncSession, principal: Principal, patient_id: uuid.UUID, kind: Kind, entry_id: uuid.UUID, data: BaseModel
) -> tuple[HealthRecordMixin, Access]:
    access = await _access(db, principal, patient_id)
    entry = await _entry(db, kind, patient_id, entry_id)
    if not access.may_edit(kind, entry, principal.user_id):
        raise PermissionDeniedError("You cannot change this entry")
    for field, value in data.model_dump().items():
        setattr(entry, field, value)
    await _save(db, kind)
    await db.refresh(entry)
    logger.info("health_record_updated", extra={"kind": kind, "entry_id": str(entry.id), "by": str(principal.user_id)})
    return entry, access


async def remove(db: AsyncSession, principal: Principal, patient_id: uuid.UUID, kind: Kind, entry_id: uuid.UUID) -> None:
    access = await _access(db, principal, patient_id)
    entry = await _entry(db, kind, patient_id, entry_id)
    if not access.may_edit(kind, entry, principal.user_id):
        raise PermissionDeniedError("You cannot remove this entry")
    entry.removed_at = clock.utcnow()
    entry.removed_by_user_id = principal.user_id
    await db.commit()
    logger.info("health_record_removed", extra={"kind": kind, "entry_id": str(entry_id), "by": str(principal.user_id)})


async def recorder_name(db: AsyncSession, entry: HealthRecordMixin) -> str | None:
    if entry.source != "clinician":
        return None
    return (await _recorder_names(db, {entry.recorded_by_user_id})).get(entry.recorded_by_user_id)
