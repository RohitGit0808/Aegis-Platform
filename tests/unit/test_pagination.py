"""Unit tests for :mod:`aegis.core.pagination`.

``PaginationParams`` is a frozen dataclass that normalises its inputs in
``__post_init__`` and derives offset/limit. Pure arithmetic, fully deterministic.
"""

from __future__ import annotations

import pytest

from aegis.core.pagination import PaginationParams

pytestmark = pytest.mark.unit


def test_defaults() -> None:
    params = PaginationParams()
    assert params.page == 1
    assert params.size == 20
    assert params.offset == 0
    assert params.limit == 20


@pytest.mark.parametrize(
    ("page", "size", "expected_offset", "expected_limit"),
    [
        (1, 20, 0, 20),
        (2, 20, 20, 20),
        (3, 50, 100, 50),
        (5, 10, 40, 10),
    ],
)
def test_offset_and_limit_math(
    page: int, size: int, expected_offset: int, expected_limit: int
) -> None:
    params = PaginationParams(page=page, size=size)
    assert params.offset == expected_offset
    assert params.limit == expected_limit


def test_size_clamped_to_max() -> None:
    params = PaginationParams(page=1, size=10_000)
    assert params.size == PaginationParams.MAX_SIZE
    assert params.size == 100
    assert params.limit == 100


def test_page_below_one_normalised() -> None:
    assert PaginationParams(page=0).page == 1
    assert PaginationParams(page=-5).page == 1


def test_size_below_one_normalised() -> None:
    assert PaginationParams(size=0).size == 1
    assert PaginationParams(size=-3).size == 1


def test_offset_uses_normalised_values() -> None:
    # page<1 -> 1 and size>MAX -> MAX, so offset reflects the clamped values.
    params = PaginationParams(page=-1, size=10_000)
    assert params.page == 1
    assert params.size == PaginationParams.MAX_SIZE
    assert params.offset == 0
