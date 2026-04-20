# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from codeguide.adapters.jinja_renderer import JinjaRenderer
from codeguide.adapters.pygments_highlighter import highlight_python as _highlight_python
from codeguide.entities.lesson_manifest import ManifestMetadata
from codeguide.entities.lesson_plan import LessonPlan
from codeguide.use_cases.doc_coverage import compute_doc_coverage
from codeguide.use_cases.ingestion import ingest
from codeguide.use_cases.offline_linter import validate_offline_invariant
from codeguide.use_cases.outline_builder import build_outline
from codeguide.use_cases.plan_lesson_manifest import PlanningFatalError, plan_with_retry
from codeguide.use_cases.rag_corpus import build_and_index

if TYPE_CHECKING:
    from codeguide.entities.code_symbol import CodeSymbol
    from codeguide.entities.doc_coverage import DocCoverage
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

logger = structlog.get_logger(__name__)
_std_logger = logging.getLogger(__name__)

_CODEGUIDE_VERSION = "0.0.3"

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

    Raises:
        PlanningFatalError: When the planning stage fails after all retries.
    """
    if output_path is None:
        output_path = Path("tutorial.html").resolve()

    repo_name = repo_path.name

    # Stage 1 — Ingestion
    _std_logger.info("[1/7] Ingestion — discovering source files")
    ingestion = ingest(repo_path, excludes=excludes, includes=includes, root_override=root_override)

    # Stage 2 — Analysis
    _std_logger.info("[2/7] Analysis — parsing AST and resolving call graph")
    symbols, raw_graph = providers.parser.parse(list(ingestion.files), ingestion.repo_root)
    resolved_graph = providers.resolver.resolve(symbols, raw_graph, ingestion.repo_root)

    # Stage 3 — Graph
    _std_logger.info("[3/7] Graph — PageRank + communities + topological sort")
    ranked = providers.ranker.rank(resolved_graph)

    # Stage 4 — RAG
    _std_logger.info("[4/7] RAG — indexing documentation")
    build_and_index(repo_path, ingestion, symbols, providers.vector_store)
    doc_coverage = compute_doc_coverage(symbols)

    # Stage 5 — Planning  (renumbered in log vs. old code; stage numbering follows CLAUDE.md)
    _std_logger.info("[5/7] Planning — generating lesson manifest")
    outline = build_outline(symbols, resolved_graph, ranked)
    allowed_symbols = _collect_allowed_symbols(ranked, symbols)
    try:
        manifest: LessonManifest = plan_with_retry(providers.llm, outline, allowed_symbols)
    except PlanningFatalError as exc:
        logger.error(
            "planning_fatal",
            attempts=exc.attempts,
            last_error=exc.last_error,
        )
        raise

    # Re-attach orchestrator-side metadata — the provider-level metadata is a
    # placeholder because only the orchestrator knows the real clock, version,
    # and documentation coverage derived from the current run.
    now = providers.clock.now()
    manifest = manifest.model_copy(
        update={
            "metadata": ManifestMetadata(
                schema_version="1.0.0",
                codeguide_version=_CODEGUIDE_VERSION,
                total_lessons=len(manifest.lessons),
                generated_at=now,
                has_readme=ingestion.has_readme,
                doc_coverage=doc_coverage,
            ),
        }
    )

    # Stage 6 — Generation
    _std_logger.info("[6/7] Generation — narrating lessons")
    lessons = _stage_generation(manifest, providers.llm)

    # Stage 7 — Build
    _std_logger.info("[7/7] Build — rendering HTML")
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    lesson_plan = LessonPlan(
        lessons=tuple(lessons),
        concepts_introduced=tuple(spec.teaches for spec in manifest.lessons),
        repo_commit_hash=ingestion.commit_hash,
        repo_branch=ingestion.branch,
    )
    html = _stage_build(
        lesson_plan,
        repo_name,
        now_str,
        doc_coverage=doc_coverage,
        has_readme=ingestion.has_readme,
    )
    output_path.write_text(html, encoding="utf-8")
    _std_logger.info("Tutorial written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# Private stage helpers
# ---------------------------------------------------------------------------


def _collect_allowed_symbols(
    ranked: RankedGraph,
    symbols: list[CodeSymbol],
) -> frozenset[str]:
    """Derive the set of symbols the planner may reference.

    Excludes symbols that are:
    - Marked ``is_uncertain`` or ``is_dynamic_import`` in the AST snapshot.
    - Members of any SCC cycle group (topological order is undefined inside cycles).

    Args:
        ranked: Stage 3 output with ``ranked_symbols`` and ``cycle_groups``.
        symbols: Full symbol list from Stage 2 analysis.

    Returns:
        Frozenset of clean, groundable symbol names.
    """
    uncertain: set[str] = {s.name for s in symbols if s.is_uncertain or s.is_dynamic_import}
    cyclic: set[str] = set()
    for group in ranked.cycle_groups:
        cyclic.update(group)
    return frozenset(
        s.symbol_name
        for s in ranked.ranked_symbols
        if s.symbol_name not in uncertain and s.symbol_name not in cyclic
    )


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
        # Serialize code_refs as dicts so the narrate call is transport-agnostic.
        spec_json = json.dumps(
            {
                "id": spec.id,
                "title": spec.title,
                "teaches": spec.teaches,
                "code_refs": [
                    {
                        "file_path": str(ref.file_path),
                        "symbol": ref.symbol,
                        "line_start": ref.line_start,
                        "line_end": ref.line_end,
                        "role": ref.role,
                    }
                    for ref in spec.code_refs
                ],
            }
        )
        lesson = llm.narrate(spec_json, concepts_introduced)
        lessons.append(lesson)
        concepts_introduced = (*concepts_introduced, spec.teaches)
    return lessons


def _stage_build(
    lesson_plan: LessonPlan,
    repo_name: str,
    generated_at: str,
    *,
    doc_coverage: DocCoverage | None = None,
    has_readme: bool = True,
) -> str:
    """Stage 7: Render to self-contained HTML and validate the offline invariant.

    Args:
        lesson_plan: Fully generated plan with all lessons populated.
        repo_name: Human-readable name of the repository.
        generated_at: ISO-8601 timestamp string for the footer.
        doc_coverage: Documentation coverage metrics; triggers warning banner
            when ``doc_coverage.is_low`` is ``True``.
        has_readme: Whether the repository has a README; drives an info banner.

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
        doc_coverage=doc_coverage,
        has_readme=has_readme,
    )
    validate_offline_invariant(html)
    return html
