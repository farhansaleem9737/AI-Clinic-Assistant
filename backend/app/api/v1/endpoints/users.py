import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.api.deps.pagination import page_params
from app.core.permissions import Perm, Principal
from app.core.storage import Storage, get_optional_storage
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.user import (
    AccountCreate,
    AdminUserRead,
    BulkStatusResult,
    BulkStatusUpdate,
    RoleResponse,
    RolesUpdate,
    UserUpdate,
)
from app.services import file_service, user_service
from app.services.pagination import PageParams
from app.services.user_service import UserSort, UserWithRoles

router = APIRouter(prefix="/users", tags=["users"])
roles_router = APIRouter(prefix="/roles", tags=["users"])


def _user_response(row: UserWithRoles, storage: Storage | None = None) -> AdminUserRead:
    user = row.user
    return AdminUserRead(
        id=user.id,
        name=user.name,
        email=user.email,
        is_active=user.is_active,
        roles=row.roles,
        created_at=user.created_at,
        phone=row.phone,
        photo_url=file_service.photo_url_for_key(storage, row.photo_key),
        doctor_id=row.doctor_id,
        patient_id=row.patient_id,
    )


@router.get("/", response_model=Page[AdminUserRead])
async def list_users(
    q: str | None = Query(None, max_length=100, description="Name, email or phone"),
    role: str | None = Query(None, max_length=50),
    is_active: bool | None = None,
    joined_from: date | None = Query(None, description="Joined on or after (clinic-local date)"),
    joined_to: date | None = Query(None, description="Joined on or before (clinic-local date)"),
    sort: UserSort = UserSort.name,
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.user_read)),
    storage: Storage | None = Depends(get_optional_storage),
):
    rows, total = await user_service.list_users(
        db, params, q=q, role=role, is_active=is_active, joined_from=joined_from, joined_to=joined_to, sort=sort
    )
    return Page(items=[_user_response(r, storage) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("/", response_model=AdminUserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AccountCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_create)),
):
    return _user_response(await user_service.create_account(db, principal, **body.model_dump()))


@router.post("/bulk-status", response_model=list[BulkStatusResult])
async def bulk_status(
    body: BulkStatusUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_deactivate)),
):
    """Activate or deactivate up to 100 users. Each one succeeds or fails on
    its own (e.g. LAST_ADMIN, SELF_DEACTIVATION); the result lists both."""
    outcomes = await user_service.set_active_bulk(db, principal, body.user_ids, body.is_active)
    return [BulkStatusResult(user_id=o.user_id, ok=o.ok, code=o.code, message=o.message) for o in outcomes]


@router.get("/{user_id}", response_model=AdminUserRead)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.user_read)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return _user_response(await user_service.get_user(db, user_id), storage)


@router.patch("/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_update)),
    storage: Storage | None = Depends(get_optional_storage),
):
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    return _user_response(await user_service.update_user(db, principal, user_id, changes), storage)


@router.post("/{user_id}/deactivate", response_model=AdminUserRead)
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_deactivate)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return _user_response(await user_service.set_active(db, principal, user_id, active=False), storage)


@router.post("/{user_id}/activate", response_model=AdminUserRead)
async def activate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_deactivate)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return _user_response(await user_service.set_active(db, principal, user_id, active=True), storage)


@router.put("/{user_id}/roles", response_model=AdminUserRead)
async def set_roles(
    user_id: uuid.UUID,
    body: RolesUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_assign_role)),
    storage: Storage | None = Depends(get_optional_storage),
):
    return _user_response(await user_service.set_roles(db, principal, user_id, body.roles), storage)


@roles_router.get("/", response_model=list[RoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.role_read)),
):
    return [
        RoleResponse(code=r.role.code, name=r.role.name, description=r.role.description, permissions=r.permissions)
        for r in await user_service.list_roles(db)
    ]
