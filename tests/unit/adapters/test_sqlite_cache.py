# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for SQLiteCache adapter (US-017, US-018, US-020, US-023, US-025, US-026)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from wiedunflow.adapters.sqlite_cache import SQLiteCache, _default_db_path
from wiedunflow.entities.cache_entry import (
    Bm25IndexEntry,
    CheckpointEntry,
    FileCacheEntry,
    PageRankSnapshot,
    PlanCacheEntry,
)
from wiedunflow.entities.cache_key import build_cache_key, build_plan_key

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cache(tmp_path: Path) -> SQLiteCache:
    """Return a fresh SQLiteCache backed by a temp file."""
    return SQLiteCache(path=tmp_path / "test_cache.db")


def _make_checkpoint(
    repo: Path,
    commit: str,
    lesson_id: str,
    model: str = "claude-haiku-4-5",
    cost_cents: int = 10,
) -> CheckpointEntry:
    key = build_cache_key(repo, commit, lesson_id)
    return CheckpointEntry(
        cache_key=key,
        repo_abs=repo,
        commit_hash=commit,
        lesson_id=lesson_id,
        lesson_json='{"id": "' + lesson_id + '"}',
        concepts_snapshot='["concept_a"]',
        model_used=model,
        cost_cents=cost_cents,
        created_at=datetime.now(UTC),
    )


