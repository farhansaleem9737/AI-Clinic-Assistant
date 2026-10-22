import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_any_permission, require_permission
from app.api.deps.pagination import page_params
from app.api.deps.uploads import read_photo
from app.core.permissions import Perm, Principal
from app.core.storage import Storage, get_optional_storage, get_storage
from app.db.session import get_db
from app.models.patient import Patient
from app.schemas.common import Page
from app.schemas.patient import (
    LinkAccount,
    PatientAccountCreate,
    PatientContactUpdate,
    PatientCreate,
    PatientRead,
    PatientStaffRead,
    PatientUpdate,
)
from app.services import file_service, patient_service
from app.services.pagination import PageParams

router = APIRouter(prefix="/patients", tags=["patients"])

# Anyone who can see patients other than themselves gets the staff view.
STAFF_READ = (Perm.patient_read_any, Perm.patient_read_assigned)
PHOTO_FILE = File(description="JPEG, PNG or WebP, at most 5 MB. Stored as a 512 px WebP without metadata.")


def to_self(p: Patient, storage: Storage | None) -> PatientRead:
    return PatientRead(
        id=p.id,
        mrn=p.mrn,
        first_name=p.first_name,
        last_name=p.last_name,
        date_of_birth=p.date_of_birth,
        sex_at_birth=p.sex_at_birth,
        phone=p.phone,
        email=p.email,
        address=p.address,
        preferred_language=p.preferred_language,
        has_account=p.user_id is not None,
        photo_url=file_service.photo_url(storage, p.photo),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def to_staff(p: Patient, storage: Storage | None) -> PatientStaffRead:
    return PatientStaffRead(
        **to_self(p, storage).model_dump(),
        user_id=p.user_id,
        is_active=p.is_active,
        registered_by_user_id=p.registered_by_user_id,
    )


# ---- Own profile -------------------------------------------------------------


@router.get("/me", response_model=PatientRead)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_read_own)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_self(await patient_service.get_own(db, principal), storage)


@router.post("/me", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
async def complete_my_profile(
    body: PatientCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update_own)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_self(await patient_service.create_own_profile(db, principal, body), storage)


@router.patch("/me", response_model=PatientRead)
async def update_my_contact_details(
    body: PatientContactUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update_own)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_self(await patient_service.update_own_contact(db, principal, body), storage)


@router.put("/me/photo", response_model=PatientRead)
async def upload_my_photo(
    file: UploadFile = PHOTO_FILE,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update_own)),
    storage: Storage = Depends(get_storage),
):
    checked = await read_photo(file)
    return to_self(await patient_service.set_own_photo(db, storage, principal, checked), storage)


@router.delete("/me/photo", response_model=PatientRead)
async def remove_my_photo(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update_own)),
    storage: Storage = Depends(get_storage),
):
    return to_self(await patient_service.remove_own_photo(db, storage, principal), storage)


# ---- Staff ------------------------------------------------------------------


@router.get("/", response_model=Page[PatientStaffRead])
async def list_patients(
    q: str | None = Query(None, max_length=100, description="Name, MRN, phone or email"),
    date_of_birth: date | None = None,
    is_active: bool | None = None,
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*STAFF_READ)),
    storage: Storage | None = Depends(get_optional_storage),
):
    rows, total = await patient_service.list_patients(
        db, principal, params, q=q, date_of_birth=date_of_birth, is_active=is_active
    )
    return Page(items=[to_staff(p, storage) for p in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("/", response_model=PatientStaffRead, status_code=status.HTTP_201_CREATED)
async def register_patient(
    body: PatientCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_create)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_staff(await patient_service.create_patient(db, principal, body), storage)


@router.get("/{patient_id}", response_model=PatientStaffRead | PatientRead)
async def get_patient(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(
        require_any_permission(Perm.patient_read_own, Perm.patient_read_any, Perm.patient_read_assigned)
    ),
    storage: Storage | None = Depends(get_optional_storage),
):
    # Record-level check happens in the service; a record the caller may not
    # see is reported as 404 whether or not it exists.
    patient = await patient_service.get_patient(db, principal, patient_id)
    return to_staff(patient, storage) if principal.has_any(*STAFF_READ) else to_self(patient, storage)


@router.patch("/{patient_id}", response_model=PatientStaffRead)
async def update_patient(
    patient_id: uuid.UUID,
    body: PatientUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_staff(await patient_service.update_patient(db, principal, patient_id, body), storage)


@router.post("/{patient_id}/deactivate", response_model=PatientStaffRead)
async def deactivate_patient(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_deactivate)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_staff(await patient_service.set_active(db, principal, patient_id, active=False), storage)


@router.post("/{patient_id}/activate", response_model=PatientStaffRead)
async def activate_patient(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_deactivate)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_staff(await patient_service.set_active(db, principal, patient_id, active=True), storage)


@router.post("/{patient_id}/link-account", response_model=PatientStaffRead)
async def link_account(
    patient_id: uuid.UUID,
    body: LinkAccount,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_staff(await patient_service.link_account(db, principal, patient_id, body.user_id), storage)


@router.post("/{patient_id}/account", response_model=PatientStaffRead, status_code=status.HTTP_201_CREATED)
async def create_account(
    patient_id: uuid.UUID,
    body: PatientAccountCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_create)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return to_staff(
        await patient_service.create_account(db, principal, patient_id, email=body.email, password=body.password),
        storage,
    )


@router.put("/{patient_id}/photo", response_model=PatientStaffRead)
async def upload_patient_photo(
    patient_id: uuid.UUID,
    file: UploadFile = PHOTO_FILE,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update)),
    storage: Storage = Depends(get_storage),
):
    checked = await read_photo(file)
    return to_staff(await patient_service.set_patient_photo(db, storage, principal, patient_id, checked), storage)


@router.delete("/{patient_id}/photo", response_model=PatientStaffRead)
async def remove_patient_photo(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update)),
    storage: Storage = Depends(get_storage),
):
    return to_staff(await patient_service.remove_patient_photo(db, storage, principal, patient_id), storage)
