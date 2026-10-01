import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.api.deps.pagination import page_params
from app.core import clock
from app.core.config import settings
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.doctor import (
    DoctorAvailabilityRead,
    DoctorCreate,
    DoctorEducationRead,
    DoctorExperienceRead,
    DoctorProfilePublic,
    DoctorPublic,
    DoctorResponse,
    DoctorSelfUpdate,
    DoctorUpdate,
)
from app.schemas.schedule import AvailableDay, PublicAvailabilityRead, SlotRead
from app.services import availability_service, doctor_service
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


@public_router.get("/{doctor_id}", response_model=DoctorProfilePublic)
async def public_get_doctor(doctor_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    profile = await doctor_service.get_public_profile(db, doctor_id)
    return DoctorProfilePublic(
        **to_public(profile.row).model_dump(),
        experience=[DoctorExperienceRead.model_validate(e) for e in profile.experience],
        education=[DoctorEducationRead.model_validate(e) for e in profile.education],
    )


@public_router.get("/{doctor_id}/availability", response_model=PublicAvailabilityRead)
async def public_doctor_availability(
    doctor_id: uuid.UUID,
    date_from: date = Query(description="Local calendar date in the doctor's department timezone"),
    date_to: date = Query(description="Inclusive; at most 31 days after date_from"),
    db: AsyncSession = Depends(get_db),
):
    """Free slots for the booking calendar on the public profile.

    The same computation as the signed-in availability endpoint, with the
    patient booking notice applied. Seeing a slot reserves nothing: booking
    re-checks it.
    """
    await doctor_service.ensure_publicly_listed(db, doctor_id)
    now = clock.utcnow()
    bookable, slots = await availability_service.available_slots(
        db, doctor_id, date_from, date_to, now=now, min_lead=timedelta(minutes=settings.booking_min_lead_minutes)
    )
    tz = bookable.timezone
    return PublicAvailabilityRead(
        doctor_id=doctor_id,
        timezone=tz.key,
        bookable_until=availability_service.bookable_until(now, tz),
        days=[
            AvailableDay(date=day, slots=[SlotRead(starts_at=s.starts_at, ends_at=s.ends_at) for s in day_slots])
            for day, day_slots in availability_service.by_local_date(slots, tz).items()
        ],
    )


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
