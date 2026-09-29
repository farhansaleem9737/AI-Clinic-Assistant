import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps.auth import require_permission
from app.api.deps.pagination import page_params
from app.core.permissions import Perm, Principal
from app.db.session import get_db
from app.schemas.common import Page
from app.schemas.user import AccountCreate, RoleResponse, RolesUpdate, UserResponse, UserUpdate
from app.services import user_service
from app.services.pagination import PageParams
from app.services.user_service import UserWithRoles

router = APIRouter(prefix="/users", tags=["users"])
roles_router = APIRouter(prefix="/roles", tags=["users"])


def _user_response(row: UserWithRoles) -> UserResponse:
    user = row.user
    return UserResponse(
        id=user.id,
        name=user.name,
        email=user.email,
        is_active=user.is_active,
        roles=row.roles,
        created_at=user.created_at,
    )


@router.get("/", response_model=Page[UserResponse])
async def list_users(
    q: str | None = Query(None, max_length=100, description="Search name or email"),
    role: str | None = Query(None, max_length=50),
    is_active: bool | None = None,
    params: PageParams = Depends(page_params),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.user_read)),
):
    rows, total = await user_service.list_users(db, params, q=q, role=role, is_active=is_active)
    return Page(items=[_user_response(r) for r in rows], total=total, page=params.page, page_size=params.page_size)


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AccountCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_create)),
):
    return _user_response(await user_service.create_account(db, principal, **body.model_dump()))


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.user_read)),
):
    return _user_response(await user_service.get_user(db, user_id))


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_update)),
):
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    return _user_response(await user_service.update_user(db, principal, user_id, changes))


@router.post("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_deactivate)),
):
    return _user_response(await user_service.set_active(db, principal, user_id, active=False))


@router.post("/{user_id}/activate", response_model=UserResponse)
async def activate_user(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_deactivate)),
):
    return _user_response(await user_service.set_active(db, principal, user_id, active=True))


@router.put("/{user_id}/roles", response_model=UserResponse)
async def set_roles(
    user_id: uuid.UUID,
    body: RolesUpdate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_permission(Perm.user_assign_role)),
):
    return _user_response(await user_service.set_roles(db, principal, user_id, body.roles))


@roles_router.get("/", response_model=list[RoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_permission(Perm.role_read)),
):
    return [
        RoleResponse(code=r.role.code, name=r.role.name, description=r.role.description, permissions=r.permissions)
        for r in await user_service.list_roles(db)
    ]
