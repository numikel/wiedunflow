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
    """Port for language-specific AST parsing and call-graph extraction."""

    def parse(self, path: Path) -> tuple[list[CodeSymbol], CallGraph]:
        """Parse a source file and return its symbols and call graph."""
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
