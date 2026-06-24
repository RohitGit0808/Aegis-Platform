"""Authorization regression tests for the platform's access-control guarantees.

These lock in two deliberate security controls:

* **No privilege escalation via self-registration** — an anonymous client cannot
  mint an ADMIN account through the public ``/auth/register`` endpoint.
* **Object-level authorization (no BOLA/IDOR)** — an authenticated engineer may
  only mutate or run suites they own; another engineer is refused.
"""

from __future__ import annotations

import httpx

from tests import factories

API = "/api/v1"


async def _register_and_login(client: httpx.AsyncClient, payload: dict) -> dict[str, str]:
    reg = await client.post(f"{API}/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        f"{API}/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_self_registration_cannot_request_admin(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        f"{API}/auth/register",
        json=factories.user_create(email="attacker@example.com", role="admin"),
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"]["code"] == "role_forbidden"


async def test_engineer_cannot_mutate_another_users_suite(
    client: httpx.AsyncClient,
) -> None:
    owner_headers = await _register_and_login(
        client, factories.user_create(email="owner@example.com")
    )
    created = await client.post(
        f"{API}/suites", json=factories.suite_create(slug="owned-suite"), headers=owner_headers
    )
    assert created.status_code == 201, created.text
    suite_id = created.json()["id"]

    intruder_headers = await _register_and_login(
        client, factories.user_create(email="intruder@example.com")
    )
    deleted = await client.delete(f"{API}/suites/{suite_id}", headers=intruder_headers)
    assert deleted.status_code == 403
    assert deleted.json()["error"]["code"] == "not_owner"

    patched = await client.patch(
        f"{API}/suites/{suite_id}", json={"name": "hijacked"}, headers=intruder_headers
    )
    assert patched.status_code == 403

    # The owner can still mutate their own suite.
    ok = await client.patch(
        f"{API}/suites/{suite_id}", json={"name": "renamed"}, headers=owner_headers
    )
    assert ok.status_code == 200, ok.text


async def test_non_owner_cannot_trigger_run(client: httpx.AsyncClient) -> None:
    owner_headers = await _register_and_login(
        client, factories.user_create(email="runowner@example.com")
    )
    created = await client.post(
        f"{API}/suites", json=factories.suite_create(slug="run-suite"), headers=owner_headers
    )
    suite_id = created.json()["id"]

    intruder_headers = await _register_and_login(
        client, factories.user_create(email="runintruder@example.com")
    )
    run = await client.post(
        f"{API}/suites/{suite_id}/runs",
        json=factories.run_create(),
        headers=intruder_headers,
    )
    assert run.status_code == 403, run.text
    assert run.json()["error"]["code"] == "not_owner"
