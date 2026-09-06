"""Authentication: register, login, current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.mappers import user_to_response
from app.api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.core.errors import AuthError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.domain import User
from app.repositories.users import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest) -> TokenResponse:
    user = await UserRepository().create(
        email=body.email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
    )
    return TokenResponse(access_token=create_access_token(user.id), user=user_to_response(user))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    repo = UserRepository()
    user = await repo.get_by_email(body.email)
    # Identical message for unknown email and wrong password: do not disclose
    # which accounts exist.
    if user is None or not user.password_hash or not verify_password(body.password, user.password_hash):
        raise AuthError("Incorrect email or password.")
    await repo.touch_active(user.id)
    return TokenResponse(access_token=create_access_token(user.id), user=user_to_response(user))


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)) -> UserResponse:
    return user_to_response(user)
