# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from codeguide.adapters.jinja_renderer import JinjaRenderer
from codeguide.adapters.pygments_highlighter import highlight_python as _highlight_python

# Runtime imports: used in constructor calls, not just annotations.
from codeguide.entities.call_graph import CallGraph
from codeguide.entities.lesson_plan import LessonPlan
from codeguide.use_cases.offline_linter import validate_offline_invariant

if TYPE_CHECKING:
    from codeguide.entities.code_symbol import CodeSymbol
    from codeguide.entities.lesson import Lesson
    from codeguide.entities.lesson_manifest import LessonManifest
    from codeguide.interfaces.ports import Cache, Clock, LLMProvider, Parser, VectorStore

logger = logging.getLogger(__name__)

_CODEGUIDE_VERSION = "0.0.1"

# Re-export so callers that import from this module can reach the helper.
highlight_python = _highlight_python


@dataclass(frozen=True)
class Providers:
    """Container for all port implementations injected into the use case."""

    llm: LLMProvider
    parser: Parser
    vector_store: VectorStore
    cache: Cache
    clock: Clock


def generate_tutorial(
    repo_path: Path,
    providers: Providers,
    output_path: Path | None = None,
) -> Path:
    """Run the 7-stage pipeline and write tutorial.html.

    Args:
        repo_path: Absolute path to the Git repository root.
        providers: Port implementations to use (stubs in S1, real in S2+).
        output_path: Destination file; defaults to cwd / 'tutorial.html'.

    Returns:
        Path to the written tutorial.html file.
    """
    if output_path is None:
        output_path = Path("tutorial.html").resolve()

    repo_name = repo_path.name

    # Stage 1 — Ingestion
    logger.info("[1/7] Ingestion — discovering source files")
    source_files = _stage_ingestion(repo_path)

    # Stage 2 — Analysis
    logger.info("[2/7] Analysis — parsing AST and resolving call graph")
    symbols, call_graph = _stage_analysis(source_files, providers.parser)

    # Stage 3 — Graph (S1: identity passthrough — PageRank in Sprint 2)
    logger.info("[3/7] Graph — ranking symbols (stub passthrough)")
    ranked_symbols = _stage_graph(symbols, call_graph)

    # Stage 4 — RAG
    logger.info("[4/7] RAG — indexing documentation")
    _stage_rag(repo_path, providers.vector_store)

    # Stage 5 — Planning
    logger.info("[5/7] Planning — generating lesson manifest")
    outline = _build_outline(ranked_symbols, call_graph)
    manifest: LessonManifest = providers.llm.plan(outline)

    # Stage 6 — Generation
    logger.info("[6/7] Generation — narrating lessons")
    lessons = _stage_generation(manifest, providers.llm)

    # Stage 7 — Build
    logger.info("[7/7] Build — rendering HTML")
    now_str = providers.clock.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    lesson_plan = LessonPlan(
        lessons=tuple(lessons),
        concepts_introduced=tuple(spec.teaches for spec in manifest.lessons),
        repo_commit_hash="deadbeef",  # S1 stub — real git integration in Sprint 2
        repo_branch="main",
    )
    html = _stage_build(lesson_plan, repo_name, now_str)
    output_path.write_text(html, encoding="utf-8")
    logger.info("Tutorial written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Private stage helpers
# ---------------------------------------------------------------------------


def _stage_ingestion(repo_path: Path) -> list[Path]:
    """Stage 1: Walk repo, discover Python source files.

    Skips hidden directories (starting with '.') and ``__pycache__`` folders.

    Args:
        repo_path: Root of the repository to walk.

    Returns:
        Sorted list of absolute paths to ``.py`` files.
    """
    return sorted(
        p
        for p in repo_path.rglob("*.py")
        if not any(part.startswith(".") for part in p.parts)
        if "__pycache__" not in p.parts
    )


def _stage_analysis(
    source_files: list[Path],
    parser: Parser,
) -> tuple[list[CodeSymbol], CallGraph]:
    """Stage 2: Parse AST, resolve call graph.

    In Sprint 1, ``StubTreeSitterParser`` ignores the path and returns fixture
    data.  The real tree-sitter adapter lands in Sprint 2.

    Args:
        source_files: Files discovered by ingestion (only the first is passed
            to the parser stub — real adapter handles all of them in S2).
        parser: Port implementation for AST extraction.

    Returns:
        2-tuple of ``(symbols, call_graph)``.
    """
    if not source_files:
        return [], CallGraph(nodes=(), edges=())
    symbols, call_graph = parser.parse(source_files[0])
    return symbols, call_graph


def _stage_graph(
    symbols: list[CodeSymbol],
    call_graph: CallGraph,
) -> list[CodeSymbol]:
    """Stage 3: Rank symbols by importance.

    Sprint 1 identity passthrough — PageRank + community detection land in
    Sprint 2.

    Args:
        symbols: Symbols from the analysis stage.
        call_graph: Call graph (unused in S1 passthrough).

    Returns:
        Symbols in their original order (unranked).
    """
    return symbols


def _stage_rag(repo_path: Path, vector_store: VectorStore) -> None:
    """Stage 4: Index documentation for RAG retrieval.

    Indexes ``README.md`` if present.  Full doc discovery (``docs/**/*.md``,
    commit messages, inline comments) lands in Sprint 3.

    Args:
        repo_path: Repository root used to locate ``README.md``.
        vector_store: Port implementation for BM25 / embedding indexing.
    """
    readme = repo_path / "README.md"
    docs: list[tuple[str, str]] = []
    if readme.exists():
        docs.append(("README.md", readme.read_text(encoding="utf-8")))
    vector_store.index(docs)


def _build_outline(symbols: list[CodeSymbol], call_graph: CallGraph) -> str:
    """Build a plain-text outline of the codebase for the planning LLM call.

    Args:
        symbols: Ranked symbol list from Stage 3.
        call_graph: Call graph from Stage 2.

    Returns:
        Multi-line string describing symbols and call edges.
    """
    lines = ["Codebase outline:", ""]
    for symbol in symbols:
        uncertainty = " [uncertain]" if symbol.is_uncertain else ""
        doc = f" — {symbol.docstring}" if symbol.docstring else ""
        lines.append(f"  {symbol.kind}: {symbol.name} (line {symbol.lineno}){uncertainty}{doc}")
    lines.append("")
    lines.append("Call edges:")
    for caller, callee in call_graph.edges:
        lines.append(f"  {caller} → {callee}")
    return "\n".join(lines)


def _stage_generation(manifest: LessonManifest, llm: LLMProvider) -> list[Lesson]:
    """Stage 6: Narrate each lesson spec sequentially.

    Accumulates ``concepts_introduced`` so every successive narration call
    receives the full list of already-taught concepts, preventing re-teaching.

    Args:
        manifest: Planning stage output with ordered ``LessonSpec`` items.
        llm: Provider used to generate the narrative for each spec.

    Returns:
        Ordered list of ``Lesson`` objects with generated narrative text.
    """
    lessons: list[Lesson] = []
    concepts_introduced: tuple[str, ...] = ()
    for spec in manifest.lessons:
        spec_json = json.dumps(
            {
                "id": spec.id,
                "title": spec.title,
                "teaches": spec.teaches,
                "code_refs": list(spec.code_refs),
            }
        )
        lesson = llm.narrate(spec_json, concepts_introduced)
        lessons.append(lesson)
        concepts_introduced = (*concepts_introduced, spec.teaches)
    return lessons


def _stage_build(lesson_plan: LessonPlan, repo_name: str, generated_at: str) -> str:
    """Stage 7: Render to self-contained HTML and validate the offline invariant.

    Args:
        lesson_plan: Fully generated plan with all lessons populated.
        repo_name: Human-readable name of the repository.
        generated_at: ISO-8601 timestamp string for the footer.

    Returns:
        Validated HTML string ready to be written to disk.

    Raises:
        OfflineLinterError: If the rendered HTML contains external network
            references that would break ``file://`` viewing.
    """
    renderer = JinjaRenderer()
    html = renderer.render(
        lesson_plan=lesson_plan,
        repo_name=repo_name,
        codeguide_version=_CODEGUIDE_VERSION,
        generated_at=generated_at,
    )
    validate_offline_invariant(html)
    return html
