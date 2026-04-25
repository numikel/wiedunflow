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

from codeguide import __version__ as _codeguide_version
from codeguide.adapters.jinja_renderer import JinjaRenderer
from codeguide.adapters.pygments_highlighter import highlight_python as _highlight_python
from codeguide.cli.cost_estimator import CostEstimate
from codeguide.cli.cost_estimator import estimate as _estimate_cost
from codeguide.cli.editor_resolver import open_in_editor as _open_in_editor
from codeguide.cli.stage_reporter import NoOpReporter, StageReporter
from codeguide.entities.lesson import Lesson
from codeguide.entities.lesson_manifest import (
    LessonManifest,
    LessonSpec,
    ManifestMetadata,
)
from codeguide.entities.lesson_plan import LessonPlan
from codeguide.entities.skipped_lesson import SkippedLesson
from codeguide.use_cases.doc_coverage import compute_doc_coverage
from codeguide.use_cases.grounding_retry import narrate_with_grounding_retry
from codeguide.use_cases.ingestion import ingest
from codeguide.use_cases.offline_linter import validate_offline_invariant
from codeguide.use_cases.outline_builder import build_outline
from codeguide.use_cases.plan_lesson_manifest import PlanningFatalError, plan_with_retry
from codeguide.use_cases.rag_corpus import build_and_index

if TYPE_CHECKING:
    from codeguide.entities.code_symbol import CodeSymbol
    from codeguide.entities.doc_coverage import DocCoverage
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
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    output_path: Path
    skipped_lessons: tuple[SkippedLesson, ...]
    degraded: bool
    degraded_ratio: float
    total_planned: int
    retry_count: int
    hallucinated_symbols: tuple[str, ...] = ()


@dataclass
class _StageGenerationOutput:
    """Typed output of the :func:`_stage_generation` helper."""

    lessons: list[Lesson] = field(default_factory=list)
    skipped: list[SkippedLesson] = field(default_factory=list)
    retry_count: int = 0
    concepts_introduced: tuple[str, ...] = ()
    hallucinated_symbols: list[str] = field(default_factory=list)


