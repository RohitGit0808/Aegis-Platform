"""Resilience primitives: retry-with-backoff, timeouts and a circuit breaker.

External calls (the LLM healing provider, downstream targets) are fronted by
these so a slow or flapping dependency degrades gracefully instead of stalling
the worker pool. The circuit breaker is a minimal, dependency-free async
implementation with the standard CLOSED → OPEN → HALF_OPEN lifecycle.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum, auto
from typing import TypeVar

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from aegis.core.exceptions import ServiceUnavailableError
from aegis.core.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")


async def with_timeout(coro: Awaitable[T], *, seconds: float) -> T:
    """Await ``coro`` with a hard deadline, mapping timeout to a 503."""
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except TimeoutError as exc:
        raise ServiceUnavailableError(
            f"Operation timed out after {seconds:.1f}s.", code="timeout"
        ) from exc


def retrying(
    *, attempts: int = 3, base_delay: float = 0.2, max_delay: float = 5.0
) -> AsyncRetrying:
    """Return a configured tenacity ``AsyncRetrying`` for transient failures."""
    return AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=base_delay, max=max_delay),
        retry=retry_if_exception_type((ServiceUnavailableError, ConnectionError, TimeoutError)),
        reraise=True,
    )


class BreakerState(StrEnum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreaker:
    """Trips OPEN after ``failure_threshold`` consecutive failures."""

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int = 5,
        reset_timeout: float = 30.0,
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._reset_timeout = reset_timeout
        self._failures = 0
        self._opened_monotonic: float | None = None
        self._state = BreakerState.CLOSED
        self._lock = asyncio.Lock()

    @property
    def state(self) -> BreakerState:
        return self._state

    async def call(self, func: Callable[[], Awaitable[T]]) -> T:
        async with self._lock:
            self._maybe_half_open()
            if self._state is BreakerState.OPEN:
                raise ServiceUnavailableError(
                    f"Circuit '{self.name}' is open.", code="circuit_open"
                )
        try:
            result = await func()
        except Exception:
            await self._on_failure()
            raise
        else:
            await self._on_success()
            return result

    def _maybe_half_open(self) -> None:
        if self._state is BreakerState.OPEN and self._opened_monotonic is not None:
            elapsed = asyncio.get_event_loop().time() - self._opened_monotonic
            if elapsed >= self._reset_timeout:
                self._state = BreakerState.HALF_OPEN
                log.info("circuit.half_open", circuit=self.name)

    async def _on_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._state = BreakerState.CLOSED
            self._opened_monotonic = None

    async def _on_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._state = BreakerState.OPEN
                self._opened_monotonic = asyncio.get_event_loop().time()
                log.warning("circuit.open", circuit=self.name, failures=self._failures)
