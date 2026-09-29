import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.core.permissions import Perm
from app.db.session import get_db
from app.schemas.doctor import DoctorCreate, DoctorResponse, DoctorUpdate
from app.services import doctor_service
from app.services.doctor_service import DoctorWithName

router = APIRouter(prefix="/doctors", tags=["doctors"])


def _doctor_response(row: DoctorWithName) -> DoctorResponse:
    """Combine a Doctor row with the name from its related User row.

    The Doctor table deliberately stores no name — identity fields live on User
    — so every response has to carry the name across from there.
    """
    doctor = row.doctor
    return DoctorResponse(
        id=doctor.id,
        user_id=doctor.user_id,
        name=row.name,
        department_id=doctor.department_id,
        specialization=doctor.specialization,
        bio=doctor.bio,
        years_of_experience=doctor.years_of_experience,
        consultation_fee=doctor.consultation_fee,
        created_at=doctor.created_at,
        updated_at=doctor.updated_at,
    )


@router.post("/", response_model=DoctorResponse, status_code=status.HTTP_201_CREATED)
async def create_doctor(
    doctor_in: DoctorCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(Perm.doctor_create)),
):
    return _doctor_response(await doctor_service.create_doctor(db, doctor_in))


@router.get("/", response_model=list[DoctorResponse])
async def list_doctors(db: AsyncSession = Depends(get_db)):
    return [_doctor_response(row) for row in await doctor_service.list_doctors(db)]


@router.get("/{doctor_id}", response_model=DoctorResponse)
async def get_doctor(doctor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return _doctor_response(await doctor_service.get_doctor(db, doctor_id))


@router.put("/{doctor_id}", response_model=DoctorResponse)
async def update_doctor(
    doctor_id: uuid.UUID,
    doctor_in: DoctorUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(Perm.doctor_update)),
):
    return _doctor_response(await doctor_service.update_doctor(db, doctor_id, doctor_in))


@router.delete("/{doctor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_doctor(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(Perm.doctor_deactivate)),
):
    await doctor_service.delete_doctor(db, doctor_id)
