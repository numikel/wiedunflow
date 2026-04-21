# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Pydantic models for SQLite cache rows.

Each model maps 1-to-1 to a table in the ``cache.db`` schema defined in
``docs/adr/0008-cache-schema-v1.md``.  All models are frozen (immutable after
construction) to prevent accidental mutation of cached data.

Serialization note: JSON fields stored in SQLite as TEXT are decoded in the
adapter layer (``sqlite_cache.py``).  These models operate on the decoded
Python objects — not on raw SQL TEXT.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class CheckpointEntry(BaseModel):
    """One completed lesson checkpoint row in the ``checkpoints`` table."""

    model_config = ConfigDict(frozen=True)

    cache_key: str
    """SHA-256 key: ``build_cache_key(repo_abs, commit_hash, lesson_id)``."""
    repo_abs: Path
    """Absolute path to the repository root at the time of generation."""
    commit_hash: str
    """Git commit hash that was current when the lesson was generated."""
    lesson_id: str
    """Stable lesson identifier matching ``LessonSpec.id``."""
    lesson_json: str
    """JSON-serialised ``Lesson`` entity."""
    concepts_snapshot: str
    """JSON-serialised tuple of concept strings introduced up to this lesson."""
    model_used: str
    """LLM model identifier used for narration (e.g. ``"claude-opus-4-7"``).

    Stored for audit purposes only — it is **not** part of the cache key.
    """
    cost_cents: int
    """Estimated cost of this lesson's generation, in USD cents x 100."""
    created_at: datetime
    """UTC timestamp of when this checkpoint was persisted."""


class PlanCacheEntry(BaseModel):
    """One lesson-manifest row in the ``plan_cache`` table."""

    model_config = ConfigDict(frozen=True)

    cache_key: str
    """SHA-256 key: ``build_plan_key(repo_abs, commit_hash)``."""
    repo_abs: Path
    """Absolute path to the repository root."""
    commit_hash: str
    """Git commit hash current at plan-generation time."""
    manifest_json: str
    """JSON-serialised ``LessonManifest``."""
    pagerank_snapshot_json: str
    """JSON-serialised ``PageRankSnapshot`` captured at planning time.

    Stored alongside the manifest so the cache layer can cheaply compute
    the PageRank diff on subsequent runs without re-ranking the full graph.
    """
    created_at: datetime
    """UTC timestamp of when this plan was cached."""


class FileCacheEntry(BaseModel):
    """One source-file analysis row in the ``file_cache`` table.

    Keyed by ``sha256`` of raw file content — content-addressed so that
    identical files in different repos or paths share a single cache row.
    """

    model_config = ConfigDict(frozen=True)

    sha256: str
    """SHA-256 hex digest of the raw file bytes (primary key)."""
    ast_json: str | None = None
    """JSON-serialised AST/symbol list, or None if not yet analysed."""
    callgraph_json: str | None = None
    """JSON-serialised call-graph slice for this file, or None."""
    created_at: datetime
    """UTC timestamp of initial insertion."""


class PageRankSnapshot(BaseModel):
    """Lightweight snapshot of the top-N PageRank results for diff computation.

    Stored in the ``pagerank_snapshots`` table (keyed by repo_abs + commit_hash)
    and embedded in every ``PlanCacheEntry`` for convenience.
    """

    model_config = ConfigDict(frozen=True)

    ranks: dict[str, float]
    """Mapping of symbol_name → PageRank score for all ranked symbols."""
    top_n: int = 20
    """Number of top symbols considered for the diff (default 20)."""

    def top_n_set(self) -> set[str]:
        """Return the set of the top-*top_n* symbol names by PageRank score.

        Returns:
            A ``set`` of symbol names (fewer than *top_n* when the graph has
            fewer symbols than the requested count).
        """
        sorted_syms = sorted(self.ranks.items(), key=lambda kv: kv[1], reverse=True)
        return {name for name, _ in sorted_syms[: self.top_n]}
