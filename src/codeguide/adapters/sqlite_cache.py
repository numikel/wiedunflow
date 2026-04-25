# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""SQLite-backed cache adapter — durable, cross-platform, WAL-enabled.

Implements the ``Cache`` Protocol (``ports.py``) for generic key/value storage
and provides Sprint-4-specific higher-level methods for checkpoints, plan cache,
file-level cache, and PageRank snapshots.

Design decisions (ADR-0008):
- WAL journal mode: allows concurrent readers while a write is in progress.
- ``check_same_thread=False`` + ``threading.Lock``: safe for multi-threaded use
  (parallel generation of leaf-level descriptions).
- No JSON1 extension: stores JSON as TEXT and decodes in Python (Windows builds
  do not always ship the JSON1 SQLite extension).
- Model name is *not* part of the cache key — a model switch requires
  ``--regenerate-plan`` (explicit user action, not silent reuse).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import platformdirs
import structlog

from codeguide.entities.cache_entry import (
    CheckpointEntry,
    FileCacheEntry,
    PageRankSnapshot,
    PlanCacheEntry,
)
from codeguide.entities.cache_key import build_plan_key

log = structlog.get_logger(__name__)

# Schema version — bump when forward-incompatible changes are made.
_SCHEMA_VERSION = 1

_DDL = f"""
CREATE TABLE IF NOT EXISTS schema_version (
    version  INTEGER PRIMARY KEY
);
INSERT OR IGNORE INTO schema_version VALUES ({_SCHEMA_VERSION});

CREATE TABLE IF NOT EXISTS checkpoints (
    cache_key          TEXT PRIMARY KEY,
    repo_abs           TEXT NOT NULL,
    commit_hash        TEXT NOT NULL,
    lesson_id          TEXT NOT NULL,
    lesson_json        TEXT NOT NULL,
    concepts_snapshot  TEXT NOT NULL,
    model_used         TEXT NOT NULL,
    cost_cents         INTEGER NOT NULL,
    created_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_repo
    ON checkpoints(repo_abs, commit_hash);

CREATE TABLE IF NOT EXISTS plan_cache (
    cache_key               TEXT PRIMARY KEY,
    repo_abs                TEXT NOT NULL,
    commit_hash             TEXT NOT NULL,
    manifest_json           TEXT NOT NULL,
    pagerank_snapshot_json  TEXT NOT NULL,
    created_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plan_repo
    ON plan_cache(repo_abs, commit_hash);

CREATE TABLE IF NOT EXISTS file_cache (
    sha256          TEXT PRIMARY KEY,
    ast_json        TEXT,
    callgraph_json  TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pagerank_snapshots (
    repo_abs     TEXT NOT NULL,
    commit_hash  TEXT NOT NULL,
    ranks_json   TEXT NOT NULL,
    top_n        INTEGER NOT NULL DEFAULT 20,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (repo_abs, commit_hash)
);
"""


def _default_db_path() -> Path:
    """Return the default SQLite database path for the current platform.

    Delegates to :func:`platformdirs.user_cache_path` which resolves to:
    - Linux:   ``~/.cache/codeguide/cache.db``
    - Windows: ``%LOCALAPPDATA%\\codeguide\\Cache\\cache.db``
    - macOS:   ``~/Library/Caches/codeguide/cache.db``
    """
    base: Path = platformdirs.user_cache_path("codeguide", appauthor=False, ensure_exists=True)
    return base / "cache.db"


