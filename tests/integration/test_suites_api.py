"""Suite & case CRUD: creation, pagination envelope, RBAC, update, add-case."""

from __future__ import annotations

import httpx
import pytest

from tests import factories

pytestmark = pytest.mark.integration

API = "/api/v1"


async def _create_suite(client: httpx.AsyncClient, headers: dict[str, str], **kwargs) -> dict:
    payload = factories.suite_create(**kwargs)
    resp = await client.post(f"{API}/suites", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_suite_returns_201_with_cases(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    payload = factories.suite_create(slug="checkout-suite", name="Checkout Suite")
    resp = await client.post(f"{API}/suites", json=payload, headers=auth_headers)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "checkout-suite"
    assert body["name"] == "Checkout Suite"
    assert body["is_active"] is True
    assert "owner_id" in body
    # SuiteDetail echoes the embedded cases with their steps.
    assert len(body["cases"]) == 2
    case_names = {c["name"] for c in body["cases"]}
    assert any("stable" in n for n in case_names)
    assert any("brittle" in n for n in case_names)


async def test_list_suites_returns_page_envelope(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create_suite(client, auth_headers, slug="suite-a", name="Suite A")
    await _create_suite(client, auth_headers, slug="suite-b", name="Suite B")

    resp = await client.get(f"{API}/suites?page=1&size=1", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Page[T] shape.
    assert set(body) == {"items", "total", "page", "size", "pages"}
    assert body["total"] == 2
    assert body["page"] == 1
    assert body["size"] == 1
    assert body["pages"] == 2
    assert len(body["items"]) == 1


async def test_get_suite_by_id(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await _create_suite(client, auth_headers, slug="fetch-me")

    resp = await client.get(f"{API}/suites/{created['id']}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == created["id"]
    assert body["slug"] == "fetch-me"
    assert len(body["cases"]) == 2


async def test_get_unknown_suite_returns_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    resp = await client.get(f"{API}/suites/{missing}", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


async def test_duplicate_slug_returns_409(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    await _create_suite(client, auth_headers, slug="taken-slug")

    payload = factories.suite_create(slug="taken-slug", name="Another")
    resp = await client.post(f"{API}/suites", json=payload, headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "slug_taken"


async def test_viewer_cannot_create_suite(
    client: httpx.AsyncClient, viewer_headers: dict[str, str]
) -> None:
    payload = factories.suite_create(slug="viewer-attempt")
    resp = await client.post(f"{API}/suites", json=payload, headers=viewer_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "insufficient_role"


async def test_viewer_can_list_suites(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    viewer_headers: dict[str, str],
) -> None:
    """RBAC denies writes for viewers but reads remain available."""
    await _create_suite(client, auth_headers, slug="readable")
    resp = await client.get(f"{API}/suites", headers=viewer_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_update_suite_via_patch(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await _create_suite(client, auth_headers, slug="patch-me", name="Old")

    resp = await client.patch(
        f"{API}/suites/{created['id']}",
        json={"name": "New Name", "tags": ["regression"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "New Name"
    assert body["tags"] == ["regression"]
    # Untouched fields are preserved.
    assert body["slug"] == "patch-me"


async def test_add_case_to_suite(client: httpx.AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await _create_suite(client, auth_headers, slug="grow-me")

    payload = factories.test_case_create(name="Extra case", order_index=9)
    resp = await client.post(
        f"{API}/suites/{created['id']}/cases", json=payload, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Extra case"
    assert body["order_index"] == 9
    assert body["suite_id"] == created["id"]

    # And it shows up when re-fetching the suite (now three cases).
    detail = await client.get(f"{API}/suites/{created['id']}", headers=auth_headers)
    assert len(detail.json()["cases"]) == 3


async def test_create_suite_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.post(f"{API}/suites", json=factories.suite_create())
    assert resp.status_code == 401
