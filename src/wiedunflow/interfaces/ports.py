# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from wiedunflow.entities.cache_entry import Bm25IndexEntry, FileCacheEntry
from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.lesson_manifest import LessonManifest
from wiedunflow.entities.ranked_graph import RankedGraph

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PathOutsideRootError(PermissionError):
    """Raised when an LLM-controlled path escapes the designated repo root.

    Why: tool inputs to the Researcher agent include paths drawn from the
    prompt-injection surface (analyzed third-party repo docstrings or
    LLM-generated arguments). A crafted ``../../etc/passwd`` must not resolve
    to a real host file outside ``repo_root``.

    Inherits from :class:`PermissionError` so callers that already catch broad
    OS-level permission errors will also catch boundary violations without
    additional handling.
    """


# ---------------------------------------------------------------------------
# Value objects (Pydantic models used as ports-layer DTOs)
# ---------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """Specification for a tool that an agent can call."""

    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema object (required/properties/type)


class ToolCall(BaseModel):
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """Result of executing a :class:`ToolCall`."""

    tool_call_id: str
    content: str
    is_error: bool = False


class AgentTurn(BaseModel):
    """A single turn in an agent conversation transcript."""

    role: Literal["assistant", "tool"]
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class AgentResult(BaseModel):
    """Result of a completed agent loop run."""

    final_text: str | None
    transcript: list[AgentTurn]
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    stop_reason: Literal["end_turn", "max_iterations", "max_cost", "error"]
    iterations: int


# ---------------------------------------------------------------------------
# Protocols (ports)
# ---------------------------------------------------------------------------


