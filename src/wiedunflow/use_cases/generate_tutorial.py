# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel, ConfigDict

from wiedunflow import __version__ as _wiedunflow_version
from wiedunflow.adapters.jinja_renderer import JinjaRenderer, _markdown_to_html
from wiedunflow.adapters.pygments_highlighter import highlight_python as _highlight_python
from wiedunflow.cli.cost_estimator import CostEstimate
from wiedunflow.cli.cost_estimator import estimate as _estimate_cost
from wiedunflow.cli.editor_resolver import open_in_editor as _open_in_editor
from wiedunflow.cli.stage_reporter import NoOpReporter, StageReporter
from wiedunflow.entities.lesson import HelperAppendixEntry, Lesson
from wiedunflow.entities.lesson_manifest import (
    LessonManifest,
    LessonSpec,
    ManifestMetadata,
)
from wiedunflow.entities.lesson_plan import LessonPlan
from wiedunflow.entities.skipped_lesson import SkippedLesson
from wiedunflow.use_cases.agent_orchestrator import run_closing_lesson, run_lesson
from wiedunflow.use_cases.agent_tools import build_tool_registry
from wiedunflow.use_cases.doc_coverage import compute_doc_coverage
from wiedunflow.use_cases.entry_point_detector import detect_entry_points
from wiedunflow.use_cases.ingestion import ingest
from wiedunflow.use_cases.inject_source_excerpts import inject_source_excerpts
from wiedunflow.use_cases.offline_linter import validate_offline_invariant
from wiedunflow.use_cases.outline_builder import build_outline
from wiedunflow.use_cases.plan_lesson_manifest import PlanningFatalError, plan_with_retry
from wiedunflow.use_cases.rag_corpus import build_and_index
from wiedunflow.use_cases.readme_excerpt import load_readme_excerpt
from wiedunflow.use_cases.skip_trivial import filter_trivial_helpers
from wiedunflow.use_cases.workspace import allocate_workspace, clean_old_runs, generate_run_id

# v0.3.0 Fix (P0 from rubber-duck code review): markdown→HTML for the
# standalone Project README lesson reuses jinja_renderer._markdown_to_html so
# external README links pass the Stage 7 offline-linter (the renderer's
# OfflineHTMLRenderer strips href attributes; the prior plain renderer left
# `<a href="https://...">` tags in `code_panel_html` and crashed every run on
# any real repo with external links in the README).

if TYPE_CHECKING:
    from wiedunflow.entities.call_graph import CallGraph
    from wiedunflow.entities.code_symbol import CodeSymbol
    from wiedunflow.entities.doc_coverage import DocCoverage
    from wiedunflow.entities.ranked_graph import RankedGraph
    from wiedunflow.interfaces.ports import (
        Cache,
        Clock,
        LLMProvider,
        Parser,
        Ranker,
        Resolver,
        SpendMeterProto,
        VectorStore,
    )

logger = structlog.get_logger(__name__)
_std_logger = logging.getLogger(__name__)

# Default lesson cap (US-035).  Track C (config.py) owns the configurable field;
# we fall back to this constant when ``config`` is not available or doesn't have
# ``tutorial.max_lessons``.
_DEFAULT_MAX_LESSONS = 30

# DEGRADED threshold (US-032 AC1): strict >.
_DEGRADED_THRESHOLD = 0.30

# Number of top-ranked uncovered symbols to surface in the closing lesson (US-049).
_CLOSING_OMITTED_SYMBOLS_COUNT = 5

# Re-export so callers that import from this module can reach the helper.
highlight_python = _highlight_python


class MaxCostExceededError(RuntimeError):
    """Raised by the cost-gate pre-flight check when the estimate exceeds ``--max-cost``.

    US-019: the CLI translates this into a structured run-report with ``status="failed"``
    and an exit code of 1 without making any narration calls.
    """

    def __init__(self, estimate_usd: float, cap_usd: float, lessons: int) -> None:
        super().__init__(
            f"Estimated cost ${estimate_usd:.2f} exceeds --max-cost cap ${cap_usd:.2f} "
            f"for {lessons} lessons"
        )
        self.estimate_usd = estimate_usd
        self.cap_usd = cap_usd
        self.lessons = lessons


class CostGateAbortedError(RuntimeError):
    """Raised when the user declines the interactive cost-gate prompt (US-084 — Sprint 8).

    Distinguished from :class:`MaxCostExceededError` because this is a clean
    user abort (exit code 0), not a failure (exit code 1). The CLI prints
    the spec-mandated abort message and writes a ``status="ok"`` run-report
    with zero cost.
    """

    def __init__(self, estimate_usd: float, lessons: int) -> None:
        super().__init__(
            f"User declined cost-gate prompt: estimate ${estimate_usd:.2f} for {lessons} lessons"
        )
        self.estimate_usd = estimate_usd
        self.lessons = lessons


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


