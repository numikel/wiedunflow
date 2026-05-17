# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Literal

import structlog
from pydantic import ValidationError

from wiedunflow.entities.lesson_manifest import (
    LessonManifest,
    LessonManifestValidationError,
    validate_against_graph,
)
from wiedunflow.interfaces.ports import LLMProvider

logger = structlog.get_logger(__name__)

_MAX_PLANNING_ATTEMPTS = 3


class PlanningFatalError(RuntimeError):
    """Raised when planning fails after the allowed retry budget is exhausted.

    The pipeline treats this as an unrecoverable failure (exit code 1).
    No partial/degraded tutorial is emitted — see ADR-0007.
    """

    def __init__(self, attempts: int, last_error: str) -> None:
        super().__init__(f"Planning failed after {attempts} attempts. Last error: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


def _prepend_allowed_symbols(outline: str, allowed_symbols: frozenset[str]) -> str:
    """Prepend an ALLOWED SYMBOLS list to the planning outline.

    Mirrors the reinforcement block from ``_build_reinforcement`` so the model
    gets the full symbol list on the first attempt, not only on retry.
    """
    top = sorted(allowed_symbols)[:100]
    block = "\n".join(f"- {s}" for s in top)
    return f"{outline}\n\nALLOWED SYMBOLS (use only names from this list in code_refs):\n{block}"


def plan_with_retry(
    llm: LLMProvider,
    outline: str,
    allowed_symbols: frozenset[str],
    entry_points: frozenset[str] | None = None,
    entry_point_mode: Literal["auto", "always", "never"] = "auto",
) -> LessonManifest:
    """Run the planning stage with one retry-with-reinforcement on validation failure.

    Retry budget: 1 extra attempt (2 total LLM calls max). On second failure,
    raises :exc:`PlanningFatalError` — there is no Stage 5 fallback (ADR-0007).

    After the planning LLM call succeeds and grounding validates, the manifest
    is post-processed via :func:`_apply_entry_point_first` to reorder lessons so
    the entry-point lesson appears first (unless *entry_point_mode* is ``"never"``).

    Args:
        llm: The LLM provider implementing the ``plan`` method.
        outline: Code-graph outline string built by ``build_outline``.
        allowed_symbols: Frozenset of symbol names the manifest may reference.
            Derived from ``RankedGraph`` by :func:`_collect_allowed_symbols` in
            ``generate_tutorial``; excludes uncertain / dynamic-import / cyclic.
        entry_points: Optional frozenset of qualified symbol names detected as
            entry points (from :func:`~wiedunflow.use_cases.entry_point_detector.detect_entry_points`).
            When ``None``, treated as an empty set (no reordering).
        entry_point_mode: Controls the reorder behaviour — ``"auto"`` (default),
            ``"always"``, or ``"never"``.  See :func:`_apply_entry_point_first`.

    Returns:
        A :class:`~wiedunflow.entities.lesson_manifest.LessonManifest` that
        passes grounding validation, with optional entry-point reordering applied.

    Raises:
        PlanningFatalError: After exhausting the retry budget.
        LessonManifestValidationError: When *entry_point_mode* is ``"always"``
            and no entry-point lesson is found in the manifest.
    """
    attempts = 0
    last_error = ""
    current_outline = _prepend_allowed_symbols(outline, allowed_symbols)
    _ep = entry_points or frozenset()

    while attempts < _MAX_PLANNING_ATTEMPTS:
        attempts += 1
        try:
            manifest = llm.plan(current_outline)
            validate_against_graph(manifest, allowed_symbols)
            logger.info("planning_ok", attempt=attempts, lessons=len(manifest.lessons))
            # Post-planning: reorder so entry-point lesson is first.
            manifest = _apply_entry_point_first(manifest, _ep, mode=entry_point_mode)
            return manifest
        except (LessonManifestValidationError, ValidationError, ValueError) as exc:
            last_error = str(exc)
            logger.warning("planning_retry", attempt=attempts, error=last_error[:200])
            invalid_symbols: list[str] = getattr(exc, "invalid_symbols", [])
            current_outline = _build_reinforcement(
                outline,
                attempt=attempts,
                last_error=last_error,
                invalid_symbols=invalid_symbols,
                allowed_symbols=allowed_symbols,
            )

    raise PlanningFatalError(attempts=attempts, last_error=last_error)


def _build_reinforcement(
    original_outline: str,
    *,
    attempt: int,
    last_error: str,
    invalid_symbols: list[str],
    allowed_symbols: frozenset[str],
) -> str:
    """Construct the retry prompt for planning.

    First attempt (attempt == 1): returns the full outline with an error block
    appended — gives the model maximum context on the first retry.

    Subsequent attempts (attempt >= 2): returns a slim reinforcement message
    *without* the full outline so the prompt does not balloon with redundant
    context on the second and third retries.  The model already received the
    outline on the initial call; re-sending it wastes ~50% of tokens on retries
    where the guidance block is what matters.
    """
    top_allowed = sorted(allowed_symbols)[:20]
    allowed_preview = ", ".join(top_allowed)
    invalid_preview = ", ".join(invalid_symbols[:10]) if invalid_symbols else "(validation error)"

    if attempt <= 1:
        # First retry — keep the full outline; append a grounding block.
        full_allowed = ", ".join(sorted(allowed_symbols)[:30])
        return (
            f"{original_outline}\n\n"
            f"--- PREVIOUS ATTEMPT FAILED ---\n"
            f"Error: {last_error[:500]}\n"
            f"Invalid symbols from last response: {invalid_preview}\n"
            f"You MUST use ONLY these allowed symbols "
            f"(top 30 shown, total={len(allowed_symbols)}): {full_allowed}\n"
            f"Retry with corrected JSON output."
        )

    # Slim reinforcement for attempts 2+ — omit the full outline to reduce
    # token cost and focus the model exclusively on the correction task.
    return (
        f"PREVIOUS ATTEMPT FAILED ({attempt}/3): {last_error[:500]}\n"
        f"Invalid symbols cited: {invalid_preview}\n"
        f"Allowed symbols (top by PageRank): {allowed_preview}\n"
        "Retry with valid symbols only."
    )


def _apply_entry_point_first(
    manifest: LessonManifest,
    entry_points: frozenset[str],
    *,
    mode: Literal["auto", "always", "never"] = "auto",
) -> LessonManifest:
    """Reorder lessons so the entry-point lesson appears first.

    The lesson whose ``code_refs`` include any symbol in *entry_points* is
    moved to position 0.  The closing lesson (``is_closing=True``) always
    stays at the end.  Other lessons keep their relative order.

    Behaviour by *mode*:

    - ``"never"``: Returns *manifest* unchanged.
    - ``"auto"`` (default): No-op when *entry_points* is empty or no lesson
      matches; silently skips reordering.
    - ``"always"``: Raises :exc:`~wiedunflow.entities.lesson_manifest.LessonManifestValidationError`
      when no entry-point lesson is found.

    Args:
        manifest: Planning-stage output to reorder.
        entry_points: Frozenset of qualified symbol names identified as entry
            points by :func:`~wiedunflow.use_cases.entry_point_detector.detect_entry_points`.
        mode: Reorder policy — ``"auto"``, ``"always"``, or ``"never"``.

    Returns:
        Possibly-reordered :class:`~wiedunflow.entities.lesson_manifest.LessonManifest`.

    Raises:
        LessonManifestValidationError: Only in ``"always"`` mode when no
            matching lesson is found.
    """
    if mode == "never":
        return manifest

    if not entry_points and mode == "auto":
        return manifest

    lessons = list(manifest.lessons)

    # Separate closing lesson(s) — they must stay at the end.
    closing = [s for s in lessons if s.is_closing]
    regular = [s for s in lessons if not s.is_closing]

    # Find the first regular lesson that references an entry-point symbol.
    ep_index: int | None = None
    for i, spec in enumerate(regular):
        for ref in spec.code_refs:
            # Match both fully-qualified and simple names.
            simple = ref.symbol.rsplit(".", 1)[-1]
            if ref.symbol in entry_points or simple in entry_points:
                ep_index = i
                break
        if ep_index is not None:
            break

    if ep_index is None:
        if mode == "always":
            raise LessonManifestValidationError(
                invalid_symbols=[],
                message=(
                    "planning_entry_point_first=always but no lesson references "
                    f"any of the detected entry points: {sorted(entry_points)[:10]}"
                ),
            )
        # mode == "auto": no match is fine, return unchanged.
        return manifest

    if ep_index == 0:
        # Already first — no mutation needed.
        return manifest

    # Move the entry-point lesson to position 0.
    ep_spec = regular.pop(ep_index)
    reordered = [ep_spec, *regular, *closing]

    logger.info(
        "entry_point_lesson_reordered",
        lesson_id=ep_spec.id,
        from_index=ep_index,
        to_index=0,
    )

    # Rebuild manifest with reordered lessons; total_lessons is unchanged.
    new_metadata = manifest.metadata.model_copy(update={"total_lessons": len(reordered)})
    return manifest.model_copy(update={"lessons": tuple(reordered), "metadata": new_metadata})
