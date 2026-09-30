import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.api.deps.pagination import page_params
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.doctor import (
    DoctorAvailabilityRead,
    DoctorCreate,
    DoctorPublic,
    DoctorResponse,
    DoctorSelfUpdate,
    DoctorUpdate,
)
from app.services import doctor_service
from app.services.doctor_service import DoctorFilters, DoctorRow, DoctorSort
from app.services.pagination import PageParams

router = APIRouter(prefix="/doctors", tags=["doctors"])
public_router = APIRouter(prefix="/public/doctors", tags=["public"])


def doctor_filters(
    department_id: uuid.UUID | None = None,
    specialization: str | None = Query(None, max_length=150),
    q: str | None = Query(None, max_length=100, description="Search doctor name, specialization or department"),
    min_experience: int | None = Query(None, ge=0),
    fee_min: Decimal | None = Query(None, ge=0),
    fee_max: Decimal | None = Query(None, ge=0),
    is_active: bool | None = Query(None, description="Staff listing only"),
    sort: DoctorSort = DoctorSort.name_asc,
) -> DoctorFilters:
    return DoctorFilters(department_id, specialization, q, min_experience, fee_min, fee_max, is_active, sort)


def to_public(row: DoctorRow) -> DoctorPublic:
    d = row.doctor
    return DoctorPublic(
        id=d.id,
        name=row.name,
        title=d.title,
        specialization=d.specialization,
        department_id=d.department_id,
        department_name=row.department_name,
        qualifications=d.qualifications,
        bio=d.bio,
        years_of_experience=d.years_of_experience,
        consultation_fee=d.consultation_fee,
        is_verified=bool(d.license_number),
        availability=DoctorAvailabilityRead(
            status=row.availability.status, next_available=row.availability.next_available
        ),
    )


def to_full(row: DoctorRow) -> DoctorResponse:
    d = row.doctor
    return DoctorResponse(
        **to_public(row).model_dump(),
        user_id=d.user_id,
        email=row.email,
        license_number=d.license_number,
        phone=d.phone,
        room_number=d.room_number,
        is_active=d.is_active,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


# ---- Public directory (no login) -------------------------------------------


@public_router.get("/", response_model=Page[DoctorPublic])
async def public_list_doctors(
    filters: DoctorFilters = Depends(doctor_filters),
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
):
    rows, total = await doctor_service.list_doctors(db, params, filters, public=True)
    return Page(items=[to_public(r) for r in rows], total=total, page=params.page, page_size=params.page_size)


@public_router.get("/specializations", response_model=list[str])
async def public_list_specializations(db: AsyncSession = Depends(get_db)):
    """Options for the directory specialization filter."""
    return await doctor_service.list_specializations(db)


@public_router.get("/{doctor_id}", response_model=DoctorPublic)
async def public_get_doctor(doctor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return to_public(await doctor_service.get_doctor(db, doctor_id, public=True))


# ---- Own profile (the doctor) ----------------------------------------------


@router.get("/me", response_model=DoctorResponse)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_update_own)),
):
    return to_full(await doctor_service.get_own_profile(db, principal))


@router.patch("/me", response_model=DoctorResponse)
async def update_my_profile(
    body: DoctorSelfUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_update_own)),
):
    return to_full(await doctor_service.update_own_profile(db, principal, body))


# ---- Staff management ------------------------------------------------------


@router.get("/", response_model=Page[DoctorResponse])
async def list_doctors(
    filters: DoctorFilters = Depends(doctor_filters),
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.doctor_read)),
):
    rows, total = await doctor_service.list_doctors(db, params, filters, public=False)
    return Page(items=[to_full(r) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("/", response_model=DoctorResponse, status_code=status.HTTP_201_CREATED)
async def create_doctor(
    body: DoctorCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_create)),
):
    return to_full(await doctor_service.create_doctor(db, principal, body))


@router.get("/{doctor_id}", response_model=DoctorResponse)
async def get_doctor(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.doctor_read)),
):
    return to_full(await doctor_service.get_doctor(db, doctor_id))


@router.patch("/{doctor_id}", response_model=DoctorResponse)
async def update_doctor(
    doctor_id: uuid.UUID,
    body: DoctorUpdate,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.doctor_update)),
):
    return to_full(await doctor_service.update_doctor(db, doctor_id, body))


@router.post("/{doctor_id}/deactivate", response_model=DoctorResponse)
async def deactivate_doctor(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.doctor_deactivate)),
):
    return to_full(await doctor_service.set_active(db, doctor_id, active=False))


@router.post("/{doctor_id}/activate", response_model=DoctorResponse)
async def activate_doctor(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.doctor_deactivate)),
):
    return to_full(await doctor_service.set_active(db, doctor_id, active=True))