class GenerationResult(BaseModel):
    """Result of the generation stage (Stage 6) returned alongside the HTML path.

    Carries run-level statistics needed by the CLI (exit code, DEGRADED banner)
    and by the renderer (skipped count, degraded flag).  This is **not** a full
    RunReport — Cross-cutting track will add the full ``run-report.json`` later.

    Attributes:
        output_path: Path to the written ``tutorial.html`` file.
        skipped_lessons: Ordered list of ``SkippedLesson`` placeholders (US-031).
        degraded: ``True`` when ``skipped_count / planned_lessons > 0.30`` (US-032).
        degraded_ratio: Exact ratio for the DEGRADED banner text.
        total_planned: Number of regular (non-closing) lessons planned.
        retry_count: Number of lessons that required a grounding retry (AC2 US-030).
        total_cost_usd: Cumulative LLM spend for the generation stage in USD.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    output_path: Path
    skipped_lessons: tuple[SkippedLesson, ...]
    degraded: bool
    degraded_ratio: float
    total_planned: int
    retry_count: int
    hallucinated_symbols: tuple[str, ...] = ()
    total_cost_usd: float = 0.0


@dataclass
class _StageGenerationOutput:
    """Typed output of the :func:`_stage_generation` helper."""

    lessons: list[Lesson] = field(default_factory=list)
    skipped: list[SkippedLesson] = field(default_factory=list)
    retry_count: int = 0
    concepts_introduced: tuple[str, ...] = ()
    hallucinated_symbols: list[str] = field(default_factory=list)
    total_cost_usd: float = 0.0


def generate_tutorial(  # noqa: PLR0915, PLR0912 — 7-stage orchestrator is naturally long
    repo_path: Path,
    providers: Providers,
    output_path: Path | None = None,
    excludes: tuple[str, ...] = (),
    includes: tuple[str, ...] = (),
    root_override: Path | None = None,
    max_lessons: int = _DEFAULT_MAX_LESSONS,
    should_abort: Callable[[], bool] | None = None,
    dry_run: bool = False,
    review_plan: bool = False,
    max_cost_usd: float | None = None,
    progress: StageReporter | NoOpReporter | None = None,
    cost_gate_callback: Callable[[CostEstimate], bool] | None = None,
    # v0.2.1 quality controls (passed through from WiedunflowConfig):
    planning_entry_point_first: str = "auto",
    planning_skip_trivial_helpers: bool = False,
    narration_min_words_trivial: int = 50,
    narration_snippet_validation: bool = True,
    # ADR-0013 follow-up: pricing catalog for cost gate accuracy.
    pricing_catalog: object | None = None,
    # v0.9.0 cost reporting wire-through.
    spend_meter: SpendMeterProto | None = None,
) -> GenerationResult:
    """Run the 7-stage pipeline and write the tutorial HTML.

    Args:
        repo_path: Absolute path to the Git repository root.
        providers: Port implementations to use (stubs in S1, real in S2+).
        output_path: Destination file; defaults to ``cwd / wiedunflow-<repo>.html``
            (the repo directory name is used as the slug).
        excludes: Additional gitignore-style patterns to exclude (additive
            over ``.gitignore``).  Threaded through to the ingestion stage.
        includes: Patterns to un-ignore despite ``.gitignore`` or *excludes*.
            Threaded through to the ingestion stage.
        root_override: Explicit repo root override for monorepo subtrees.
            When set, ingestion uses this path as ``repo_root``.
        max_lessons: Hard cap on planned lessons (US-035).  Defaults to 30.
            Track C (config.py) passes the user-configured value here.
        should_abort: Optional predicate polled between stages; when it
            returns ``True`` the pipeline raises :class:`KeyboardInterrupt`
            after flushing the current state (US-027 graceful SIGINT).
        progress: Optional :class:`StageReporter` (or :class:`NoOpReporter`)
            that receives stage lifecycle events for animated CLI output
            (Sprint 8 / v0.2.0). Defaults to a :class:`NoOpReporter` when
            ``None`` so headless callers (tests, ``--log-format=json``)
            need not pass anything.
        cost_gate_callback: Optional predicate invoked after Stage 5
            (Planning) with the cost estimate. Returning ``False`` raises
            :class:`CostGateAbortedError` (clean abort, exit 0). When
            ``None`` the cost-gate prompt is skipped entirely (back-compat
            with v0.1.0 behaviour where ``--max-cost`` was the only gate).

    Returns:
        :class:`GenerationResult` carrying the output path, DEGRADED flag,
        retry count, and skipped-lesson markers — the CLI uses this to build
        the ``RunReport``.

    Raises:
        PlanningFatalError: When the planning stage fails after all retries.
        MaxCostExceededError: When the cost estimate exceeds ``--max-cost``.
        CostGateAbortedError: When the user declines the interactive cost-gate
            prompt (Sprint 8 / US-084).
        KeyboardInterrupt: When ``should_abort`` returns ``True`` between
            stages (graceful SIGINT — US-027).
    """
    repo_name = repo_path.name

    if output_path is None:
        output_path = Path(f"wiedunflow-{repo_name}.html").resolve()

    if progress is None:
        progress = NoOpReporter()

    def _check_abort() -> None:
        if should_abort is not None and should_abort():
            raise KeyboardInterrupt("SIGINT received — aborting generation")

    # Stage 1 — Ingestion
    progress.stage_start(1)
    logger.info("stage_start", stage=1, name="Ingestion")
    ingestion = ingest(repo_path, excludes=excludes, includes=includes, root_override=root_override)
    progress.stage_done(f"{len(ingestion.files)} python files discovered")
    _check_abort()

    # Stage 2 — Analysis
    # Use ``detail`` rather than ``progress_line`` because tree-sitter + Jedi
    # parse the whole batch in one shot — there is no per-file callback to
    # drive a replace-line region. A static line avoids ``rich.live`` rerendering
    # when structlog warnings (e.g., low_jedi_resolution) are interleaved.
    progress.stage_start(2)
    logger.info("stage_start", stage=2, name="Analysis")
    progress.detail(f"parsing AST + resolving call graph for {len(ingestion.files)} files")
    symbols, raw_graph = providers.parser.parse(list(ingestion.files), ingestion.repo_root)
    resolved_graph = providers.resolver.resolve(symbols, raw_graph, ingestion.repo_root)
    progress.stage_done(f"{len(symbols)} symbols · {len(raw_graph.edges)} call edges")

    # Stage 3 — Graph
    progress.stage_start(3)
    logger.info("stage_start", stage=3, name="Graph")
    ranked = providers.ranker.rank(resolved_graph)
    progress.stage_done(
        f"{len(ranked.ranked_symbols)} symbols ranked · {len(ranked.cycle_groups)} cycle groups"
    )

    # Stage 4 — RAG
    progress.stage_start(4)
    logger.info("stage_start", stage=4, name="RAG")
    build_and_index(repo_path, ingestion, symbols, providers.vector_store)
    doc_coverage = compute_doc_coverage(symbols)
    progress.stage_done(f"BM25 index built · doc coverage {doc_coverage.ratio * 100:.0f}%")

    # Stage 5 — Planning  (renumbered in log vs. old code; stage numbering follows CLAUDE.md)
    progress.stage_start(5)
    logger.info("stage_start", stage=5, name="Planning")
    progress.detail("generating lesson manifest…")
    outline = build_outline(symbols, resolved_graph, ranked)
    allowed_symbols = _collect_allowed_symbols(ranked, symbols)

    # Detect entry points for happy-path ordering (v0.2.1).
    # ingestion.files are absolute paths — relativise before passing to detector.
    _ep_file_paths: tuple[Path, ...] = tuple(
        p.relative_to(ingestion.repo_root) if p.is_absolute() else p for p in ingestion.files
    )
    entry_points = detect_entry_points(ingestion.repo_root, _ep_file_paths)
    logger.debug("entry_points_detected", count=len(entry_points), symbols=sorted(entry_points))

    try:
        manifest: LessonManifest = plan_with_retry(
            providers.llm,
            outline,
            allowed_symbols,
            entry_points=entry_points,
            entry_point_mode=planning_entry_point_first,  # type: ignore[arg-type]
        )
    except PlanningFatalError as exc:
        logger.error(
            "planning_fatal",
            attempts=exc.attempts,
            last_error=exc.last_error,
        )
        raise
    progress.stage_done(f"manifest ready ({len(manifest.lessons)} lessons)")

    # Post-planning: inject source excerpts for anti-hallucination (v0.2.1 A2).
    manifest = inject_source_excerpts(manifest, ingestion.repo_root)
    logger.debug("source_excerpts_injected")

    # Re-attach orchestrator-side metadata — the provider-level metadata is a
    # placeholder because only the orchestrator knows the real clock, version,
    # and documentation coverage derived from the current run.
    now = providers.clock.now()
    manifest = manifest.model_copy(
        update={
            "metadata": ManifestMetadata(
                schema_version="1.0.0",
                wiedunflow_version=_wiedunflow_version,
                total_lessons=len(manifest.lessons),
                generated_at=now,
                has_readme=ingestion.has_readme,
                doc_coverage=doc_coverage,
            ),
        }
    )

    # --max-cost pre-flight (US-019 — Sprint 5 follow-up): short-circuit before any
    # Stage 5/6 LLM call if the heuristic estimate exceeds the user-supplied cap.
    # Sprint 8 (US-084): also short-circuit if the user declines the interactive
    # cost-gate prompt. Both checks share the same heuristic estimate.
    pre_narration_estimate: CostEstimate | None = None
    if max_cost_usd is not None or cost_gate_callback is not None:
        plan_model = getattr(providers.llm, "model_plan", None)
        narrate_model = getattr(providers.llm, "model_narrate", None)
        pre_narration_estimate = _estimate_cost(
            symbols=len(symbols),
            lessons=len(manifest.lessons),
            clusters=1,
            plan_model=plan_model,
            narrate_model=narrate_model,
            pricing_catalog=pricing_catalog,  # type: ignore[arg-type]
        )

    if (
        max_cost_usd is not None
        and pre_narration_estimate is not None
        and pre_narration_estimate.total_cost_usd > max_cost_usd
    ):
        logger.error(
            "max_cost_exceeded",
            estimate_usd=pre_narration_estimate.total_cost_usd,
            cap_usd=max_cost_usd,
            lessons=len(manifest.lessons),
        )
        raise MaxCostExceededError(
            estimate_usd=pre_narration_estimate.total_cost_usd,
            cap_usd=max_cost_usd,
            lessons=len(manifest.lessons),
        )

    # Sprint 8 (US-084): interactive cost-gate prompt. Skipped when the callback
    # already short-circuits via bypass conditions (--yes / --no-cost-prompt /
    # non-TTY), or when no callback was supplied (back-compat with v0.1.0).
    if (
        cost_gate_callback is not None
        and pre_narration_estimate is not None
        and not dry_run  # dry-run never reaches narration, no need to prompt
        and not cost_gate_callback(pre_narration_estimate)
    ):
        logger.info(
            "cost_gate_user_declined",
            estimate_usd=pre_narration_estimate.total_cost_usd,
            lessons=len(manifest.lessons),
        )
        raise CostGateAbortedError(
            estimate_usd=pre_narration_estimate.total_cost_usd,
            lessons=len(manifest.lessons),
        )

    # --review-plan (US-016): write the manifest to .wiedunflow/manifest.json and
    # open it in the resolved editor.  On save, re-validate; an invalid manifest
    # falls back to the original planner output.
    if review_plan:
        manifest = _review_plan_interactive(manifest, repo_path)

    # --dry-run (US-015): short-circuit Stage 5 and 6, render a preview HTML where
    # every lesson carries a placeholder narrative but full metadata (title,
    # code_refs) so the user can audit the plan without paying for narration.
    if dry_run:
        preview_lessons = _build_preview_lessons(manifest)
        lesson_plan = LessonPlan(
            lessons=tuple(preview_lessons),
            concepts_introduced=(),
            repo_commit_hash=ingestion.commit_hash,
            repo_branch=ingestion.branch,
        )
        now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        html = _stage_build(
            lesson_plan,
            repo_name,
            now_str,
            doc_coverage=doc_coverage,
            has_readme=ingestion.has_readme,
            skipped_lessons=[],
            degraded=False,
            total_planned=len(preview_lessons),
            symbols=symbols,
            repo_root=repo_path,
        )
        preview_output = output_path
        if preview_output.name == "tutorial.html":
            preview_output = preview_output.with_name("tutorial-preview.html")
        _write_html_output(preview_output, html)
        _std_logger.info("[dry-run] Preview written to %s", preview_output)
        return GenerationResult(
            output_path=preview_output,
            skipped_lessons=(),
            degraded=False,
            degraded_ratio=0.0,
            total_planned=len(preview_lessons),
            retry_count=0,
        )

    # US-035: assert the manifest respects the lesson cap.  The planning LLM is
    # instructed by Track C (config.py / planning prompt) to cap at max_lessons.
    # Here we surface a warning but do not hard-fail — partial tutorials are
    # preferable to a crash (DEGRADED handles the quality signal instead).
    if len(manifest.lessons) > max_lessons:
        _std_logger.warning(
            "[6/7] Generation — manifest has %d lessons, cap is %d; truncating",
            len(manifest.lessons),
            max_lessons,
        )
        # Truncate: keep the first max_lessons specs (planner should have ordered
        # by importance / topological order already).
        truncated_lessons = manifest.lessons[:max_lessons]
        truncated_metadata = manifest.metadata.model_copy(
            update={"total_lessons": len(truncated_lessons)}
        )
        manifest = manifest.model_copy(
            update={"lessons": truncated_lessons, "metadata": truncated_metadata}
        )

    # Post-planning: filter trivial helpers (v0.2.1 A6).
    manifest, helper_appendix_refs = filter_trivial_helpers(
        manifest,
        ranked,
        entry_points,
        enabled=planning_skip_trivial_helpers,
    )
    if helper_appendix_refs:
        logger.info(
            "trivial_helpers_filtered",
            removed=len(helper_appendix_refs),
            remaining_lessons=len(manifest.lessons),
        )

    _check_abort()

    # v0.2.1 — load README excerpt for project-level context injection.
    # Kept for API back-compat; BM25 index already covers README content so
    # the multi-agent pipeline's search_docs tool surfaces it implicitly.
    readme_excerpt = load_readme_excerpt(repo_path) if ingestion.has_readme else None

    # Allocate a stable run_id for workspace / resume support.
    _run_id = generate_run_id(
        str(ingestion.repo_root),
        ingestion.commit_hash or "unknown",
        now.isoformat(),
    )
    # Clean up stale runs from previous invocations (lazy, one-shot).
    clean_old_runs()

    # Stage 6 — Generation
    progress.stage_start(6)
    logger.info("stage_start", stage=6, name="Generation")
    generation_result = _stage_generation(
        manifest,
        providers.llm,
        allowed_symbols,
        ingestion=ingestion,
        repo_path=repo_path,
        ranked=ranked,
        workspace_run_id=_run_id,
        symbols=symbols,
        graph=resolved_graph,
        vector_store=providers.vector_store,
        should_abort=should_abort,
        progress=progress,
        narration_min_words_trivial=narration_min_words_trivial,
        narration_snippet_validation=narration_snippet_validation,
        project_context=readme_excerpt,
        spend_meter=spend_meter,
    )
    all_lessons: list[Lesson] = generation_result.lessons
    skipped_lessons: list[SkippedLesson] = generation_result.skipped
    # retry_count is logged by grounding_retry; future RunReport will expose it via Cross-cutting.
    concepts_introduced: tuple[str, ...] = generation_result.concepts_introduced

    # v0.3.0 — single closing-lesson decoration pass: attach helper appendix
    # (Fix A6 from v0.2.1) and switch to single-column layout in one
    # ``model_copy`` so we lookup the closing index once.
    if all_lessons:
        closing_idx = next(
            (i for i, lsn in enumerate(all_lessons) if lsn.id == "lesson-closing"),
            len(all_lessons) - 1,
        )
        closing_updates: dict[str, object] = {"layout": "single"}
        if helper_appendix_refs:
            closing_updates["helper_appendix"] = tuple(
                HelperAppendixEntry(
                    symbol=ref.symbol,
                    file_path=str(ref.file_path),
                    line_start=ref.line_start,
                    line_end=ref.line_end,
                )
                for ref in helper_appendix_refs
            )
        all_lessons[closing_idx] = all_lessons[closing_idx].model_copy(update=closing_updates)

    # v0.3.0 — append a standalone "Project README" lesson as the final TOC
    # entry when the repo ships one. The narration column hosts a thin
    # pointer ("Project README — read on the right →") while the right code
    # pane is replaced with the rendered README HTML, treating it as
    # reference reading rather than a primary lesson.
    if readme_excerpt:
        rendered_readme = _markdown_to_html(readme_excerpt)
        readme_html = (
            rendered_readme.strip() if isinstance(rendered_readme, str) else readme_excerpt
        )
        readme_lesson = Lesson(
            id="lesson-readme",
            title="Project README",
            narrative=(
                "## Project README\n\n"
                "The repository's README is rendered in the panel on the right — "
                "browse it for project-level context, install instructions, and any "
                "pointers the maintainers left behind."
            ),
            code_refs=(),
            code_panel_html=readme_html,
            status="generated",
            confidence="HIGH",
        )
        all_lessons.append(readme_lesson)

    # A8 bug fix: synchronise manifest.metadata.total_lessons with the ACTUAL
    # lesson count after generation (which is manifest.lessons + 1 closing lesson).
    # Before this fix, total_lessons was set to len(manifest.lessons) which
    # excluded the closing lesson, causing the footer to show N-1 instead of N.
    actual_total = len(all_lessons)
    if manifest.metadata.total_lessons != actual_total:
        _old_total = manifest.metadata.total_lessons
        manifest = manifest.model_copy(
            update={
                "metadata": manifest.metadata.model_copy(update={"total_lessons": actual_total})
            }
        )
        logger.debug(
            "total_lessons_synced",
            old=_old_total,
            new=actual_total,
        )

    # DEGRADED calculation (US-032).  Denominator = regular planned lessons only
    # (closing lesson excluded per spec decision).
    total_planned = len(manifest.lessons)
    skipped_count = len(skipped_lessons)
    degraded_ratio = skipped_count / total_planned if total_planned > 0 else 0.0
    degraded = degraded_ratio > _DEGRADED_THRESHOLD

    if degraded:
        _std_logger.warning(
            "Tutorial DEGRADED: %d of %d lessons skipped (ratio=%.2f)",
            skipped_count,
            total_planned,
            degraded_ratio,
        )

    progress.stage_done(
        f"{len(all_lessons)} lessons narrated"
        + (f" · {skipped_count} skipped" if skipped_count else "")
    )

    # Stage 7 — Build
    progress.stage_start(7)
    logger.info("stage_start", stage=7, name="Build")
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    lesson_plan = LessonPlan(
        lessons=tuple(all_lessons),
        concepts_introduced=tuple(concepts_introduced),
        repo_commit_hash=ingestion.commit_hash,
        repo_branch=ingestion.branch,
    )
    html = _stage_build(
        lesson_plan,
        repo_name,
        now_str,
        doc_coverage=doc_coverage,
        has_readme=ingestion.has_readme,
        skipped_lessons=skipped_lessons,
        degraded=degraded,
        total_planned=total_planned,
        symbols=symbols,
        repo_root=repo_path,
    )
    _write_html_output(output_path, html)
    progress.stage_done(f"tutorial.html written · {output_path.stat().st_size // 1024} KB")
    _std_logger.info("Tutorial written to %s", output_path)
    # Deduplicate and sort hallucinated symbols for deterministic output.
    deduped_hallucinations = tuple(sorted(set(generation_result.hallucinated_symbols)))
    return GenerationResult(
        output_path=output_path,
        skipped_lessons=tuple(skipped_lessons),
        degraded=degraded,
        degraded_ratio=degraded_ratio,
        total_planned=total_planned,
        retry_count=generation_result.retry_count,
        hallucinated_symbols=deduped_hallucinations,
        total_cost_usd=generation_result.total_cost_usd,
    )


# ---------------------------------------------------------------------------
# Private stage helpers
# ---------------------------------------------------------------------------


def _write_html_output(output_path: Path, html: str) -> None:
    """Write rendered HTML, creating the configured output directory if needed."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")


