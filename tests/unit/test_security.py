"""Unit tests for :mod:`aegis.core.security`.

Pure crypto/JWT round-trips — no DB, no network. Argon2 hashing and HS256 JWT
issuance/verification are deterministic enough to assert behaviour directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest

from aegis.core.config import settings
from aegis.core.exceptions import UnauthorizedError
from aegis.core.security import (
    TokenData,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Password hashing
# --------------------------------------------------------------------------- #
def test_hash_password_round_trip() -> None:
    raw = "correct horse battery staple"
    hashed = hash_password(raw)

    # The hash must not leak the plaintext and must verify against it.
    assert hashed != raw
    assert hashed.startswith("$argon2")
    assert verify_password(raw, hashed) is True


def test_hash_password_is_salted() -> None:
    # Two hashes of the same password differ (random salt) yet both verify.
    raw = "s3cr3t-passw0rd"
    first = hash_password(raw)
    second = hash_password(raw)

    assert first != second
    assert verify_password(raw, first)
    assert verify_password(raw, second)


def test_verify_wrong_password_fails() -> None:
    hashed = hash_password("the-right-one")
    assert verify_password("the-wrong-one", hashed) is False


# --------------------------------------------------------------------------- #
# Token issuance & decoding
# --------------------------------------------------------------------------- #
def test_create_and_decode_access_token() -> None:
    token = create_access_token(subject="user-123", role="engineer")
    data = decode_token(token, expected_type="access")

    assert isinstance(data, TokenData)
    assert data.subject == "user-123"
    assert data.role == "engineer"
    assert data.token_type == "access"
    assert data.jti  # a non-empty unique id was issued
    assert data.expires_at > datetime.now(UTC)


def test_create_and_decode_refresh_token() -> None:
    token = create_refresh_token(subject="user-456", role="admin")
    data = decode_token(token, expected_type="refresh")

    assert data.subject == "user-456"
    assert data.role == "admin"
    assert data.token_type == "refresh"


def test_decode_without_expected_type_accepts_either() -> None:
    access = create_access_token(subject="u", role="viewer")
    refresh = create_refresh_token(subject="u", role="viewer")

    assert decode_token(access).token_type == "access"
    assert decode_token(refresh).token_type == "refresh"


def test_access_and_refresh_have_distinct_jti() -> None:
    access = decode_token(create_access_token(subject="u", role="viewer"))
    refresh = decode_token(create_refresh_token(subject="u", role="viewer"))
    assert access.jti != refresh.jti


# --------------------------------------------------------------------------- #
# Failure modes
# --------------------------------------------------------------------------- #
def test_decode_token_wrong_expected_type_raises() -> None:
    # A refresh token must never be accepted where an access token is expected.
    refresh = create_refresh_token(subject="user-1", role="engineer")
    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token(refresh, expected_type="access")
    assert exc_info.value.code == "token_wrong_type"


def test_decode_garbage_token_raises() -> None:
    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token("not-a-real-jwt")
    assert exc_info.value.code == "token_invalid"


def test_decode_tampered_token_raises() -> None:
    # Flip a character in the signature segment to break the HMAC.
    token = create_access_token(subject="user-1", role="engineer")
    header, payload, signature = token.split(".")
    flipped = "B" if signature[0] != "B" else "C"
    tampered = ".".join([header, payload, flipped + signature[1:]])

    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token(tampered)
    assert exc_info.value.code == "token_invalid"


def test_decode_token_signed_with_wrong_secret_raises() -> None:
    # A structurally valid JWT signed with the wrong key must be rejected.
    forged = jwt.encode(
        {"sub": "evil", "role": "admin", "type": "access", "exp": 9_999_999_999},
        "a-different-secret-key",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token(forged)
    assert exc_info.value.code == "token_invalid"


def test_decode_expired_token_raises() -> None:
    # Mint a token that expired in the past and confirm the expiry branch maps.
    expired = jwt.encode(
        {
            "sub": "user-1",
            "role": "viewer",
            "type": "access",
            "iat": 1_000_000_000,
            "exp": 1_000_000_001,
            "jti": "abc",
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token(expired)
    assert exc_info.value.code == "token_expired"
