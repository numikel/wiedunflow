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
from codeguide.use_cases.ingestion import ingest
from codeguide.use_cases.offline_linter import validate_offline_invariant

if TYPE_CHECKING:
    from codeguide.entities.code_symbol import CodeSymbol
    from codeguide.entities.lesson import Lesson
    from codeguide.entities.lesson_manifest import LessonManifest
    from codeguide.entities.ranked_graph import RankedGraph
    from codeguide.interfaces.ports import (
        Cache,
        Clock,
        LLMProvider,
        Parser,
        Ranker,
        Resolver,
        VectorStore,
    )

logger = logging.getLogger(__name__)

_CODEGUIDE_VERSION = "0.0.2"

# Re-export so callers that import from this module can reach the helper.
highlight_python = _highlight_python


@dataclass(frozen=True)
class Providers:
    """Container for all port implementations injected into the use case."""

    llm: LLMProvider
    parser: Parser
    resolver: Resolver
    ranker: Ranker
    vector_store: VectorStore
    cache: Cache
    clock: Clock


def generate_tutorial(
    repo_path: Path,
    providers: Providers,
    output_path: Path | None = None,
    excludes: tuple[str, ...] = (),
    includes: tuple[str, ...] = (),
    root_override: Path | None = None,
) -> Path:
    """Run the 7-stage pipeline and write tutorial.html.

    Args:
        repo_path: Absolute path to the Git repository root.
        providers: Port implementations to use (stubs in S1, real in S2+).
        output_path: Destination file; defaults to cwd / 'tutorial.html'.
        excludes: Additional gitignore-style patterns to exclude (additive
            over ``.gitignore``).  Threaded through to the ingestion stage.
        includes: Patterns to un-ignore despite ``.gitignore`` or *excludes*.
            Threaded through to the ingestion stage.
        root_override: Explicit repo root override for monorepo subtrees.
            When set, ingestion uses this path as ``repo_root``.

    Returns:
        Path to the written tutorial.html file.
    """
    if output_path is None:
        output_path = Path("tutorial.html").resolve()

    repo_name = repo_path.name

    # Stage 1 — Ingestion
    logger.info("[1/7] Ingestion — discovering source files")
    ingestion = ingest(repo_path, excludes=excludes, includes=includes, root_override=root_override)

    # Stage 2 — Analysis
    logger.info("[2/7] Analysis — parsing AST and resolving call graph")
    symbols, raw_graph = providers.parser.parse(list(ingestion.files), ingestion.repo_root)
    resolved_graph = providers.resolver.resolve(symbols, raw_graph, ingestion.repo_root)

    # Stage 3 — Graph
    logger.info("[3/7] Graph — PageRank + communities + topological sort")
    ranked = providers.ranker.rank(resolved_graph)

    # Stage 4 — RAG
    logger.info("[4/7] RAG — indexing documentation")
    _stage_rag(repo_path, providers.vector_store)

    # Stage 5 — Planning
    logger.info("[5/7] Planning — generating lesson manifest")
    outline = _build_outline(symbols, resolved_graph, ranked)
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
        repo_commit_hash=ingestion.commit_hash,
        repo_branch=ingestion.branch,
    )
    html = _stage_build(lesson_plan, repo_name, now_str)
    output_path.write_text(html, encoding="utf-8")
    logger.info("Tutorial written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Private stage helpers
# ---------------------------------------------------------------------------


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


def _build_outline(
    symbols: list[CodeSymbol],
    call_graph: CallGraph,
    ranked: RankedGraph,
) -> str:
    """Build a plain-text outline of the codebase for the planning LLM call.

    Args:
        symbols: Symbols emitted by the parser (post-resolver).
        call_graph: Resolved call graph from Stage 2.
        ranked: Output of Stage 3 — PageRank, communities, topological order.

    Returns:
        Multi-line string describing symbols (ordered topologically) and call edges.
    """
    pagerank_by_name = {rs.symbol_name: rs.pagerank_score for rs in ranked.ranked_symbols}
    community_by_name = {rs.symbol_name: rs.community_id for rs in ranked.ranked_symbols}
    by_name = {s.name: s for s in symbols}

    ordered_names = [n for n in ranked.topological_order if n in by_name]
    trailing = [s.name for s in symbols if s.name not in ordered_names]
    ordered_names.extend(trailing)

    lines = ["Codebase outline (topological order, leaves → roots):", ""]
    for name in ordered_names:
        symbol = by_name[name]
        uncertainty = " [uncertain]" if symbol.is_uncertain else ""
        dynamic = " [dynamic]" if symbol.is_dynamic_import else ""
        doc = f" — {symbol.docstring}" if symbol.docstring else ""
        score = pagerank_by_name.get(name, 0.0)
        community = community_by_name.get(name, -1)
        lines.append(
            f"  {symbol.kind}: {symbol.name} (line {symbol.lineno}, "
            f"pr={score:.3f}, community={community}){uncertainty}{dynamic}{doc}"
        )
    lines.append("")
    lines.append("Call edges:")
    for caller, callee in call_graph.edges:
        lines.append(f"  {caller} → {callee}")
    if ranked.has_cycles:
        lines.append("")
        lines.append("Cycles detected:")
        for group in ranked.cycle_groups:
            lines.append(f"  {' → '.join(group)}")
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
