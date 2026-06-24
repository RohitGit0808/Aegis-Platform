"""Shared FastAPI dependencies: DB session, auth, RBAC, pagination, rate limiting.

Write endpoints own their unit of work — the ``get_session`` dependency rolls
back on error but does not auto-commit, so endpoints commit explicitly once the
service work succeeds.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Header, Query, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from aegis.cache.redis import get_cache
from aegis.core.config import settings
from aegis.core.exceptions import ForbiddenError, RateLimitedError, UnauthorizedError
from aegis.core.pagination import PaginationParams
from aegis.core.security import decode_token
from aegis.db.models import User
from aegis.db.session import get_session
from aegis.domain.enums import UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep, token: Annotated[str, Depends(oauth2_scheme)]
) -> User:
    data = decode_token(token, expected_type="access")
    user = await session.get(User, uuid.UUID(data.subject))
    if user is None or not user.is_active:
        raise UnauthorizedError("User no longer exists or is inactive.", code="invalid_token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[..., Coroutine[Any, Any, User]]:
    """Dependency factory enforcing RBAC. Admins always pass."""

    async def _checker(user: CurrentUser) -> User:
        if user.role is not UserRole.ADMIN and user.role not in roles:
            raise ForbiddenError("Your role does not permit this action.", code="insufficient_role")
        return user

    return _checker


def get_pagination(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=PaginationParams.MAX_SIZE)] = 20,
) -> PaginationParams:
    return PaginationParams(page=page, size=size)


Pagination = Annotated[PaginationParams, Depends(get_pagination)]

IdempotencyKey = Annotated[str | None, Header(alias="Idempotency-Key")]


async def rate_limiter(request: Request) -> None:
    if not settings.rate_limit_enabled:
        return
    client = request.client.host if request.client else "anonymous"
    key = f"rl:{client}:{request.url.path}"
    allowed = await get_cache().allow_request(
        key,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
    )
    if not allowed:
        raise RateLimitedError()
