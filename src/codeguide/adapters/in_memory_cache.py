# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations


class InMemoryCache:
    """Simple dict-backed Cache for tests — no persistence across runs.

    Implements the Cache Protocol via duck typing.  The real SQLite-backed
    adapter (Sprint 3) will replace this with durable caching.
    """

    def __init__(self) -> None:
        self._store: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        """Return the cached value for key, or None if absent.

        Args:
            key: Cache key.

        Returns:
            The stored value, or None if the key is not present.
        """
        return self._store.get(key)

    def set(self, key: str, value: object) -> None:
        """Store value under key.

        Args:
            key: Cache key.
            value: Value to store.
        """
        self._store[key] = value
