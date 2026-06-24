"""Runnable seed wrapper: ``python -m scripts.seed``.

Thin shim around the CLI seed logic so the same admin user and demo suite can be
provisioned from a plain Python entrypoint (handy in Docker/K8s init jobs where
invoking the ``aegis`` console script is inconvenient). All real work lives in
:func:`aegis.cli._seed`; this file only drives the event loop.
"""

from __future__ import annotations

import asyncio


def main() -> None:
    # Imported lazily so merely importing this module has no side effects.
    from aegis.cli import _seed

    asyncio.run(_seed())


if __name__ == "__main__":
    main()