def _build_preview_lessons(manifest: LessonManifest) -> list[Lesson]:
    """Translate LessonSpecs into placeholder ``Lesson`` entities for --dry-run (US-015).

    Narration carries a short ``[preview]`` marker so validators pass; the actual
    Opus call is skipped entirely. Title + code_refs are preserved so the reader
    can audit the plan.
    """
    preview: list[Lesson] = []
    for spec in manifest.lessons:
        code_ref_names = tuple(ref.symbol for ref in spec.code_refs)
        preview.append(
            Lesson(
                id=spec.id,
                title=spec.title,
                narrative=(
                    f"[preview] This lesson will be generated during a full run "
                    f"(teaches: {spec.teaches})."
                ),
                code_refs=code_ref_names,
                status="generated",
            )
        )
    return preview


def _review_plan_interactive(manifest: LessonManifest, repo_path: Path) -> LessonManifest:
    """Open the manifest in ``$EDITOR`` for manual review (US-016).

    Writes ``<repo>/.wiedunflow/manifest.edited.json`` so edits survive across
    runs and can be diffed. On save, the file is validated back into a
    ``LessonManifest``; an invalid edit falls back to the original with a
    structured warning so the run continues rather than hard-failing.
    """
    edit_dir = repo_path / ".wiedunflow"
    edit_dir.mkdir(parents=True, exist_ok=True)
    edit_path = edit_dir / "manifest.edited.json"
    edit_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    rc = _open_in_editor(edit_path)
    if rc != 0:
        logger.warning("review_plan_editor_nonzero_exit", rc=rc)

    try:
        return LessonManifest.model_validate_json(edit_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "review_plan_validation_failed",
            error=str(exc),
            msg="edited manifest rejected; falling back to original planner output",
        )
        return manifest


