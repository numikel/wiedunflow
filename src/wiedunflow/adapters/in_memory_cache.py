# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from wiedunflow.entities.cache_entry import FileCacheEntry


class InMemoryCache:
    """Simple dict-backed Cache for tests — no persistence across runs.

    Implements the Cache Protocol via duck typing.  The real SQLite-backed
    adapter (Sprint 3) is the durable counterpart; this in-memory version
    is preferred for unit tests because it has the same API surface but no
    database file lifecycle.
    """

    def __init__(self) -> None:
        self._store: dict[str, object] = {}
        self._file_cache: dict[str, FileCacheEntry] = {}

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

    def get_file_cache(self, sha256: str) -> FileCacheEntry | None:
        """Return the cached file-analysis payload for the given content hash."""
        return self._file_cache.get(sha256)

    def save_file_cache(self, entry: FileCacheEntry) -> None:
        """Persist the file-analysis payload keyed by its content SHA-256."""
        self._file_cache[entry.sha256] = entry