def _make_plan(repo: Path, commit: str) -> PlanCacheEntry:
    key = build_plan_key(repo, commit)
    return PlanCacheEntry(
        cache_key=key,
        repo_abs=repo,
        commit_hash=commit,
        manifest_json='{"lessons": []}',
        pagerank_snapshot_json='{"ranks": {}, "top_n": 20}',
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Schema initialisation (US-020)
# ---------------------------------------------------------------------------


def test_us_020_init_creates_all_tables(tmp_path: Path) -> None:
    """Opening a new cache creates all expected tables."""
    cache = SQLiteCache(path=tmp_path / "cache.db")
    cursor = cache._conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = {row[0] for row in cursor.fetchall()}
    expected = {
        "schema_version",
        "generic_kv",
        "checkpoints",
        "plan_cache",
        "file_cache",
        "pagerank_snapshots",
        "bm25_index",
    }
    assert expected.issubset(tables)


def test_us_020_schema_version_matches_current(tmp_path: Path) -> None:
    """Schema version row reflects the in-code constant after fresh init."""
    from wiedunflow.adapters.sqlite_cache import _SCHEMA_VERSION

    cache = SQLiteCache(path=tmp_path / "cache.db")
    row = cache._conn.execute("SELECT version FROM schema_version").fetchone()
    assert row is not None
    assert row[0] == _SCHEMA_VERSION


def test_us_020_explicit_cache_path_creates_file(tmp_path: Path) -> None:
    """--cache-path override: file is created at the given path (AC1, AC2)."""
    db_path = tmp_path / "subdir" / "mycache.db"
    assert not db_path.exists()
    cache = SQLiteCache(path=db_path)
    assert db_path.exists()
    assert db_path.is_file()
    cache.close()


def test_us_020_cache_path_directory_raises(tmp_path: Path) -> None:
    """Passing an existing directory as cache path raises ValueError (AC3)."""
    with pytest.raises(ValueError, match="must be a file"):
        SQLiteCache(path=tmp_path)


# ---------------------------------------------------------------------------
# Checkpoint roundtrip (US-017 resume)
# ---------------------------------------------------------------------------


def test_us_017_save_and_load_checkpoint_roundtrip(cache: SQLiteCache, tmp_path: Path) -> None:
    """save_checkpoint followed by load_checkpoints returns the same data."""
    repo = Path("/fake/repo")
    commit = "deadbeef"
    entry = _make_checkpoint(repo, commit, "lesson-001")

    cache.save_checkpoint(entry)
    loaded = cache.load_checkpoints(repo, commit)

    assert len(loaded) == 1
    loaded_entry = loaded[0]
    assert loaded_entry.cache_key == entry.cache_key
    assert loaded_entry.repo_abs == entry.repo_abs
    assert loaded_entry.commit_hash == entry.commit_hash
    assert loaded_entry.lesson_id == entry.lesson_id
    assert loaded_entry.lesson_json == entry.lesson_json
    assert loaded_entry.concepts_snapshot == entry.concepts_snapshot
    assert loaded_entry.model_used == entry.model_used
    assert loaded_entry.cost_cents == entry.cost_cents


def test_us_017_load_checkpoints_empty_for_unknown_repo(cache: SQLiteCache) -> None:
    """load_checkpoints returns empty list when no checkpoints exist."""
    result = cache.load_checkpoints(Path("/unknown/repo"), "no_commit")
    assert result == []


def test_us_017_load_checkpoints_isolated_by_commit(
    cache: SQLiteCache,
) -> None:
    """Checkpoints for different commits are isolated from each other."""
    repo = Path("/fake/repo")
    entry_a = _make_checkpoint(repo, "commit_a", "lesson-001")
    entry_b = _make_checkpoint(repo, "commit_b", "lesson-001")

    cache.save_checkpoint(entry_a)
    cache.save_checkpoint(entry_b)

    result_a = cache.load_checkpoints(repo, "commit_a")
    result_b = cache.load_checkpoints(repo, "commit_b")

    assert len(result_a) == 1 and result_a[0].commit_hash == "commit_a"
    assert len(result_b) == 1 and result_b[0].commit_hash == "commit_b"


# ---------------------------------------------------------------------------
# Plan cache + invalidation (US-018 regenerate-plan)
# ---------------------------------------------------------------------------


def test_us_018_save_and_get_plan_roundtrip(cache: SQLiteCache) -> None:
    """save_plan followed by get_plan returns the same plan entry."""
    repo = Path("/fake/repo")
    commit = "abc123"
    plan = _make_plan(repo, commit)

    cache.save_plan(plan)
    loaded = cache.get_plan(repo, commit)

    assert loaded is not None
    assert loaded.manifest_json == plan.manifest_json
    assert loaded.pagerank_snapshot_json == plan.pagerank_snapshot_json
    assert loaded.commit_hash == commit


def test_us_018_get_plan_returns_none_when_absent(cache: SQLiteCache) -> None:
    """get_plan returns None when no plan is cached (AC1 precondition)."""
    result = cache.get_plan(Path("/missing/repo"), "abc123")
    assert result is None


def test_us_018_invalidate_plan_removes_plan_row(cache: SQLiteCache) -> None:
    """invalidate_plan deletes the plan_cache row (AC1)."""
    repo = Path("/fake/repo")
    commit = "abc123"
    plan = _make_plan(repo, commit)

    cache.save_plan(plan)
    assert cache.get_plan(repo, commit) is not None

    cache.invalidate_plan(repo, commit)
    assert cache.get_plan(repo, commit) is None


def test_us_018_invalidate_plan_cascades_to_checkpoints(cache: SQLiteCache) -> None:
    """invalidate_plan also deletes all checkpoints for the same repo+commit (AC3)."""
    repo = Path("/fake/repo")
    commit = "abc123"

    cache.save_plan(_make_plan(repo, commit))
    for i in range(3):
        cache.save_checkpoint(_make_checkpoint(repo, commit, f"lesson-{i:03}"))

    assert len(cache.load_checkpoints(repo, commit)) == 3
    cache.invalidate_plan(repo, commit)
    assert len(cache.load_checkpoints(repo, commit)) == 0


def test_us_018_invalidate_plan_does_not_affect_other_commits(
    cache: SQLiteCache,
) -> None:
    """Invalidating one commit does not remove checkpoints for other commits."""
    repo = Path("/fake/repo")
    cache.save_plan(_make_plan(repo, "commit_a"))
    cache.save_plan(_make_plan(repo, "commit_b"))
    cache.save_checkpoint(_make_checkpoint(repo, "commit_a", "lesson-001"))
    cache.save_checkpoint(_make_checkpoint(repo, "commit_b", "lesson-001"))

    cache.invalidate_plan(repo, "commit_a")

    assert len(cache.load_checkpoints(repo, "commit_a")) == 0
    assert len(cache.load_checkpoints(repo, "commit_b")) == 1


# ---------------------------------------------------------------------------
# File cache (US-026 SHA-256 file granularity)
# ---------------------------------------------------------------------------


def test_us_026_get_file_cache_returns_none_when_absent(cache: SQLiteCache) -> None:
    """get_file_cache returns None for unknown SHA-256 (AC2 precondition)."""
    result = cache.get_file_cache("0" * 64)
    assert result is None


def test_us_026_save_and_get_file_cache_roundtrip(cache: SQLiteCache) -> None:
    """save_file_cache + get_file_cache preserves all fields."""
    sha = "a" * 64
    entry = FileCacheEntry(
        sha256=sha,
        ast_json='[{"name": "foo"}]',
        callgraph_json='{"edges": []}',
        created_at=datetime.now(UTC),
    )
    cache.save_file_cache(entry)
    loaded = cache.get_file_cache(sha)

    assert loaded is not None
    assert loaded.sha256 == sha
    assert loaded.ast_json == entry.ast_json
    assert loaded.callgraph_json == entry.callgraph_json


def test_us_026_file_cache_null_fields_round_trip(cache: SQLiteCache) -> None:
    """Null ast_json and callgraph_json survive a roundtrip."""
    sha = "b" * 64
    entry = FileCacheEntry(
        sha256=sha, ast_json=None, callgraph_json=None, created_at=datetime.now(UTC)
    )
    cache.save_file_cache(entry)
    loaded = cache.get_file_cache(sha)
    assert loaded is not None
    assert loaded.ast_json is None
    assert loaded.callgraph_json is None


# ---------------------------------------------------------------------------
# PageRank snapshots (US-024)
# ---------------------------------------------------------------------------


def test_us_024_save_and_get_pagerank_snapshot_roundtrip(cache: SQLiteCache) -> None:
    """PageRank snapshot survives a save/load roundtrip."""
    repo = Path("/fake/repo")
    commit = "abc123"
    snapshot = PageRankSnapshot(ranks={"foo": 0.5, "bar": 0.3, "baz": 0.2}, top_n=20)

    cache.save_pagerank_snapshot(repo, commit, snapshot)
    loaded = cache.get_pagerank_snapshot(repo, commit)

    assert loaded is not None
    assert loaded.ranks == snapshot.ranks
    assert loaded.top_n == 20


def test_us_024_get_pagerank_snapshot_returns_none_when_absent(cache: SQLiteCache) -> None:
    """get_pagerank_snapshot returns None when no snapshot is stored."""
    result = cache.get_pagerank_snapshot(Path("/missing"), "no_commit")
    assert result is None


# ---------------------------------------------------------------------------
# Generic Cache Protocol (ports.Cache compatibility)
# ---------------------------------------------------------------------------


def test_generic_kv_get_returns_none_when_absent(cache: SQLiteCache) -> None:
    """Generic get() returns None for unknown keys."""
    assert cache.get("nonexistent_key") is None


def test_generic_kv_set_and_get_roundtrip(cache: SQLiteCache) -> None:
    """Generic set/get roundtrip preserves JSON-serialisable values."""
    cache.set("my_key", {"hello": "world", "n": 42})
    loaded = cache.get("my_key")
    assert loaded == {"hello": "world", "n": 42}


def test_generic_kv_set_overwrites_existing(cache: SQLiteCache) -> None:
    """Calling set() twice on the same key replaces the value."""
    cache.set("k", "original")
    cache.set("k", "updated")
    assert cache.get("k") == "updated"


# ---------------------------------------------------------------------------
# Concurrent writes (US-023 thread safety)
# ---------------------------------------------------------------------------


def test_us_023_concurrent_writes_no_corruption(tmp_path: Path) -> None:
    """50 threads each writing a unique checkpoint — all rows present, no corruption."""
    cache = SQLiteCache(path=tmp_path / "concurrent.db")
    repo = Path("/concurrent/repo")
    commit = "abc123"
    n_threads = 50

    def write_checkpoint(i: int) -> None:
        lesson_id = f"lesson-{i:03}"
        entry = _make_checkpoint(repo, commit, lesson_id)
        cache.save_checkpoint(entry)

    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(write_checkpoint, range(n_threads)))

    rows = cache.load_checkpoints(repo, commit)
    assert len(rows) == n_threads
    loaded_ids = {r.lesson_id for r in rows}
    expected_ids = {f"lesson-{i:03}" for i in range(n_threads)}
    assert loaded_ids == expected_ids


