"""Allergies, diagnoses and medications in a patient's record (D112).

    GET    /patients/{patient_id}/health-records                 all three, and what the caller may add
    POST   /patients/{patient_id}/health-records/{kind}          add an entry
    PUT    /patients/{patient_id}/health-records/{kind}/{id}     replace an entry
    DELETE /patients/{patient_id}/health-records/{kind}/{id}     remove (hidden, kept)

`kind` is allergies, diagnoses or medications. The service decides who may do
what with each entry (health_record_service).
"""

import uuid

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_any_permission
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.models.health_record import HealthRecordMixin
from app.schemas.health_record import (
    AllergyRead,
    AllergyWrite,
    DiagnosisRead,
    DiagnosisWrite,
    HealthRecords,
    MedicationRead,
    MedicationWrite,
)
from app.services import health_record_service as service

router = APIRouter(prefix="/patients/{patient_id}/health-records", tags=["health records"])

READ = (Perm.health_record_read_own, Perm.health_record_read_assigned)
WRITE = (Perm.health_record_report_own, Perm.health_record_write_assigned)
READ_SCHEMAS: dict[str, type[BaseModel]] = {
    "allergies": AllergyRead,
    "diagnoses": DiagnosisRead,
    "medications": MedicationRead,
}


def _read(
    kind: str, entry: HealthRecordMixin, access: service.Access, principal: Principal, recorded_by: str | None
) -> BaseModel:
    schema = READ_SCHEMAS[kind]
    own = {name: getattr(entry, name) for name in schema.model_fields if hasattr(entry, name)}
    return schema(
        **own,
        recorded_by=recorded_by,
        recorded_by_me=entry.recorded_by_user_id == principal.user_id,
        can_edit=access.may_edit(kind, entry, principal.user_id),
    )


@router.get("", response_model=HealthRecords)
async def list_health_records(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*READ)),
):
    records = await service.list_records(db, principal, patient_id)
    shown = {
        kind: [
            _read(kind, e, records.access, principal, records.names.get(e.recorded_by_user_id) if e.source == "clinician" else None)
            for e in entries
        ]
        for kind, entries in records.entries.items()
    }
    return HealthRecords(
        **shown,
        can_add_allergies=records.access.may_add("allergies"),
        can_add_diagnoses=records.access.may_add("diagnoses"),
        can_add_medications=records.access.may_add("medications"),
    )


def _routes(kind: service.Kind, write: type[BaseModel], read: type[BaseModel]) -> None:
    async def add(
        patient_id: uuid.UUID,
        data: write,  # type: ignore[valid-type]
        db: AsyncSession = Depends(get_db),
        principal: Principal = Depends(require_any_permission(*WRITE)),
    ):
        entry, access = await service.add(db, principal, patient_id, kind, data)
        return _read(kind, entry, access, principal, await service.recorder_name(db, entry))

    async def replace(
        patient_id: uuid.UUID,
        entry_id: uuid.UUID,
        data: write,  # type: ignore[valid-type]
        db: AsyncSession = Depends(get_db),
        principal: Principal = Depends(require_any_permission(*WRITE)),
    ):
        entry, access = await service.update(db, principal, patient_id, kind, entry_id, data)
        return _read(kind, entry, access, principal, await service.recorder_name(db, entry))

    async def remove(
        patient_id: uuid.UUID,
        entry_id: uuid.UUID,
        db: AsyncSession = Depends(get_db),
        principal: Principal = Depends(require_any_permission(*WRITE)),
    ):
        await service.remove(db, principal, patient_id, kind, entry_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    router.add_api_route(
        f"/{kind}", add, methods=["POST"], response_model=read, status_code=status.HTTP_201_CREATED, name=f"add_{kind}"
    )
    router.add_api_route(f"/{kind}/{{entry_id}}", replace, methods=["PUT"], response_model=read, name=f"update_{kind}")
    router.add_api_route(
        f"/{kind}/{{entry_id}}", remove, methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT, name=f"remove_{kind}"
    )


_routes("allergies", AllergyWrite, AllergyRead)
_routes("diagnoses", DiagnosisWrite, DiagnosisRead)
_routes("medications", MedicationWrite, MedicationRead)
