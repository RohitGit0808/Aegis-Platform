"""Idempotency helpers built on the cache backend.

Clients pass an ``Idempotency-Key`` header on run creation; the key maps to the
id of the run that was created for it. Replaying the same key returns the
original run instead of starting a duplicate — the standard safe-retry contract
for non-idempotent POSTs.
"""

from __future__ import annotations

from aegis.cache.redis import CacheBackend

_PREFIX = "idem:"
_DEFAULT_TTL = 60 * 60 * 24  # 24h


async def lookup(cache: CacheBackend, key: str) -> str | None:
    """Return the previously stored resource id for ``key``, if any."""
    return await cache.get(f"{_PREFIX}{key}")


async def remember(
    cache: CacheBackend, key: str, resource_id: str, *, ttl_seconds: int = _DEFAULT_TTL
) -> None:
    await cache.set(f"{_PREFIX}{key}", resource_id, ttl_seconds=ttl_seconds)
