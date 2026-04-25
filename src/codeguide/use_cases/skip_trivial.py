# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Filter trivial helper lessons from the lesson manifest.

A lesson is considered "trivial" when its primary ``code_ref`` body span is
very short AND the symbol is not referenced as ``primary`` in any other lesson,
is not an entry-point, and is not in the top-5% of the PageRank distribution.

Trivial lessons are removed from the active manifest and their primary
``code_refs`` are collected into a ``helper_appendix`` tuple that gets
attached to the *closing* lesson spec.  The frontend (Track B) reads
``meta.helper_appendix`` from the closing lesson payload.

Design notes:
- When ``enabled=False`` (default), this function is a no-op — backward-compat
  with v0.2.0 behaviour.
- The closing lesson (``is_closing=True``) is never filtered.
- The ``LessonManifest.metadata.total_lessons`` is updated to reflect the new
  lesson count after filtering.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from codeguide.entities.lesson_manifest import LessonManifest, LessonSpec

if TYPE_CHECKING:
    from codeguide.entities.code_ref import CodeRef
    from codeguide.entities.ranked_graph import RankedGraph

__all__ = ["filter_trivial_helpers"]

logger = structlog.get_logger(__name__)

# Body span threshold: lessons with span < this are candidates for filtering.
_TRIVIAL_SPAN = 3


def filter_trivial_helpers(
    manifest: LessonManifest,
    ranked_graph: RankedGraph,
    entry_points: frozenset[str],
    *,
    enabled: bool = False,
) -> tuple[LessonManifest, tuple[CodeRef, ...]]:
    """Filter trivial helper lessons and collect their refs for the appendix.

    A lesson is skipped when **all** of the following hold:
    - Its primary ``code_ref`` body span < :data:`_TRIVIAL_SPAN` lines.
    - The symbol is NOT cited as ``primary`` in any *other* lesson.
    - The symbol is NOT in *entry_points*.
    - The symbol is NOT in the top-5% of ranked symbols by PageRank score.

    Skipped lessons' primary ``code_refs`` are returned as the ``helper_refs``
    tuple.  The closing lesson's ``code_refs`` are extended with these refs
    (attached as ``helper_appendix`` via lesson spec ``teaches`` metadata —
    Track B reads ``meta.helper_appendix`` from the lesson payload).

    Args:
        manifest: Planning-stage manifest to filter.
        ranked_graph: Stage 3 :class:`~codeguide.entities.ranked_graph.RankedGraph`
            with ``ranked_symbols`` sorted descending by PageRank score.
        entry_points: Frozenset of qualified symbol names detected as entry points.
        enabled: When ``False`` (default), returns ``(manifest, ())`` immediately.

    Returns:
        ``(filtered_manifest, helper_refs_for_appendix)`` where
        ``filtered_manifest`` has trivial lessons removed and
        ``helper_refs_for_appendix`` contains the primary refs from removed lessons.
        When ``enabled=False`` returns ``(manifest, ())``.
    """
    if not enabled:
        return manifest, ()

    # Defensive: a degenerate :class:`RankedGraph` with no symbols means we
    # can't tell which symbols are "important", so we keep everything rather
    # than risk dropping lessons the user actually wanted. (Without this
    # guard the top-5% set would be empty and every trivial symbol would be
    # skip-eligible — silently trimming small repos with sparse rankings.)
    if not ranked_graph.ranked_symbols:
        return manifest, ()

    # Compute top-5% PageRank threshold.
    all_scores = sorted(
        (rs.pagerank_score for rs in ranked_graph.ranked_symbols),
        reverse=True,
    )
    top5_cutoff_idx = max(1, int(len(all_scores) * 0.05))
    top5_threshold = all_scores[top5_cutoff_idx - 1]

    top5_symbols: frozenset[str] = frozenset(
        rs.symbol_name for rs in ranked_graph.ranked_symbols if rs.pagerank_score >= top5_threshold
    )

    helper_refs: list[CodeRef] = []
    kept_lessons: list[LessonSpec] = []

    for spec in manifest.lessons:
        if spec.is_closing:
            # Closing lesson is never filtered.
            kept_lessons.append(spec)
            continue

        primary_ref = next((r for r in spec.code_refs if r.role == "primary"), None)
        if primary_ref is None:
            # No primary ref → cannot determine trivial-ness → keep.
            kept_lessons.append(spec)
            continue

        span = primary_ref.line_end - primary_ref.line_start

        # Check all skip conditions (ALL must hold to skip).
        if span >= _TRIVIAL_SPAN:
            kept_lessons.append(spec)
            continue

        symbol = primary_ref.symbol
        simple = symbol.rsplit(".", 1)[-1]

        # Symbol cited as primary in other lessons?
        primary_count = sum(
            1
            for s in manifest.lessons
            for r in s.code_refs
            if r.role == "primary" and r.symbol == symbol and s.id != spec.id
        )
        if primary_count > 0:
            kept_lessons.append(spec)
            continue

        # Entry point?
        if symbol in entry_points or simple in entry_points:
            kept_lessons.append(spec)
            continue

        # Top-5% PageRank?
        if symbol in top5_symbols or simple in top5_symbols:
            kept_lessons.append(spec)
            continue

        # All conditions met — skip this lesson.
        helper_refs.append(primary_ref)
        logger.debug(
            "skip_trivial_lesson",
            lesson_id=spec.id,
            symbol=symbol,
            span=span,
        )

    if not helper_refs:
        # Nothing was filtered.
        return manifest, ()

    logger.info(
        "skip_trivial_done",
        removed_count=len(helper_refs),
        kept_count=len(kept_lessons),
    )

    helper_tuple: tuple[CodeRef, ...] = tuple(helper_refs)

    # The helper-appendix tuple is consumed by the orchestrator
    # (``generate_tutorial.py``) which attaches a typed
    # :class:`~codeguide.entities.lesson.HelperAppendixEntry` collection to
    # the closing :class:`Lesson` after Stage 6 narration. The renderer
    # serialises ``Lesson.helper_appendix`` into the JSON envelope under the
    # top-level ``helper_appendix`` field, which the JS consumes directly —
    # no LessonSpec mutation needed (an earlier draft attempted to smuggle
    # the refs through ``code_refs[role="example"]`` but that path was never
    # wired into rendering).
    new_metadata = manifest.metadata.model_copy(update={"total_lessons": len(kept_lessons)})
    new_manifest = manifest.model_copy(
        update={"lessons": tuple(kept_lessons), "metadata": new_metadata}
    )
    return new_manifest, helper_tuple
