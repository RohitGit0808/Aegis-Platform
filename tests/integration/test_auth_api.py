"""Auth flow: register, login (OAuth2 password), me, refresh, error envelopes."""

from __future__ import annotations

import httpx
import pytest

from tests import factories

pytestmark = pytest.mark.integration

API = "/api/v1"


async def test_register_returns_201_and_user(client: httpx.AsyncClient) -> None:
    payload = factories.user_create(email="ada@example.com", full_name="Ada Lovelace")
    resp = await client.post(f"{API}/auth/register", json=payload)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["role"] == "engineer"
    assert body["is_active"] is True
    assert "id" in body
    # The password (or its hash) must never be serialised back to the client.
    assert "password" not in body
    assert "hashed_password" not in body


async def test_duplicate_email_returns_409_email_taken(client: httpx.AsyncClient) -> None:
    payload = factories.user_create(email="dupe@example.com")
    first = await client.post(f"{API}/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post(f"{API}/auth/register", json=payload)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "email_taken"


async def test_login_returns_access_and_refresh_tokens(client: httpx.AsyncClient) -> None:
    payload = factories.user_create(email="login@example.com")
    await client.post(f"{API}/auth/register", json=payload)

    resp = await client.post(
        f"{API}/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0


async def test_login_bad_credentials_returns_401(client: httpx.AsyncClient) -> None:
    payload = factories.user_create(email="wrongpw@example.com")
    await client.post(f"{API}/auth/register", json=payload)

    resp = await client.post(
        f"{API}/auth/login",
        data={"username": payload["email"], "password": "not-the-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "invalid_credentials"


async def test_me_with_bearer_returns_current_user(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    resp = await client.get(f"{API}/auth/me", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["role"] == "engineer"
    assert body["is_active"] is True


async def test_me_with_bad_token_returns_401(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401


async def test_me_without_token_returns_401(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"{API}/auth/me")
    assert resp.status_code == 401


async def test_refresh_returns_new_token(client: httpx.AsyncClient) -> None:
    payload = factories.user_create(email="refresh@example.com")
    await client.post(f"{API}/auth/register", json=payload)
    login = await client.post(
        f"{API}/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    refresh_token = login.json()["refresh_token"]

    resp = await client.post(f"{API}/auth/refresh", json={"refresh_token": refresh_token})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]
    # The new access token must actually authenticate.
    me = await client.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200


async def test_refresh_rejects_access_token(client: httpx.AsyncClient) -> None:
    """An access token must not be usable on the refresh endpoint."""
    payload = factories.user_create(email="mixup@example.com")
    await client.post(f"{API}/auth/register", json=payload)
    login = await client.post(
        f"{API}/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    access_token = login.json()["access_token"]

    resp = await client.post(f"{API}/auth/refresh", json={"refresh_token": access_token})
    assert resp.status_code == 401
