"""Authentication & user lifecycle."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from aegis.core.config import settings
from aegis.core.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from aegis.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from aegis.db.models import User
from aegis.domain.schemas import Token, UserCreate
from aegis.repositories.users import UserRepository


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def register(self, data: UserCreate) -> User:
        if await self.users.get_by_email(data.email):
            raise ConflictError("Email is already registered.", code="email_taken")
        user = User(
            email=data.email.lower(),
            full_name=data.full_name,
            hashed_password=hash_password(data.password),
            role=data.role,
        )
        return await self.users.add(user)

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)
        if user is None or not verify_password(password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password.", code="invalid_credentials")
        if not user.is_active:
            raise ForbiddenError("This account has been disabled.")
        return user

    def issue_tokens(self, user: User) -> Token:
        return Token(
            access_token=create_access_token(subject=str(user.id), role=user.role.value),
            refresh_token=create_refresh_token(subject=str(user.id), role=user.role.value),
            expires_in=settings.access_token_ttl_seconds,
        )

    async def refresh(self, refresh_token: str) -> Token:
        data = decode_token(refresh_token, expected_type="refresh")
        user = await self.users.get(uuid.UUID(data.subject))
        if user is None or not user.is_active:
            raise UnauthorizedError("Account is no longer valid.", code="invalid_token")
        return self.issue_tokens(user)