def _collect_allowed_symbols(
    ranked: RankedGraph,
    symbols: list[CodeSymbol],
) -> frozenset[str]:
    """Derive the set of symbols the planner may reference.

    Excludes symbols that are:
    - Marked ``is_uncertain`` in the AST snapshot (importlib/``__import__`` in source).

    Cyclic symbols are intentionally NOT excluded: the grounding invariant checks
    symbol *existence* (ADR-0007), not lesson ordering.  Excluding cycles caused
    false-negative grounding failures when the LLM legitimately referenced a symbol
    that lives in a call cycle (e.g. dateutil.parser._parser.parse).

    Args:
        ranked: Stage 3 output with ``ranked_symbols`` and ``cycle_groups``.
        symbols: Full symbol list from Stage 2 analysis.

    Returns:
        Frozenset of clean, groundable symbol names.
    """
    # Only exclude symbols whose resolution is genuinely uncertain (importlib/
    # __import__ in source file).  is_dynamic_import alone (set for getattr
    # usage) no longer implies ungroundable — see detect_strict_uncertainty.
    uncertain: set[str] = {s.name for s in symbols if s.is_uncertain}
    return frozenset(s.symbol_name for s in ranked.ranked_symbols if s.symbol_name not in uncertain)


def _build_closing_spec(
    manifest: LessonManifest,
    ingestion: object,
    repo_path: Path,
    ranked: RankedGraph,
) -> LessonSpec:
    """Construct the synthetic closing lesson spec (US-049).

    The closing lesson is a +1 beyond the regular cap.  It instructs the LLM
    to write a "Where to go next" section referencing:
    - README links (when ``ingestion.has_readme`` is ``True``).
    - Top 5 highest-ranked symbols *not* already covered by earlier lessons.
    - Git log hints about actively changing subdirectories (approximated from
      ingestion metadata when available).

    Args:
        manifest: The finalised lesson manifest (all regular lessons).
        ingestion: Ingestion result (duck-typed to avoid circular import).
        repo_path: Path to the repository root.
        ranked: Stage 3 ranked graph for picking omitted high-rank symbols.

    Returns:
        A :class:`~wiedunflow.entities.lesson_manifest.LessonSpec` with
        ``is_closing=True`` and no ``code_refs`` (closing lesson is not
        grounded in specific symbols).
    """
    # Symbols already covered in the manifest.
    covered: set[str] = set()
    for spec in manifest.lessons:
        for ref in spec.code_refs:
            covered.add(ref.symbol)

    # Top N high-ranked symbols not in covered.
    omitted: list[str] = []
    for rs in ranked.ranked_symbols:
        if rs.symbol_name not in covered:
            omitted.append(rs.symbol_name)
        if len(omitted) >= _CLOSING_OMITTED_SYMBOLS_COUNT:
            break

    has_readme = getattr(ingestion, "has_readme", False)
    readme_hint = " Consult the README for project-level documentation." if has_readme else ""
    omitted_hint = f" Notable uncovered symbols: {', '.join(omitted)}." if omitted else ""

    teaches = "Where to go next: external resources, uncovered symbols, and contribution hints."
    full_teaches = f"{teaches}{readme_hint}{omitted_hint}"

    return LessonSpec(
        id="lesson-closing",
        title="Where to go next",
        teaches=full_teaches,
        prerequisites=tuple(spec.id for spec in manifest.lessons),
        code_refs=(),
        is_closing=True,
    )


