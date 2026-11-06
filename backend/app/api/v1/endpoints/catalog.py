"""Specializations in the medical catalog (D118).

Public: the active specializations (of a department) with how many listed
doctors practise each, for the directory filters.
Staff: manage specializations and their departments (department:manage), and
set a doctor's specializations (doctor:update). Doctors cannot set their own.
"""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.schemas.catalog import (
    DoctorSpecializationsUpdate,
    SpecializationAdmin,
    SpecializationCreate,
    SpecializationPublic,
    SpecializationRef,
    SpecializationUpdate,
)
from app.services import catalog_service
from app.services.catalog_service import SpecializationRow

public_router = APIRouter(prefix="/public/specializations", tags=["public"])
router = APIRouter(prefix="/specializations", tags=["catalog"])
doctor_router = APIRouter(prefix="/doctors", tags=["doctors"])


def _public(row: SpecializationRow) -> SpecializationPublic:
    s = row.specialization
    return SpecializationPublic(id=s.id, name=s.name, slug=s.slug, department_ids=row.department_ids, doctor_count=row.doctor_count)


def _admin(row: SpecializationRow) -> SpecializationAdmin:
    s = row.specialization
    return SpecializationAdmin(
        **_public(row).model_dump(), description=s.description, aliases=s.aliases, is_active=s.is_active
    )


@public_router.get("/", response_model=list[SpecializationPublic])
async def public_list_specializations(
    department_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    """Active specializations by name. With `department_id`, only that
    department's, and the doctor counts are of doctors in that department."""
    return [_public(r) for r in await catalog_service.list_specializations(db, department_id=department_id, q=q)]


@router.get("/", response_model=list[SpecializationAdmin])
async def list_specializations(
    department_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=100),
    is_active: bool | None = None,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    """Every specialization (retired ones too unless `is_active` says otherwise),
    with each one's departments and the number of doctor profiles linked to it."""
    rows = await catalog_service.list_specializations(db, department_id=department_id, q=q, active_only=False, public_counts=False)
    if is_active is not None:
        rows = [r for r in rows if r.specialization.is_active is is_active]
    return [_admin(r) for r in rows]


@router.post("/", response_model=SpecializationAdmin, status_code=status.HTTP_201_CREATED)
async def create_specialization(
    body: SpecializationCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.department_manage)),
):
    return _admin(await catalog_service.create_specialization(db, principal, body))


@router.patch("/{specialization_id}", response_model=SpecializationAdmin)
async def update_specialization(
    specialization_id: uuid.UUID,
    body: SpecializationUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.department_manage)),
):
    return _admin(await catalog_service.update_specialization(db, principal, specialization_id, body))


@doctor_router.get("/{doctor_id}/specializations", response_model=list[SpecializationRef])
async def get_doctor_specializations(
    doctor_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.doctor_read)),
):
    return (await catalog_service.doctor_specializations(db, [doctor_id]))[doctor_id]


@doctor_router.put("/{doctor_id}/specializations", response_model=list[SpecializationRef])
async def set_doctor_specializations(
    doctor_id: uuid.UUID,
    body: DoctorSpecializationsUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.doctor_update)),
):
    """Replace the doctor's catalog specializations; each must belong to the
    doctor's department. Audited."""
    return await catalog_service.set_doctor_specializations(db, principal, doctor_id, body.specialization_ids)
