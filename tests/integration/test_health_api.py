"""Infra + meta endpoint smoke tests against the real app."""

from __future__ import annotations

import httpx
import pytest

from aegis import __version__

pytestmark = pytest.mark.integration

API = "/api/v1"


async def test_healthz_reports_alive(client: httpx.AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


async def test_readyz_reports_ready_with_checks(client: httpx.AsyncClient) -> None:
    resp = await client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ready"] is True
    # Both the SQLite DB and the FakeRedis cache should be reachable.
    assert body["checks"] == {"database": True, "cache": True}


async def test_api_health_returns_version(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"{API}/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["environment"] == "test"


async def test_metrics_returns_prometheus_text(client: httpx.AsyncClient) -> None:
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    # Prometheus exposition format is text/plain with a version param.
    assert resp.headers["content-type"].startswith("text/plain")
    # A couple of well-known metric families defined in aegis.core.metrics.
    assert "aegis_" in resp.text
