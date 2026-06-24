"""Authentication primitives: password hashing and JWT issuance/verification.

Passwords are hashed with Argon2id (memory-hard, the OWASP-recommended default).
Tokens are signed JWTs carrying a subject (user id), role, token type and the
standard ``exp``/``iat``/``jti`` claims. Access and refresh tokens are
distinguished by their ``type`` claim so a refresh token can never be replayed
as an access token.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from aegis.core.config import settings
from aegis.core.exceptions import UnauthorizedError

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

TokenType = Literal["access", "refresh"]


@dataclass(slots=True, frozen=True)
class TokenData:
    """Decoded, verified token claims."""

    subject: str
    role: str
    token_type: TokenType
    jti: str
    expires_at: datetime


def hash_password(raw_password: str) -> str:
    return _pwd_context.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(raw_password, hashed_password)


def _create_token(*, subject: str, role: str, token_type: TokenType, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(*, subject: str, role: str) -> str:
    return _create_token(
        subject=subject,
        role=role,
        token_type="access",
        ttl_seconds=settings.access_token_ttl_seconds,
    )


def create_refresh_token(*, subject: str, role: str) -> str:
    return _create_token(
        subject=subject,
        role=role,
        token_type="refresh",
        ttl_seconds=settings.refresh_token_ttl_seconds,
    )


def decode_token(token: str, *, expected_type: TokenType | None = None) -> TokenData:
    """Verify signature/expiry and return claims, or raise ``UnauthorizedError``."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("Token has expired.", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Token is invalid.", code="token_invalid") from exc

    token_type = payload.get("type")
    if expected_type is not None and token_type != expected_type:
        raise UnauthorizedError(f"Expected a {expected_type} token.", code="token_wrong_type")

    return TokenData(
        subject=str(payload["sub"]),
        role=str(payload.get("role", "viewer")),
        token_type=token_type,  # type: ignore[arg-type]
        jti=str(payload.get("jti", "")),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
    )