def _stage_generation(
    manifest: LessonManifest,
    llm: LLMProvider,
    allowed_symbols: frozenset[str],
    *,
    ingestion: object,
    repo_path: Path,
    ranked: RankedGraph,
    workspace_run_id: str,
    symbols: list[CodeSymbol],
    graph: CallGraph,
    vector_store: VectorStore,
    should_abort: Callable[[], bool] | None = None,
    progress: StageReporter | NoOpReporter | None = None,
    narration_min_words_trivial: int = 50,
    narration_snippet_validation: bool = True,
    project_context: str | None = None,
    spend_meter: SpendMeterProto | None = None,
) -> _StageGenerationOutput:
    """Stage 6: Narrate each lesson via the multi-agent pipeline.

    Each regular lesson runs Orchestrator -> Researcher x N -> Writer -> Reviewer.
    The closing lesson uses a lightweight single-Writer pass.
    ``concepts_introduced`` accumulates from successful lessons only.

    Args:
        manifest: Planning stage output with ordered ``LessonSpec`` items.
        llm: LLM provider implementing ``run_agent``.
        allowed_symbols: Frozenset of groundable symbol names (Stage 3 output).
        ingestion: Ingestion result used to build the closing lesson spec.
        repo_path: Repo root path (passed through to closing spec builder).
        ranked: RankedGraph used to find uncovered high-rank symbols.
        workspace_run_id: Unique run ID for the workspace (used to resume).
        symbols: All symbols from Stage 2 — fed into tool_registry.
        graph: Resolved call graph from Stage 2 — fed into tool_registry.
        vector_store: Indexed vector store from Stage 4 — fed into tool_registry.
        narration_min_words_trivial: Kept for API back-compat; not used in v0.9.0+.
        narration_snippet_validation: Kept for API back-compat; not used in v0.9.0+.
        project_context: Kept for API back-compat; not used in v0.9.0+.

    Returns:
        :class:`_StageGenerationOutput` with typed fields for lessons, skipped,
        retry_count, and cumulative concepts_introduced.
    """
    workspace = allocate_workspace(workspace_run_id)
    tool_registry = build_tool_registry(
        symbols=symbols,
        graph=graph,
        vector_store=vector_store,
        repo_root=repo_path,
    )

    output = _StageGenerationOutput()

    if progress is None:
        progress = NoOpReporter()

    total_lessons = len(manifest.lessons)
    for idx, spec in enumerate(manifest.lessons, start=1):
        if should_abort is not None and should_abort():
            raise KeyboardInterrupt("SIGINT received during generation stage")
        progress.lesson_event(idx, total_lessons, spec.title)
        result = run_lesson(
            spec,
            workspace=workspace,
            llm=llm,
            tool_registry=tool_registry,
            concepts_introduced=output.concepts_introduced,
            spend_meter=spend_meter,
        )

        if isinstance(result, SkippedLesson):
            output.skipped.append(result)
            placeholder = Lesson(
                id=result.lesson_id,
                title=result.title,
                narrative=(
                    f"This lesson was skipped — "
                    f"see symbol {result.missing_symbols[0] if result.missing_symbols else 'unknown'} "
                    f"in the code"
                ),
                code_refs=result.missing_symbols,
                status="skipped",
            )
            output.lessons.append(placeholder)
        else:
            output.lessons.append(result)
            output.concepts_introduced = (*output.concepts_introduced, spec.teaches)

    # --- Closing lesson (US-049) — always +1 beyond cap ---
    closing_spec = _build_closing_spec(manifest, ingestion, repo_path, ranked)
    closing_result = run_closing_lesson(
        closing_spec,
        workspace=workspace,
        llm=llm,
        concepts_introduced=output.concepts_introduced,
        spend_meter=spend_meter,
    )
    if isinstance(closing_result, SkippedLesson):
        closing_placeholder = Lesson(
            id=closing_result.lesson_id,
            title=closing_result.title,
            narrative=(
                "This lesson was skipped due to generation failures. "
                "See the repository README for further reading."
            ),
            code_refs=(),
            status="skipped",
        )
        output.lessons.append(closing_placeholder)
    else:
        output.lessons.append(closing_result)

    # Wire cumulative spend from the meter (if present) into the stage output.
    if spend_meter is not None:
        output.total_cost_usd = getattr(spend_meter, "total_cost_usd", 0.0)

    return output