# ---------------------------------------------------------------------------
# Cross-OS platformdirs path resolution (US-025)
# ---------------------------------------------------------------------------


def test_us_025_default_db_path_contains_wiedunflow(tmp_path: Path) -> None:
    """Default DB path includes 'wiedunflow' (cache namespace) in the path."""
    with patch("platformdirs.user_cache_path", return_value=tmp_path / "wiedunflow") as mock_fn:
        # Ensure the returned path exists
        (tmp_path / "wiedunflow").mkdir(parents=True, exist_ok=True)
        db_path = _default_db_path()
        mock_fn.assert_called_once_with("wiedunflow", appauthor=False, ensure_exists=True)
        assert db_path.name == "cache.db"


@pytest.mark.parametrize(
    ("platform", "path_fragment"),
    [
        ("linux", ".cache"),
        ("win32", "Cache"),
        ("darwin", "Caches"),
    ],
)
def test_us_025_cross_os_path_suffix(tmp_path: Path, platform: str, path_fragment: str) -> None:
    """SQLiteCache accepts an explicit tmp_path — verifying cross-OS path creation."""
    # We verify that explicit path override works on any OS; actual platformdirs
    # per-OS resolution is tested by the CI matrix (linux/windows/macOS runners).
    db_path = tmp_path / platform / path_fragment / "cache.db"
    cache = SQLiteCache(path=db_path)
    assert db_path.exists()
    cache.close()


