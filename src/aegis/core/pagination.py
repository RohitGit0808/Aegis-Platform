"""Offset/limit pagination primitives shared by the API and repositories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(slots=True, frozen=True)
class PaginationParams:
    """Validated pagination window. Page is 1-based."""

    MAX_SIZE: ClassVar[int] = 100

    page: int = 1
    size: int = 20

    def __post_init__(self) -> None:
        if self.page < 1:
            object.__setattr__(self, "page", 1)
        if self.size < 1:
            object.__setattr__(self, "size", 1)
        if self.size > self.MAX_SIZE:
            object.__setattr__(self, "size", self.MAX_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size