def generate_tutorial(  # noqa: PLR0915 — 7-stage orchestrator is naturally long
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
) -> GenerationResult:
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
    if output_path is None:
        output_path = Path("tutorial.html").resolve()

    if progress is None:
        progress = NoOpReporter()

    repo_name = repo_path.name

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
    progress.stage_start(2)
    logger.info("stage_start", stage=2, name="Analysis")
    progress.progress_line(f"parsing AST + resolving call graph for {len(ingestion.files)} files")
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
    try:
        manifest: LessonManifest = plan_with_retry(providers.llm, outline, allowed_symbols)
    except PlanningFatalError as exc:
        logger.error(
            "planning_fatal",
            attempts=exc.attempts,
            last_error=exc.last_error,
        )
        raise
    progress.stage_done(f"manifest ready ({len(manifest.lessons)} lessons)")

    # Re-attach orchestrator-side metadata — the provider-level metadata is a
    # placeholder because only the orchestrator knows the real clock, version,
    # and documentation coverage derived from the current run.
    now = providers.clock.now()
    manifest = manifest.model_copy(
        update={
            "metadata": ManifestMetadata(
                schema_version="1.0.0",
                codeguide_version=_codeguide_version,
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
        pre_narration_estimate = _estimate_cost(
            symbols=len(symbols),
            lessons=len(manifest.lessons),
            clusters=1,
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

    # --review-plan (US-016): write the manifest to .codeguide/manifest.json and
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
        preview_output.write_text(html, encoding="utf-8")
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

    _check_abort()

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
        should_abort=should_abort,
        progress=progress,
    )
    all_lessons: list[Lesson] = generation_result.lessons
    skipped_lessons: list[SkippedLesson] = generation_result.skipped
    # retry_count is logged by grounding_retry; future RunReport will expose it via Cross-cutting.
    concepts_introduced: tuple[str, ...] = generation_result.concepts_introduced

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
    output_path.write_text(html, encoding="utf-8")
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
    )


# ---------------------------------------------------------------------------
# Private stage helpers
# ---------------------------------------------------------------------------


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

    Writes ``<repo>/.codeguide/manifest.edited.json`` so edits survive across
    runs and can be diffed. On save, the file is validated back into a
    ``LessonManifest``; an invalid edit falls back to the original with a
    structured warning so the run continues rather than hard-failing.
    """
    edit_dir = repo_path / ".codeguide"
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
        A :class:`~codeguide.entities.lesson_manifest.LessonSpec` with
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
    should_abort: Callable[[], bool] | None = None,
    progress: StageReporter | NoOpReporter | None = None,
) -> _StageGenerationOutput:
    """Stage 6: Narrate each lesson spec with grounding retry.

    Accumulates ``concepts_introduced`` from successfully generated lessons only
    (skipped lessons do not contribute to the concept set, preventing "phantom"
    concept claims in later narrations).

    Appends a closing lesson epilogue (US-049) after the regular lessons.

    Args:
        manifest: Planning stage output with ordered ``LessonSpec`` items.
        llm: Provider used to generate the narrative for each spec.
        allowed_symbols: Frozenset of groundable symbol names (Stage 3 output).
        ingestion: Ingestion result used to build the closing lesson spec.
        repo_path: Repo root path (passed through to closing spec builder).
        ranked: RankedGraph used to find uncovered high-rank symbols.

    Returns:
        :class:`_StageGenerationOutput` with typed fields for lessons, skipped,
        retry_count, and cumulative concepts_introduced.
    """
    output = _StageGenerationOutput()

    if progress is None:
        progress = NoOpReporter()

    total_lessons = len(manifest.lessons)
    for idx, spec in enumerate(manifest.lessons, start=1):
        if should_abort is not None and should_abort():
            # Graceful SIGINT between lessons (US-027).  Partially generated
            # lessons remain in ``output`` so the caller can flush a checkpoint
            # before re-raising KeyboardInterrupt.
            raise KeyboardInterrupt("SIGINT received during generation stage")
        progress.lesson_event(idx, total_lessons, spec.title)
        result = narrate_with_grounding_retry(
            spec,
            allowed_symbols,
            llm,
            output.concepts_introduced,
            hallucination_accumulator=output.hallucinated_symbols,
        )

        if isinstance(result, SkippedLesson):
            # Lesson failed both attempts — produce a placeholder Lesson with
            # status="skipped" for LessonPlan (which only accepts Lesson objects)
            # and record the SkippedLesson for run-report stats.
            output.skipped.append(result)
            placeholder = Lesson(
                id=result.lesson_id,
                title=result.title,
                narrative=(
                    f"This lesson was skipped due to grounding failures — "
                    f"see symbol {result.missing_symbols[0] if result.missing_symbols else 'unknown'} "
                    f"in the code"
                ),
                code_refs=result.missing_symbols,
                status="skipped",
            )
            output.lessons.append(placeholder)
            # Do NOT update concepts_introduced from skipped lessons.
        else:
            output.lessons.append(result)
            output.concepts_introduced = (*output.concepts_introduced, spec.teaches)

    # --- Closing lesson (US-049) — always +1 beyond cap ---
    closing_spec = _build_closing_spec(manifest, ingestion, repo_path, ranked)
    # Closing lesson: empty allowed_symbols -> grounding validation skipped.
    # Still thread the accumulator so word-count retries are visible.
    closing_result = narrate_with_grounding_retry(
        closing_spec,
        frozenset(),
        llm,
        output.concepts_introduced,
        hallucination_accumulator=output.hallucinated_symbols,
    )
    if isinstance(closing_result, SkippedLesson):
        # Closing lesson failed — render placeholder (still append, no DEGRADED impact).
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
        codeguide_version=_codeguide_version,
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