def test_us_025_cache_key_includes_repo_and_commit() -> None:
    """Cache keys are keyed by repo_abs + commit_hash (AC4)."""
    repo = Path("/home/user/repo")
    commit = "abc123"
    key_lesson = build_cache_key(repo, commit, "lesson-001")
    key_plan = build_plan_key(repo, commit)
    # Both keys encode repo+commit — they should differ only in the lesson slot
    assert key_lesson != key_plan
    # Neither key should be 'none' or 'empty'
    assert len(key_lesson) == 64
    assert len(key_plan) == 64


# ---------------------------------------------------------------------------
# BM25 index cache
# ---------------------------------------------------------------------------


def _bm25_entry(
    *,
    repo: str = "/repo",
    commit: str = "abc123def456",
    fingerprint: str = "fp001",
    lib_version: str = "0.2.2",
    blob: bytes = b"pickled-bm25-bytes",
) -> Bm25IndexEntry:
    return Bm25IndexEntry(
        repo_abs=repo,
        commit_hash=commit,
        corpus_config_fingerprint=fingerprint,
        bm25_lib_version=lib_version,
        blob=blob,
        created_at=datetime(2026, 5, 17, tzinfo=UTC),
    )


def test_bm25_index_save_and_load_roundtrip(cache: SQLiteCache, tmp_path: Path) -> None:
    """save then get round-trips identically when the lookup key matches the stored row."""
    # Use tmp_path so str(Path(...)) normalization stays consistent across OS
    # (Windows turns ``Path("/repo")`` into ``\\repo`` which would never match a
    # row saved as the forward-slash string).
    entry = _bm25_entry(repo=str(tmp_path))
    cache.save_bm25_index(entry)
    loaded = cache.get_bm25_index(tmp_path, entry.commit_hash, entry.corpus_config_fingerprint)
    assert loaded is not None
    assert loaded.blob == entry.blob
    assert loaded.bm25_lib_version == entry.bm25_lib_version


