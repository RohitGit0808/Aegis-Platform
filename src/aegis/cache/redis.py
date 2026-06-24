"""Cache / queue / pub-sub backend with a zero-config in-process fallback.

When ``AEGIS_REDIS_URL`` is set we talk to real Redis (``redis.asyncio``);
otherwise we transparently use :mod:`fakeredis` so the whole platform — rate
limiting, idempotency, distributed locks and live run events — works on a
laptop with nothing installed. The rest of the codebase depends only on the
:class:`CacheBackend` facade, never on the concrete client.
"""

from __future__ import annotations

from typing import Any

from aegis.core.config import settings
from aegis.core.logging import get_logger

log = get_logger(__name__)


class CacheBackend:
    """Thin async facade over a Redis-compatible client."""

    def __init__(self, client: Any) -> None:
        self._redis = client

    @property
    def client(self) -> Any:
        return self._redis

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        await self._redis.set(key, value, ex=ttl_seconds)

    async def set_if_absent(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        """Atomic SET NX EX — the building block for locks and idempotency."""
        return bool(await self._redis.set(key, value, nx=True, ex=ttl_seconds))

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._redis.delete(*keys)

    async def incr(self, key: str) -> int:
        return int(await self._redis.incr(key))

    async def expire(self, key: str, ttl_seconds: int) -> None:
        await self._redis.expire(key, ttl_seconds)

    async def publish(self, channel: str, message: str) -> None:
        await self._redis.publish(channel, message)

    def pubsub(self) -> Any:
        return self._redis.pubsub()

    async def allow_request(self, key: str, *, limit: int, window_seconds: int) -> bool:
        """Fixed-window rate limit. Returns True if the request is permitted."""
        count = await self.incr(key)
        if count == 1:
            await self.expire(key, window_seconds)
        return count <= limit

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:  # pragma: no cover - defensive
            return False

    async def close(self) -> None:
        close = getattr(self._redis, "aclose", None) or getattr(self._redis, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


def _build_client() -> Any:
    if settings.use_fake_cache:
        import fakeredis.aioredis

        log.info("cache.backend", backend="fakeredis", reason="no AEGIS_REDIS_URL set")
        return fakeredis.aioredis.FakeRedis(decode_responses=True)

    import redis.asyncio as aioredis

    log.info("cache.backend", backend="redis", url=settings.redis_url)
    return aioredis.from_url(settings.redis_url, decode_responses=True)  # type: ignore[no-untyped-call]


_cache: CacheBackend | None = None


def get_cache() -> CacheBackend:
    """Return the process-wide cache backend, building it lazily."""
    global _cache
    if _cache is None:
        _cache = CacheBackend(_build_client())
    return _cache


async def close_cache() -> None:
    global _cache
    if _cache is not None:
        await _cache.close()
        _cache = None