class SQLiteCache:
    """Durable SQLite-backed cache with WAL mode and thread-safe writes.

    Usage
    -----
    >>> cache = SQLiteCache()  # default platform path
    >>> cache = SQLiteCache(path=Path("/tmp/test.db"))  # explicit path

    The cache implements the generic ``Cache`` Protocol for compatibility with
    the existing adapter injection points, plus Sprint-4-specific typed methods
    for checkpoints, plan cache, file cache, and PageRank snapshots.
    """

    def __init__(self, path: Path | None = None) -> None:
        """Initialise the cache, creating the database file and schema if needed.

        Args:
            path: Explicit path for the ``cache.db`` file.  When ``None``,
                :func:`_default_db_path` is used (cross-platform via
                :mod:`platformdirs`).  The parent directory is created if it
                does not exist.

        Raises:
            PermissionError: If the path is not writable.
            NotADirectoryError: If a non-directory path component blocks
                directory creation.
        """
        if path is None:
            db_path = _default_db_path()
        else:
            if path.is_dir():
                raise ValueError(f"cache path must be a file, not a directory: {path}")
            path.parent.mkdir(parents=True, exist_ok=True)
            db_path = path

        self._path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we use explicit transactions
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        log.info("sqlite_cache.opened", path=str(db_path))

    # ------------------------------------------------------------------
    # Cache Protocol (ports.Cache compatibility)
    # ------------------------------------------------------------------

    def get(self, key: str) -> object | None:
        """Return the JSON-decoded value for *key*, or ``None`` if absent.

        Satisfies the generic ``Cache`` Protocol used by injection points that
        are not stage-specific.

        Args:
            key: Arbitrary string cache key.

        Returns:
            The stored value (decoded from JSON), or ``None``.
        """
        row = self._conn.execute("SELECT value FROM generic_kv WHERE key = ?", (key,)).fetchone()
        if row is None:
            log.debug("cache.miss", key=key[:16])
            return None
        log.debug("cache.hit", key=key[:16])
        result: object = json.loads(row["value"])
        return result

    def set(self, key: str, value: object) -> None:
        """Store *value* (JSON-serialised) under *key*.

        Args:
            key: Arbitrary string cache key.
            value: JSON-serialisable Python object.
        """
        serialised = json.dumps(value)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO generic_kv(key, value, created_at) VALUES (?, ?, ?)",
                (key, serialised, _utcnow()),
            )
        log.debug("cache.set", key=key[:16])

    # ------------------------------------------------------------------
    # Checkpoint methods (US-017 resume)
    # ------------------------------------------------------------------

    def save_checkpoint(self, entry: CheckpointEntry) -> None:
        """Persist a completed-lesson checkpoint row.

        Args:
            entry: Checkpoint data to persist (see :class:`CheckpointEntry`).
        """
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO checkpoints
                       (cache_key, repo_abs, commit_hash, lesson_id,
                        lesson_json, concepts_snapshot, model_used,
                        cost_cents, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.cache_key,
                    str(entry.repo_abs),
                    entry.commit_hash,
                    entry.lesson_id,
                    entry.lesson_json,
                    entry.concepts_snapshot,
                    entry.model_used,
                    entry.cost_cents,
                    entry.created_at.isoformat(),
                ),
            )
        log.info(
            "checkpoint.saved",
            repo=str(entry.repo_abs),
            commit=entry.commit_hash[:8],
            lesson=entry.lesson_id,
        )

    def has_checkpoint(self, repo_abs: Path) -> bool:
        """Return ``True`` if any checkpoint row exists for ``repo_abs`` (any commit).

        Used by the menu's ``Resume last run`` action (ADR-0013 Step 8) to
        decide whether to launch the resume flow or surface a "no checkpoint
        found" message before sending the user back to the menu.
        """
        row = self._conn.execute(
            "SELECT 1 FROM checkpoints WHERE repo_abs = ? LIMIT 1",
            (str(repo_abs),),
        ).fetchone()
        return row is not None

    def load_checkpoints(self, repo_abs: Path, commit: str) -> list[CheckpointEntry]:
        """Return all checkpoint entries for *repo_abs* + *commit*, ordered by creation time.

        Args:
            repo_abs: Absolute path to the repository root.
            commit: Git commit hash.

        Returns:
            List of :class:`CheckpointEntry` (may be empty for a first run).
        """
        rows = self._conn.execute(
            "SELECT * FROM checkpoints WHERE repo_abs = ? AND commit_hash = ? ORDER BY created_at",
            (str(repo_abs), commit),
        ).fetchall()
        entries = [
            CheckpointEntry(
                cache_key=row["cache_key"],
                repo_abs=Path(row["repo_abs"]),
                commit_hash=row["commit_hash"],
                lesson_id=row["lesson_id"],
                lesson_json=row["lesson_json"],
                concepts_snapshot=row["concepts_snapshot"],
                model_used=row["model_used"],
                cost_cents=row["cost_cents"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]
        log.info(
            "checkpoints.loaded",
            repo=str(repo_abs),
            commit=commit[:8],
            count=len(entries),
        )
        return entries

    # ------------------------------------------------------------------
    # Plan cache methods (US-018 regenerate-plan)
    # ------------------------------------------------------------------

    def save_plan(self, entry: PlanCacheEntry) -> None:
        """Persist a lesson-manifest cache entry.

        Args:
            entry: Plan data to persist (see :class:`PlanCacheEntry`).
        """
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO plan_cache
                       (cache_key, repo_abs, commit_hash,
                        manifest_json, pagerank_snapshot_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    entry.cache_key,
                    str(entry.repo_abs),
                    entry.commit_hash,
                    entry.manifest_json,
                    entry.pagerank_snapshot_json,
                    entry.created_at.isoformat(),
                ),
            )
        log.info(
            "plan.saved",
            repo=str(entry.repo_abs),
            commit=entry.commit_hash[:8],
        )

    def get_plan(self, repo_abs: Path, commit: str) -> PlanCacheEntry | None:
        """Return the cached plan for *repo_abs* + *commit*, or ``None``.

        Args:
            repo_abs: Absolute path to the repository root.
            commit: Git commit hash.

        Returns:
            :class:`PlanCacheEntry` if found, ``None`` otherwise.
        """
        key = build_plan_key(repo_abs, commit)
        row = self._conn.execute("SELECT * FROM plan_cache WHERE cache_key = ?", (key,)).fetchone()
        if row is None:
            log.info("plan.miss", repo=str(repo_abs), commit=commit[:8])
            return None
        log.info("plan.hit", repo=str(repo_abs), commit=commit[:8])
        return PlanCacheEntry(
            cache_key=row["cache_key"],
            repo_abs=Path(row["repo_abs"]),
            commit_hash=row["commit_hash"],
            manifest_json=row["manifest_json"],
            pagerank_snapshot_json=row["pagerank_snapshot_json"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def invalidate_plan(self, repo_abs: Path, commit: str) -> None:
        """Delete the cached plan and cascade-delete all checkpoints.

        Implements ``--regenerate-plan``: removes the ``plan_cache`` row for
        this repo+commit and all matching ``checkpoints`` rows (lesson IDs may
        differ after a re-plan).

        Args:
            repo_abs: Absolute path to the repository root.
            commit: Git commit hash.
        """
        key = build_plan_key(repo_abs, commit)
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM plan_cache WHERE cache_key = ?", (key,))
            self._conn.execute(
                "DELETE FROM checkpoints WHERE repo_abs = ? AND commit_hash = ?",
                (str(repo_abs), commit),
            )
        log.info(
            "plan.invalidated",
            repo=str(repo_abs),
            commit=commit[:8],
        )

    # ------------------------------------------------------------------
    # File cache methods (US-026 SHA-256 file granularity)
    # ------------------------------------------------------------------

    def save_file_cache(self, entry: FileCacheEntry) -> None:
        """Persist file-level analysis results keyed by content SHA-256.

        Args:
            entry: File cache data to persist (see :class:`FileCacheEntry`).
        """
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO file_cache
                       (sha256, ast_json, callgraph_json, created_at)
                       VALUES (?, ?, ?, ?)""",
                (
                    entry.sha256,
                    entry.ast_json,
                    entry.callgraph_json,
                    entry.created_at.isoformat(),
                ),
            )
        log.debug("file_cache.saved", sha256=entry.sha256[:12])

    def get_file_cache(self, sha256: str) -> FileCacheEntry | None:
        """Return cached AST/call-graph data for a file identified by *sha256*.

        Args:
            sha256: SHA-256 hex digest of raw file content.

        Returns:
            :class:`FileCacheEntry` if found, ``None`` otherwise.
        """
        row = self._conn.execute("SELECT * FROM file_cache WHERE sha256 = ?", (sha256,)).fetchone()
        if row is None:
            log.debug("file_cache.miss", sha256=sha256[:12])
            return None
        log.debug("file_cache.hit", sha256=sha256[:12])
        return FileCacheEntry(
            sha256=row["sha256"],
            ast_json=row["ast_json"],
            callgraph_json=row["callgraph_json"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    # ------------------------------------------------------------------
    # PageRank snapshot methods (US-024 diff threshold)
    # ------------------------------------------------------------------

    def save_pagerank_snapshot(
        self, repo_abs: Path, commit: str, snapshot: PageRankSnapshot
    ) -> None:
        """Persist a PageRank snapshot for diff computation on the next run.

        Args:
            repo_abs: Absolute path to the repository root.
            commit: Git commit hash.
            snapshot: PageRank snapshot to persist.
        """
        ranks_json = json.dumps(snapshot.ranks)
        with self._lock, self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO pagerank_snapshots
                       (repo_abs, commit_hash, ranks_json, top_n, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                (str(repo_abs), commit, ranks_json, snapshot.top_n, _utcnow()),
            )
        log.info("pagerank_snapshot.saved", repo=str(repo_abs), commit=commit[:8])

    def get_pagerank_snapshot(self, repo_abs: Path, commit: str) -> PageRankSnapshot | None:
        """Return the stored PageRank snapshot for *repo_abs* + *commit*, or ``None``.

        Args:
            repo_abs: Absolute path to the repository root.
            commit: Git commit hash.

        Returns:
            :class:`PageRankSnapshot` if found, ``None`` otherwise.
        """
        row = self._conn.execute(
            "SELECT ranks_json, top_n FROM pagerank_snapshots WHERE repo_abs = ? AND commit_hash = ?",
            (str(repo_abs), commit),
        ).fetchone()
        if row is None:
            log.info("pagerank_snapshot.miss", repo=str(repo_abs), commit=commit[:8])
            return None
        log.info("pagerank_snapshot.hit", repo=str(repo_abs), commit=commit[:8])
        return PageRankSnapshot(
            ranks=json.loads(row["ranks_json"]),
            top_n=row["top_n"],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        """Execute the DDL statements to create tables and indexes."""
        # Execute each statement individually to avoid issues with executescript
        # dropping WAL mode on some SQLite builds.
        with self._lock, self._conn:
            # Create generic_kv table (for Cache Protocol compatibility)
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS generic_kv (
                        key         TEXT PRIMARY KEY,
                        value       TEXT NOT NULL,
                        created_at  TEXT NOT NULL
                    )"""
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
            )
            self._conn.execute(f"INSERT OR IGNORE INTO schema_version VALUES ({_SCHEMA_VERSION})")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS checkpoints (
                        cache_key          TEXT PRIMARY KEY,
                        repo_abs           TEXT NOT NULL,
                        commit_hash        TEXT NOT NULL,
                        lesson_id          TEXT NOT NULL,
                        lesson_json        TEXT NOT NULL,
                        concepts_snapshot  TEXT NOT NULL,
                        model_used         TEXT NOT NULL,
                        cost_cents         INTEGER NOT NULL,
                        created_at         TEXT NOT NULL
                    )"""
            )
            self._conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_checkpoints_repo
                       ON checkpoints(repo_abs, commit_hash)"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS plan_cache (
                        cache_key               TEXT PRIMARY KEY,
                        repo_abs                TEXT NOT NULL,
                        commit_hash             TEXT NOT NULL,
                        manifest_json           TEXT NOT NULL,
                        pagerank_snapshot_json  TEXT NOT NULL,
                        created_at              TEXT NOT NULL
                    )"""
            )
            self._conn.execute(
                """CREATE INDEX IF NOT EXISTS idx_plan_repo
                       ON plan_cache(repo_abs, commit_hash)"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS file_cache (
                        sha256          TEXT PRIMARY KEY,
                        ast_json        TEXT,
                        callgraph_json  TEXT,
                        created_at      TEXT NOT NULL
                    )"""
            )
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS pagerank_snapshots (
                        repo_abs     TEXT NOT NULL,
                        commit_hash  TEXT NOT NULL,
                        ranks_json   TEXT NOT NULL,
                        top_n        INTEGER NOT NULL DEFAULT 20,
                        created_at   TEXT NOT NULL,
                        PRIMARY KEY (repo_abs, commit_hash)
                    )"""
            )

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
        log.info("sqlite_cache.closed", path=str(self._path))


def _utcnow() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(tz=UTC).isoformat()
