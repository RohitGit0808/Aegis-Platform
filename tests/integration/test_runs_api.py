"""Run lifecycle: trigger (202) -> inline execution -> terminal status, healing,
and idempotency — all driven through the real HTTP API.

The InlineDispatcher runs the executor as an in-process ``asyncio`` background
task, so a freshly-triggered run is ``queued`` and reaches a terminal status a
moment later. We poll ``GET /runs/{id}`` with small sleeps until it settles.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from tests import factories

pytestmark = pytest.mark.integration

API = "/api/v1"

_TERMINAL = {"passed", "failed", "error", "cancelled"}


async def _create_suite(client: httpx.AsyncClient, headers: dict[str, str]) -> str:
    payload = factories.suite_create(slug="run-suite")
    resp = await client.post(f"{API}/suites", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _wait_for_terminal(
    client: httpx.AsyncClient,
    run_id: str,
    headers: dict[str, str],
    *,
    timeout: float = 5.0,
    interval: float = 0.05,
) -> dict:
    """Poll the run until it reaches a terminal status (bounded by ``timeout``)."""
    deadline = asyncio.get_event_loop().time() + timeout
    body: dict = {}
    while asyncio.get_event_loop().time() < deadline:
        resp = await client.get(f"{API}/runs/{run_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body["status"] in _TERMINAL:
            return body
        await asyncio.sleep(interval)
    raise AssertionError(
        f"Run {run_id} did not reach a terminal status within {timeout}s; "
        f"last status={body.get('status')!r}"
    )


async def test_trigger_run_returns_202_queued(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    suite_id = await _create_suite(client, auth_headers)

    resp = await client.post(
        f"{API}/suites/{suite_id}/runs",
        json=factories.run_create(),
        headers=auth_headers,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["suite_id"] == suite_id
    assert body["trigger"] == "manual"
    # total_cases is computed from the suite at creation time.
    assert body["total_cases"] == 2
    # It is enqueued; status starts at queued (it may already be running, but
    # the response is serialised from the row before the worker mutates it).
    assert body["status"] in {"queued", "running"}


async def test_run_executes_and_heals_brittle_locator(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    suite_id = await _create_suite(client, auth_headers)
    trigger = await client.post(
        f"{API}/suites/{suite_id}/runs",
        json=factories.run_create(),
        headers=auth_headers,
    )
    run_id = trigger.json()["id"]

    run = await _wait_for_terminal(client, run_id, auth_headers)

    # The stable case passes; the brittle #id locator is recovered by the healer.
    assert run["status"] in {"passed", "failed"}
    assert run["healed_count"] >= 1
    assert run["finished_at"] is not None
    assert run["duration_ms"] is not None

    # The full run detail carries per-step results.
    assert any(r["status"] == "healed" for r in run["results"])

    # Healing events are recorded and queryable for the run.
    events = await client.get(f"{API}/runs/{run_id}/healing", headers=auth_headers)
    assert events.status_code == 200, events.text
    payload = events.json()
    assert len(payload) >= 1
    healed = payload[0]
    assert healed["run_id"] == run_id
    assert healed["original_selector"] == "#place-order-button"
    assert healed["healed_selector"] is not None
    assert healed["succeeded"] is True
    assert healed["strategy"] in {"heuristic", "llm", "hybrid"}


async def test_idempotent_trigger_returns_same_run(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    suite_id = await _create_suite(client, auth_headers)
    headers = {**auth_headers, "Idempotency-Key": "fixed-key-123"}

    first = await client.post(
        f"{API}/suites/{suite_id}/runs", json=factories.run_create(), headers=headers
    )
    assert first.status_code == 202, first.text
    first_id = first.json()["id"]

    # Replaying the same key must return the identical run (no new run created).
    second = await client.post(
        f"{API}/suites/{suite_id}/runs", json=factories.run_create(), headers=headers
    )
    assert second.status_code == 202, second.text
    assert second.json()["id"] == first_id

    # Only one run exists for this suite.
    listing = await client.get(f"{API}/runs?suite_id={suite_id}", headers=auth_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


async def test_list_runs_returns_page_envelope(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    suite_id = await _create_suite(client, auth_headers)
    await client.post(
        f"{API}/suites/{suite_id}/runs",
        json=factories.run_create(),
        headers=auth_headers,
    )

    resp = await client.get(f"{API}/runs", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"items", "total", "page", "size", "pages"}
    assert body["total"] >= 1


async def test_trigger_run_on_unknown_suite_returns_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    resp = await client.post(
        f"{API}/suites/{missing}/runs",
        json=factories.run_create(),
        headers=auth_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
