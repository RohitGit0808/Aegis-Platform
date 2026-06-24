"""Block until the database and cache backends are reachable.

Intended as a container/K8s init step ("wait-for-it" style) so the app or worker
only starts once its dependencies accept connections. Polls:

  * the database via ``SELECT 1`` on the app's async engine, and
  * the cache via ``CacheBackend.ping()`` (real Redis, or the in-process
    fakeredis fallback when ``AEGIS_REDIS_URL`` is unset — which returns ready
    immediately).

Exits 0 once both are ready, or non-zero on timeout.

Usage:
    python -m scripts.wait_for_services [--timeout 60] [--interval 1.0]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from sqlalchemy import text


async def _check_db() -> bool:
    from aegis.db.session import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _check_redis() -> bool:
    from aegis.cache.redis import get_cache

    try:
        return await get_cache().ping()
    except Exception:
        return False


async def _wait(timeout: float, interval: float) -> int:
    deadline = time.monotonic() + timeout
    db_ready = redis_ready = False

    while True:
        if not db_ready:
            db_ready = await _check_db()
        if not redis_ready:
            redis_ready = await _check_redis()

        if db_ready and redis_ready:
            print("services ready: db=ok cache=ok")
            return 0

        if time.monotonic() >= deadline:
            print(
                f"timed out after {timeout:.0f}s "
                f"(db={'ok' if db_ready else 'down'}, "
                f"cache={'ok' if redis_ready else 'down'})",
                file=sys.stderr,
            )
            return 1

        pending = [name for name, ok in (("db", db_ready), ("cache", redis_ready)) if not ok]
        print(f"waiting for: {', '.join(pending)} ...")
        await asyncio.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Wait for Aegis dependencies to be ready.")
    parser.add_argument(
        "--timeout", type=float, default=60.0, help="Max seconds to wait (default: 60)."
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="Seconds between polls (default: 1.0)."
    )
    args = parser.parse_args()

    raise SystemExit(asyncio.run(_wait(args.timeout, args.interval)))


if __name__ == "__main__":
    main()
