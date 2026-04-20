"""Collection / iteration helpers."""

from collections.abc import Iterable


def unique(items: Iterable[int]) -> list[int]:
    """Return a list of unique items preserving input order."""
    seen: set[int] = set()
    out: list[int] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def chunk(items: list[int], size: int) -> list[list[int]]:
    """Split *items* into chunks of length *size*."""
    return [items[i : i + size] for i in range(0, len(items), size)]