def _stage_build(
    lesson_plan: LessonPlan,
    repo_name: str,
    generated_at: str,
    *,
    doc_coverage: DocCoverage | None = None,
    has_readme: bool = True,
    skipped_lessons: list[SkippedLesson] | None = None,
    degraded: bool = False,
    total_planned: int = 0,
    symbols: list[CodeSymbol] | None = None,
    repo_root: Path | None = None,
) -> str:
    """Stage 7: Render to self-contained HTML and validate the offline invariant.

    Args:
        lesson_plan: Fully generated plan with all lessons populated.
        repo_name: Human-readable name of the repository.
        generated_at: ISO-8601 timestamp string for the footer.
        doc_coverage: Documentation coverage metrics; triggers warning banner
            when ``doc_coverage.is_low`` is ``True``.
        has_readme: Whether the repository has a README; drives an info banner.
        skipped_lessons: List of ``SkippedLesson`` markers for the run report.
        degraded: When ``True``, renders the DEGRADED banner in the HTML.
        total_planned: Total number of regular planned lessons (for banner text).

    Returns:
        Validated HTML string ready to be written to disk.

    Raises:
        OfflineLinterError: If the rendered HTML contains external network
            references that would break ``file://`` viewing.
    """
    _skipped = skipped_lessons or []
    renderer = JinjaRenderer()
    html = renderer.render(
        lesson_plan=lesson_plan,
        repo_name=repo_name,
        wiedunflow_version=_wiedunflow_version,
        generated_at=generated_at,
        doc_coverage=doc_coverage,
        has_readme=has_readme,
        skipped_count=len(_skipped),
        degraded=degraded,
        total_planned=total_planned,
        symbols=symbols,
        repo_root=repo_root,
    )
    validate_offline_invariant(html)
    return html
