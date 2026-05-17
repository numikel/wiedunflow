# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

from wiedunflow.entities.cache_entry import Bm25IndexEntry, FileCacheEntry


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
        # Keyed by (repo_abs, commit_hash, corpus_config_fingerprint) to mirror
        # the SQLite schema's composite primary key.
        self._bm25_cache: dict[tuple[str, str, str], Bm25IndexEntry] = {}

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

    def get_bm25_index(
        self, repo_abs: Path, commit: str, fingerprint: str
    ) -> Bm25IndexEntry | None:
        """Return the cached BM25 index payload or ``None`` on miss."""
        return self._bm25_cache.get((str(repo_abs), commit, fingerprint))

    def save_bm25_index(self, entry: Bm25IndexEntry) -> None:
        """Persist a BM25 cache entry."""
        self._bm25_cache[(entry.repo_abs, entry.commit_hash, entry.corpus_config_fingerprint)] = (
            entry
        )
