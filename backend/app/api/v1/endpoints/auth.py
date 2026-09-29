from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import AccessTokenResponse, RefreshRequest, Token, UserCreate, UserLogin, UserResponse
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    return await auth_service.register_patient(db, user_in)


@router.post("/login", response_model=Token)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    tokens = await auth_service.login(db, credentials.email, credentials.password)
    return Token(access_token=tokens.access_token, refresh_token=tokens.refresh_token)


@router.post("/refresh", response_model=AccessTokenResponse)
async def refresh_access_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    access_token = await auth_service.refresh_access_token(db, body.refresh_token)
    return AccessTokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    await auth_service.logout(db, body.refresh_token)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
