import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.api.deps.pagination import page_params
from app.api.deps.uploads import read_photo
from app.core import clock
from app.core.config import settings
from app.core.permissions import Perm, Principal
from app.core.storage import Storage, get_optional_storage, get_storage
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
from app.services import availability_service, doctor_service, file_service
from app.services.doctor_service import DoctorFilters, DoctorRow, DoctorSort
from app.services.pagination import PageParams

router = APIRouter(prefix="/doctors", tags=["doctors"])
public_router = APIRouter(prefix="/public/doctors", tags=["public"])

PHOTO_FILE = File(description="JPEG, PNG or WebP, at most 5 MB. Stored as a 512 px WebP without metadata.")


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


def to_public(row: DoctorRow, storage: Storage | None) -> DoctorPublic:
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
        photo_url=file_service.photo_url(storage, d.photo),
    )


def to_full(row: DoctorRow, storage: Storage | None) -> DoctorResponse:
    d = row.doctor
    return DoctorResponse(
        **to_public(row, storage).model_dump(),
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
    storage: Storage | None = Depends(get_optional_storage),
):
    rows, total = await doctor_service.list_doctors(db, params, filters, public=True)
    return Page(items=[to_public(r, storage) for r in rows], total=total, page=params.page, page_size=params.page_size)


@public_router.get("/specializations", response_model=list[str])
async def public_list_specializations(db: AsyncSession = Depends(get_db)):
    """Options for the directory specialization filter."""
    return await doctor_service.list_specializations(db)


@public_router.get("/{doctor_id}", response_model=DoctorProfilePublic)
async def public_get_doctor(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    storage: Storage | None = Depends(get_optional_storage),
):
    profile = await doctor_service.get_public_profile(db, doctor_id)
    return DoctorProfilePublic(
        **to_public(profile.row, storage).model_dump(),
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
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_full(await doctor_service.get_own_profile(db, principal), storage)


@router.patch("/me", response_model=DoctorResponse)
async def update_my_profile(
    body: DoctorSelfUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_update_own)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_full(await doctor_service.update_own_profile(db, principal, body), storage)


@router.put("/me/photo", response_model=DoctorResponse)
async def upload_my_photo(
    file: UploadFile = PHOTO_FILE,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_update_own)),
    storage: Storage = Depends(get_storage),
):
    checked = await read_photo(file)
    row = await doctor_service.set_photo(db, storage, principal, doctor_service.own_doctor_id(principal), checked)
    return to_full(row, storage)


@router.delete("/me/photo", response_model=DoctorResponse)
async def remove_my_photo(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_update_own)),
    storage: Storage = Depends(get_storage),
):
    row = await doctor_service.remove_photo(db, storage, principal, doctor_service.own_doctor_id(principal))
    return to_full(row, storage)


# ---- Staff management ------------------------------------------------------


@router.get("/", response_model=Page[DoctorResponse])
async def list_doctors(
    filters: DoctorFilters = Depends(doctor_filters),
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_read)),
    storage: Storage | None = Depends(get_optional_storage),
):
    rows, total = await doctor_service.list_doctors(db, params, filters, public=False)
    return Page(items=[to_full(r, storage) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("/", response_model=DoctorResponse, status_code=status.HTTP_201_CREATED)
async def create_doctor(
    body: DoctorCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_create)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_full(await doctor_service.create_doctor(db, principal, body), storage)


@router.get("/{doctor_id}", response_model=DoctorResponse)
async def get_doctor(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_read)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_full(await doctor_service.get_doctor(db, doctor_id), storage)


@router.patch("/{doctor_id}", response_model=DoctorResponse)
async def update_doctor(
    doctor_id: uuid.UUID,
    body: DoctorUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_update)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_full(await doctor_service.update_doctor(db, doctor_id, body), storage)


@router.post("/{doctor_id}/deactivate", response_model=DoctorResponse)
async def deactivate_doctor(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_deactivate)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_full(await doctor_service.set_active(db, doctor_id, active=False), storage)


@router.post("/{doctor_id}/activate", response_model=DoctorResponse)
async def activate_doctor(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_deactivate)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_full(await doctor_service.set_active(db, doctor_id, active=True), storage)


@router.put("/{doctor_id}/photo", response_model=DoctorResponse)
async def upload_doctor_photo(
    doctor_id: uuid.UUID,
    file: UploadFile = PHOTO_FILE,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_update)),
    storage: Storage = Depends(get_storage),
):
    checked = await read_photo(file)
    return to_full(await doctor_service.set_photo(db, storage, principal, doctor_id, checked), storage)


@router.delete("/{doctor_id}/photo", response_model=DoctorResponse)
async def remove_doctor_photo(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_update)),
    storage: Storage = Depends(get_storage),
):
    return to_full(await doctor_service.remove_photo(db, storage, principal, doctor_id), storage)