def test_bm25_index_miss_returns_none(cache: SQLiteCache, tmp_path: Path) -> None:
    assert cache.get_bm25_index(tmp_path / "no-such", "00", "fp") is None


def test_bm25_index_different_fingerprint_misses(cache: SQLiteCache, tmp_path: Path) -> None:
    """Changing exclude/include patterns must invalidate the cache row."""
    cache.save_bm25_index(_bm25_entry(repo=str(tmp_path), fingerprint="fp-old"))
    miss = cache.get_bm25_index(tmp_path, "abc123def456", "fp-new")
    assert miss is None


def test_bm25_index_same_key_replaces_blob(cache: SQLiteCache, tmp_path: Path) -> None:
    """save_bm25_index uses INSERT OR REPLACE — repeated saves update in place."""
    cache.save_bm25_index(_bm25_entry(repo=str(tmp_path), blob=b"v1"))
    cache.save_bm25_index(_bm25_entry(repo=str(tmp_path), blob=b"v2"))
    loaded = cache.get_bm25_index(tmp_path, "abc123def456", "fp001")
    assert loaded is not None
    assert loaded.blob == b"v2"


def test_schema_migration_v1_db_picks_up_bm25_table(tmp_path: Path) -> None:
    """Opening a database written under schema_version=1 must add bm25_index and bump version."""
    import sqlite3

    db_path = tmp_path / "legacy.db"
    # Hand-write the legacy v1 layout (no bm25_index table, version row at 1).
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
        INSERT INTO schema_version VALUES (1);
        CREATE TABLE generic_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, created_at TEXT NOT NULL);
        """
    )
    conn.commit()
    conn.close()

    cache = SQLiteCache(path=db_path)
    # Migration must surface the new bm25_index table.
    tables = {
        r[0]
        for r in cache._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "bm25_index" in tables
    # And bump schema_version row.
    row = cache._conn.execute("SELECT version FROM schema_version").fetchone()
    assert row[0] == 2


# ---------------------------------------------------------------------------
# PRAGMA tuning assertions
# ---------------------------------------------------------------------------


def test_sqlite_cache_synchronous_normal(tmp_path: Path) -> None:
    """PRAGMA synchronous must be 1 (NORMAL) after init.

    NORMAL is durable for regenerable cache data under WAL mode: a crash
    between a WAL frame write and the checkpoint yields a cache miss, not
    data corruption.  SQLite encodes NORMAL as integer 1.
    """
    cache = SQLiteCache(path=tmp_path / "cache.db")
    row = cache._conn.execute("PRAGMA synchronous").fetchone()
    assert row is not None
    assert row[0] == 1, f"Expected synchronous=1 (NORMAL), got {row[0]}"


def test_sqlite_cache_cache_size_32mb(tmp_path: Path) -> None:
    """PRAGMA cache_size must be -32000 (32 MB) after init.

    Negative values are kilobytes; -32000 = 32 MB page cache so that the
    working set of lesson_payload TEXT blobs stays in RAM for medium repos.
    """
    cache = SQLiteCache(path=tmp_path / "cache.db")
    row = cache._conn.execute("PRAGMA cache_size").fetchone()
    assert row is not None
    assert row[0] == -32000, f"Expected cache_size=-32000, got {row[0]}"


def test_sqlite_cache_temp_store_memory(tmp_path: Path) -> None:
    """PRAGMA temp_store must be 2 (MEMORY) after init.

    Storing sort/join scratch in memory avoids disk I/O on ORDER BY /
    DISTINCT operations on the small result sets used by this cache.
    SQLite encodes MEMORY as integer 2.
    """
    cache = SQLiteCache(path=tmp_path / "cache.db")
    row = cache._conn.execute("PRAGMA temp_store").fetchone()
    assert row is not None
    assert row[0] == 2, f"Expected temp_store=2 (MEMORY), got {row[0]}"
