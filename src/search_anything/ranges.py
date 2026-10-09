"""Parsing and formatting for one RFC 9110 byte range."""

from __future__ import annotations

import re
from dataclasses import dataclass

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


@dataclass(frozen=True)
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    def header_value(self) -> str:
        return f"bytes={self.start}-{self.end}"


class UnsatisfiableRange(ValueError):
    def __init__(self, size: int) -> None:
        super().__init__("requested byte range cannot be satisfied")
        self.size = size


def parse_range(value: str | None, size: int) -> ByteRange | None:
    if value is None:
        return None
    match = _RANGE.fullmatch(value.strip())
    if match is None or size < 0:
        raise UnsatisfiableRange(size)
    first, last = match.groups()
    if not first and not last:
        raise UnsatisfiableRange(size)
    if not first:
        suffix = int(last)
        if suffix == 0 or size == 0:
            raise UnsatisfiableRange(size)
        return ByteRange(max(0, size - suffix), size - 1)
    start = int(first)
    if start >= size:
        raise UnsatisfiableRange(size)
    end = size - 1 if not last else min(int(last), size - 1)
    if end < start:
        raise UnsatisfiableRange(size)
    return ByteRange(start, end)
