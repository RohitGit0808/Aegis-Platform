"""Authentication endpoints: register, login (OAuth2 password flow), refresh, me."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from aegis.api.deps import CurrentUser, SessionDep
from aegis.core.exceptions import ForbiddenError
from aegis.domain.enums import UserRole
from aegis.domain.schemas import Token, TokenRefreshRequest, UserCreate, UserRead
from aegis.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(data: UserCreate, session: SessionDep) -> UserRead:
    # Prevent privilege escalation: self-registration may not grant the admin role.
    if data.role is UserRole.ADMIN:
        raise ForbiddenError(
            "Self-registration cannot request the admin role.", code="role_forbidden"
        )
    service = AuthService(session)
    user = await service.register(data)
    await session.commit()
    return UserRead.model_validate(user)


@router.post("/login", response_model=Token)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: SessionDep
) -> Token:
    service = AuthService(session)
    user = await service.authenticate(form.username, form.password)
    return service.issue_tokens(user)


@router.post("/refresh", response_model=Token)
async def refresh(body: TokenRefreshRequest, session: SessionDep) -> Token:
    return await AuthService(session).refresh(body.refresh_token)


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)
