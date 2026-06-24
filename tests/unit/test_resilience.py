"""Unit tests for :mod:`aegis.core.resilience`.

Covers the timeout wrapper and the async circuit breaker lifecycle. Uses tiny
``asyncio.sleep`` durations so the suite stays fast and deterministic.
pytest-asyncio runs in auto mode (see pyproject), so ``async def`` tests need
no explicit marker.
"""

from __future__ import annotations

import asyncio

import pytest

from aegis.core.exceptions import ServiceUnavailableError
from aegis.core.resilience import BreakerState, CircuitBreaker, with_timeout

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# with_timeout
# --------------------------------------------------------------------------- #
async def test_with_timeout_returns_value_for_fast_coro() -> None:
    async def fast() -> int:
        await asyncio.sleep(0)
        return 42

    assert await with_timeout(fast(), seconds=1.0) == 42


async def test_with_timeout_raises_on_slow_coro() -> None:
    async def slow() -> int:
        await asyncio.sleep(0.5)
        return 1

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await with_timeout(slow(), seconds=0.01)
    assert exc_info.value.code == "timeout"


# --------------------------------------------------------------------------- #
# CircuitBreaker
# --------------------------------------------------------------------------- #
async def _boom() -> None:
    raise ConnectionError("downstream exploded")


async def _ok() -> str:
    return "ok"


async def test_breaker_opens_after_threshold_failures() -> None:
    breaker = CircuitBreaker(name="t", failure_threshold=3, reset_timeout=999)

    # The first `threshold` failures propagate the *original* exception while the
    # breaker is still CLOSED, tripping it on the last one.
    for _ in range(3):
        with pytest.raises(ConnectionError):
            await breaker.call(_boom)

    assert breaker.state is BreakerState.OPEN

    # Once OPEN, calls short-circuit with a circuit_open ServiceUnavailableError
    # without ever invoking the wrapped function.
    with pytest.raises(ServiceUnavailableError) as exc_info:
        await breaker.call(_ok)
    assert exc_info.value.code == "circuit_open"


async def test_breaker_resets_failure_count_on_success() -> None:
    breaker = CircuitBreaker(name="t", failure_threshold=3, reset_timeout=999)

    # Two failures (below threshold)...
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await breaker.call(_boom)

    # ...a success clears the consecutive-failure counter and keeps it CLOSED.
    assert await breaker.call(_ok) == "ok"
    assert breaker.state is BreakerState.CLOSED

    # Two more failures should therefore NOT be enough to open it (counter reset).
    for _ in range(2):
        with pytest.raises(ConnectionError):
            await breaker.call(_boom)
    assert breaker.state is BreakerState.CLOSED


async def test_breaker_starts_closed() -> None:
    breaker = CircuitBreaker(name="t")
    assert breaker.state is BreakerState.CLOSED
    assert await breaker.call(_ok) == "ok"
