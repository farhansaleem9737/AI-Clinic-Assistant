import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.api.deps.pagination import page_params
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.schemas.common import Page
from app.core.storage import Storage, get_optional_storage
from app.schemas.department import (
    DepartmentCreate,
    DepartmentDetail,
    DepartmentListItem,
    DepartmentPublic,
    DepartmentPublicCard,
    DepartmentResponse,
    DepartmentSummaryRead,
    DepartmentUpdate,
)
from app.services import department_service, file_service
from app.services.department_service import DepartmentSort, DepartmentWithDoctors
from app.services.pagination import PageParams

router = APIRouter(prefix="/departments", tags=["departments"])
public_router = APIRouter(prefix="/public/departments", tags=["public"])


@public_router.get("/", response_model=Page[DepartmentPublicCard])
async def public_list_departments(
    q: str | None = Query(None, max_length=100, description="Name or description"),
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    storage: Storage | None = Depends(get_optional_storage),
):
    """Active departments only, by name, each with the number of doctors the
    public directory lists and up to three of them (D94). Same query as the
    admin list, restricted to active departments: a doctor counts when their
    profile and login are active, and the department is active by definition."""
    rows, total = await department_service.manage_list(db, params, q=q, is_active=True)
    items = [
        DepartmentPublicCard(
            id=r.department.id,
            name=r.department.name,
            description=r.department.description,
            icon=r.department.icon,
            color=r.department.color,
            doctor_count=r.doctor_count,
            doctors_preview=[_doctor(d, storage) for d in r.preview],
        )
        for r in rows
    ]
    return Page(items=items, total=total, page=params.page, page_size=params.page_size)


@public_router.get("/{department_id}", response_model=DepartmentPublic)
async def public_get_department(department_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    return await department_service.get_department(db, department_id, active_only=True)


def _doctor(row, storage: Storage | None) -> dict:
    return {"id": row.id, "name": row.name, "title": row.title, "photo_url": file_service.photo_url_for_key(storage, row.photo_key)}


def _item(row: DepartmentWithDoctors, storage: Storage | None) -> DepartmentListItem:
    return DepartmentListItem(
        **DepartmentResponse.model_validate(row.department).model_dump(),
        doctor_count=row.doctor_count,
        doctors_preview=[_doctor(d, storage) for d in row.preview],
    )


@router.get("/", response_model=Page[DepartmentListItem])
async def list_departments(
    q: str | None = Query(None, max_length=100, description="Name or description"),
    is_active: bool | None = None,
    include_inactive: bool = Query(True, description="Kept for older clients; is_active takes precedence"),
    sort: DepartmentSort = DepartmentSort.name,
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
    storage: Storage | None = Depends(get_optional_storage),
):
    if is_active is None and not include_inactive:
        is_active = True
    rows, total = await department_service.manage_list(db, params, q=q, is_active=is_active, sort=sort)
    return Page(items=[_item(r, storage) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.get("/summary", response_model=DepartmentSummaryRead)
async def department_summary(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    """Total / active / inactive departments and practising doctors, clinic-wide."""
    s = await department_service.summary(db)
    return DepartmentSummaryRead(total=s.total, active=s.active, inactive=s.inactive, doctors=s.doctors)


@router.post("/", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    return await department_service.create_department(db, body)


@router.get("/{department_id}", response_model=DepartmentDetail)
async def get_department(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
    storage: Storage | None = Depends(get_optional_storage),
):
    """With every doctor profile in the department and the count of upcoming
    appointments (shown before deactivating)."""
    row = await department_service.get_detail(db, department_id)
    return DepartmentDetail(
        **_item(row, storage).model_dump(),
        doctors=[
            {**_doctor(d, storage), "specialization": d.specialization, "is_active": d.is_active} for d in row.doctors
        ],
        upcoming_appointments=row.upcoming_appointments,
    )


@router.patch("/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: uuid.UUID,
    body: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    return await department_service.update_department(db, department_id, body)


@router.post("/{department_id}/deactivate", response_model=DepartmentResponse)
async def deactivate_department(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    return await department_service.set_active(db, department_id, active=False)


@router.post("/{department_id}/activate", response_model=DepartmentResponse)
async def activate_department(
    department_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.department_manage)),
):
    return await department_service.set_active(db, department_id, active=True)
