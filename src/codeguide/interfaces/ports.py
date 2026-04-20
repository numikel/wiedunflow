# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from codeguide.entities.call_graph import CallGraph
from codeguide.entities.code_symbol import CodeSymbol
from codeguide.entities.lesson import Lesson
from codeguide.entities.lesson_manifest import LessonManifest
from codeguide.entities.ranked_graph import RankedGraph


@runtime_checkable
class LLMProvider(Protocol):
    """Port for LLM interactions: planning and per-lesson narration."""

    def plan(self, outline: str) -> LessonManifest:
        """Produce a structured lesson manifest from a code-graph outline."""
        ...

    def narrate(
        self,
        spec_json: str,
        concepts_introduced: tuple[str, ...],
    ) -> Lesson:
        """Generate narrative text for a single lesson spec.

        Args:
            spec_json: JSON-serialised LessonSpec.
            concepts_introduced: Concepts already taught in prior lessons — must
                not be re-taught, enforcing narrative coherence.
        """
        ...


@runtime_checkable
class Parser(Protocol):
    """Port for language-specific AST parsing and call-graph extraction.

    Implementations produce a *raw* ``CallGraph`` — edges may reference textual
    callee names that are not resolved across files. The :class:`Resolver` port
    refines the raw graph via semantic analysis (Jedi) and attaches
    ``resolution_stats``.
    """

    def parse(
        self,
        files: list[Path],
        repo_root: Path,
    ) -> tuple[list[CodeSymbol], CallGraph]:
        """Parse a batch of source files and return their symbols + raw call graph.

        Args:
            files: Source files to parse (paths typically relative to ``repo_root``
                but absolute paths are accepted).
            repo_root: Anchor for qualified-name construction (e.g.
                ``package.module.function``).

        Returns:
            Tuple of ``(symbols, raw_graph)``. ``raw_graph.resolution_stats`` is
            ``None`` at this stage; the Resolver fills it.
        """
        ...


@runtime_checkable
class Resolver(Protocol):
    """Port for semantic resolution of call-graph edges (Jedi-powered by default).

    Consumes the raw graph emitted by :class:`Parser` and returns a refined graph
    where edges reference known node names. Attaches a :class:`ResolutionStats`
    summary reporting 3-tier coverage (resolved / uncertain / unresolved).
    """

    def resolve(
        self,
        symbols: list[CodeSymbol],
        raw_graph: CallGraph,
        repo_root: Path,
    ) -> CallGraph:
        """Resolve raw-graph edges against ``symbols`` using semantic analysis.

        Edges that do not resolve to any known symbol are pruned. Dynamic imports
        and reflection sites propagate ``is_dynamic_import`` / ``is_uncertain``
        markers on the corresponding symbols.
        """
        ...


@runtime_checkable
class Ranker(Protocol):
    """Port for graph ranking: PageRank + community detection + topological order.

    The default adapter is ``networkx``-based. Consumed by Stage 4 (planning) to
    seed the "leaves → roots" story outline.
    """

    def rank(self, graph: CallGraph) -> RankedGraph:
        """Compute PageRank, Louvain communities, and SCC-condensed topological order."""
        ...


@runtime_checkable
class VectorStore(Protocol):
    """Port for BM25 / embedding-based document retrieval (RAG stage)."""

    def index(self, documents: list[tuple[str, str]]) -> None:
        """Index a list of (id, text) pairs."""
        ...

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        """Return up to k (id, score) pairs for the given query."""
        ...


@runtime_checkable
class Cache(Protocol):
    """Port for stage-level caching (SQLite-backed in the default adapter)."""

    def get(self, key: str) -> object | None:
        """Return the cached value for key, or None if absent."""
        ...

    def set(self, key: str, value: object) -> None:
        """Store value under key."""
        ...


@runtime_checkable
class Clock(Protocol):
    """Port for current-time injection — simplifies deterministic testing."""

    def now(self) -> datetime:
        """Return the current UTC datetime."""
        ...