@runtime_checkable
class SpendMeterProto(Protocol):
    """Port for the cumulative-cost meter consulted by adapters.

    Adapters read :attr:`total_cost_usd` at the start and end of each
    ``run_agent`` call to compute the per-call delta surfaced via
    :class:`AgentResult.total_cost_usd`. Cumulative spend remains on the
    meter for the whole run.
    """

    @property
    def total_cost_usd(self) -> float:
        """Cumulative USD spend across all :meth:`charge` calls so far."""
        ...

    def charge(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        provider: Literal["anthropic", "openai", "auto"] = "auto",
    ) -> None:
        """Record token usage for the given model.

        Cache token kwargs are optional (default zero); adapters that observe
        cache metrics in provider responses (Anthropic ``usage.cache_*_input_tokens``,
        OpenAI ``usage.prompt_tokens_details.cached_tokens``) forward them so the
        meter can apply provider-specific cache pricing multipliers.
        """
        ...

    def would_exceed(self) -> bool:
        """Return True if the accumulated spend already exceeds the budget."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Port for LLM interactions: planning and agent loops."""

    def plan(self, outline: str) -> LessonManifest:
        """Produce a structured lesson manifest from a code-graph outline."""
        ...

    def run_agent(
        self,
        *,
        system: str,
        user: str,
        tools: list[ToolSpec],
        tool_executor: Callable[[ToolCall], ToolResult],
        model: str,
        max_iterations: int = 15,
        max_cost_usd: float = 1.0,
        spend_meter: SpendMeterProto | None = None,
        prompt_caching: bool = False,
        max_history_iterations: int = 10,
    ) -> AgentResult:
        """Run an agent loop: call LLM → execute tools → repeat until end_turn or limits.

        Args:
            system: System prompt for the agent.
            user: Initial user message to start the conversation.
            tools: Tool specifications available to the agent.
            tool_executor: Callable that executes a :class:`ToolCall` and returns a
                :class:`ToolResult`. Called synchronously within the loop.
            model: Model identifier to use for the agent loop.
            max_iterations: Hard cap on loop iterations; returns ``stop_reason="max_iterations"``
                when reached.
            max_cost_usd: Soft budget cap; the loop aborts with ``stop_reason="max_cost"``
                when ``spend_meter.would_exceed()`` returns True.
            spend_meter: Optional :class:`SpendMeterProto` that tracks cumulative spend.
                When provided, :meth:`charge` is called after every LLM response and
                :meth:`would_exceed` is checked before the next iteration.
            prompt_caching: When True, providers that support manual cache markers
                (Anthropic) attach ``cache_control: {"type": "ephemeral"}`` to the
                system prompt and the last tool schema. Providers with automatic
                cache (OpenAI) ignore the flag — their cache hits surface through
                ``cached_tokens`` in ``response.usage`` regardless of this value.
                The default ``False`` preserves the v0.x.0 wire format for callers
                that have not opted in.
            max_history_iterations: Threshold for in-loop sliding-window context
                compression. When the message history would grow past this many
                iterations, the middle iterations are replaced with one-line
                summaries while the system prompt, initial user message, and the
                most recent iterations stay verbatim. Tool_use ↔ tool_result
                pairs are pruned together to preserve API validity.

        Returns:
            :class:`AgentResult` with the final text, full transcript, token counts,
            cost estimate, stop reason, and iteration count.
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
        cache: Cache | None = None,
    ) -> tuple[list[CodeSymbol], CallGraph]:
        """Parse a batch of source files and return their symbols + raw call graph.

        Args:
            files: Source files to parse (paths typically relative to ``repo_root``
                but absolute paths are accepted).
            repo_root: Anchor for qualified-name construction (e.g.
                ``package.module.function``).
            cache: Optional content-addressed file cache (ADR-0008). When
                supplied, each file's SHA-256 is looked up; cache hits skip
                re-parsing, misses save the parsed slice for the next run.
                ``None`` disables caching (used by tests and stub adapters).

        Returns:
            Tuple of ``(symbols, raw_graph)``. ``raw_graph.resolution_stats`` is
            ``None`` at this stage; the Resolver fills it.
        """
        ...


@runtime_checkable
class Resolver(Protocol):
    """Port for semantic resolution of call-graph edges (Jedi-powered by default).

    Consumes the raw graph emitted by :class:`Parser`` and returns a refined graph
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

    def search(self, query: str, k: int = 5) -> list[tuple[str, str, float]]:
        """Return up to k (doc_id, text, score) triples for the given query."""
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

    def get_file_cache(self, sha256: str) -> FileCacheEntry | None:
        """Return cached AST/call-graph payload for a file content SHA-256.

        Content-addressed lookup (ADR-0008): identical bytes in different
        repos or paths share a single cache row. Returns ``None`` on miss.
        """
        ...

    def save_file_cache(self, entry: FileCacheEntry) -> None:
        """Persist file-level analysis payload keyed by its content SHA-256."""
        ...

    def get_bm25_index(
        self, repo_abs: Path, commit: str, fingerprint: str
    ) -> Bm25IndexEntry | None:
        """Return the cached BM25 index for ``(repo_abs, commit, fingerprint)`` or ``None``.

        Implementations must also check ``rank_bm25.__version__`` against the
        stored ``bm25_lib_version`` and treat a mismatch as a miss — a
        library upgrade that changes the ``BM25Okapi`` class layout would
        otherwise yield an obscure unpickle error.
        """
        ...

    def save_bm25_index(self, entry: Bm25IndexEntry) -> None:
        """Persist a serialized BM25 index payload."""
        ...


@runtime_checkable
class FsBoundary(Protocol):
    """Port that validates filesystem paths stay within a designated root.

    The production adapter is
    :class:`~wiedunflow.adapters.fs_boundary.DefaultFsBoundary`.
    Tests may inject any callable object that satisfies this structural
    Protocol (including a simple lambda that always passes or always raises).

    The boundary guard is applied to all four filesystem-touching tools in the
    agent tool registry:

    * ``list_files_in_dir`` — LLM supplies a relative directory path
    * ``read_lines`` — LLM supplies a relative file path
    * ``read_tests`` — defensive; paths come from ``rglob`` within ``tests/``
    * ``grep_usages`` — defensive; paths come from ``rglob`` over Python files

    Only ``list_files_in_dir`` and ``read_lines`` accept user-controlled path
    strings; the other two are defended in depth against symlink escape.
    """

    def ensure_within_root(self, target: Path) -> Path:
        """Resolve *target* and assert it is contained within the root.

        Args:
            target: The candidate path to validate.

        Returns:
            The fully-resolved absolute ``Path``.

        Raises:
            PathOutsideRootError: When the resolved path escapes the root.
        """
        ...


@runtime_checkable
class Clock(Protocol):
    """Port for current-time injection — simplifies deterministic testing."""

    def now(self) -> datetime:
        """Return the current UTC datetime."""
        ...
