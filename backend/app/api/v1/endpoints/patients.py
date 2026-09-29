import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_any_permission, require_permission
from app.api.deps.pagination import page_params
from app.core.permissions import Perm, Principal
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
from app.services import patient_service
from app.services.pagination import PageParams

router = APIRouter(prefix="/patients", tags=["patients"])

# Anyone who can see patients other than themselves gets the staff view.
STAFF_READ = (Perm.patient_read_any, Perm.patient_read_assigned)


def to_self(p: Patient) -> PatientRead:
    return PatientRead(
        id=p.id,
        mrn=p.mrn,
        first_name=p.first_name,
        last_name=p.last_name,
        date_of_birth=p.date_of_birth,
        sex_at_birth=p.sex_at_birth,
        gender_identity=p.gender_identity,
        phone=p.phone,
        email=p.email,
        address=p.address,
        preferred_language=p.preferred_language,
        has_account=p.user_id is not None,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def to_staff(p: Patient) -> PatientStaffRead:
    return PatientStaffRead(
        **to_self(p).model_dump(),
        user_id=p.user_id,
        is_active=p.is_active,
        registered_by_user_id=p.registered_by_user_id,
    )


# ---- Own profile -------------------------------------------------------------


@router.get("/me", response_model=PatientRead)
async def get_my_profile(
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_read_own)),
):
    return to_self(await patient_service.get_own(db, principal))


@router.post("/me", response_model=PatientRead, status_code=status.HTTP_201_CREATED)
async def complete_my_profile(
    body: PatientCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update_own)),
):
    return to_self(await patient_service.create_own_profile(db, principal, body))


@router.patch("/me", response_model=PatientRead)
async def update_my_contact_details(
    body: PatientContactUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update_own)),
):
    return to_self(await patient_service.update_own_contact(db, principal, body))


# ---- Staff ------------------------------------------------------------------


@router.get("/", response_model=Page[PatientStaffRead])
async def list_patients(
    q: str | None = Query(None, max_length=100, description="Name, MRN, phone or email"),
    date_of_birth: date | None = None,
    is_active: bool | None = None,
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_any_permission(*STAFF_READ)),
):
    rows, total = await patient_service.list_patients(
        db, principal, params, q=q, date_of_birth=date_of_birth, is_active=is_active
    )
    return Page(items=[to_staff(p) for p in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("/", response_model=PatientStaffRead, status_code=status.HTTP_201_CREATED)
async def register_patient(
    body: PatientCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_create)),
):
    return to_staff(await patient_service.create_patient(db, principal, body))


@router.get("/{patient_id}", response_model=PatientStaffRead | PatientRead)
async def get_patient(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(
        require_any_permission(Perm.patient_read_own, Perm.patient_read_any, Perm.patient_read_assigned)
    ),
):
    # Record-level check happens in the service; a record the caller may not
    # see is reported as 404 whether or not it exists.
    patient = await patient_service.get_patient(db, principal, patient_id)
    return to_staff(patient) if principal.has_any(*STAFF_READ) else to_self(patient)


@router.patch("/{patient_id}", response_model=PatientStaffRead)
async def update_patient(
    patient_id: uuid.UUID,
    body: PatientUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update)),
):
    return to_staff(await patient_service.update_patient(db, principal, patient_id, body))


@router.post("/{patient_id}/deactivate", response_model=PatientStaffRead)
async def deactivate_patient(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_deactivate)),
):
    return to_staff(await patient_service.set_active(db, principal, patient_id, active=False))


@router.post("/{patient_id}/activate", response_model=PatientStaffRead)
async def activate_patient(
    patient_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_deactivate)),
):
    return to_staff(await patient_service.set_active(db, principal, patient_id, active=True))


@router.post("/{patient_id}/link-account", response_model=PatientStaffRead)
async def link_account(
    patient_id: uuid.UUID,
    body: LinkAccount,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_update)),
):
    return to_staff(await patient_service.link_account(db, principal, patient_id, body.user_id))


@router.post("/{patient_id}/account", response_model=PatientStaffRead, status_code=status.HTTP_201_CREATED)
async def create_account(
    patient_id: uuid.UUID,
    body: PatientAccountCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.patient_create)),
):
    return to_staff(
        await patient_service.create_account(db, principal, patient_id, email=body.email, password=body.password)
    )
