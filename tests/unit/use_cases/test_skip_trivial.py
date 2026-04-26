# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for ``use_cases.skip_trivial.filter_trivial_helpers``.

Covers the four-condition skip rule:
    span < _TRIVIAL_SPAN
    AND symbol not cited as primary in any other lesson
    AND symbol not in entry_points
    AND symbol not in top-5% by PageRank
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from wiedunflow.entities.code_ref import CodeRef
from wiedunflow.entities.lesson_manifest import (
    LessonManifest,
    LessonSpec,
    ManifestMetadata,
)
from wiedunflow.entities.ranked_graph import RankedGraph, RankedSymbol
from wiedunflow.use_cases.skip_trivial import filter_trivial_helpers


def _build_ref(
    symbol: str,
    *,
    line_start: int = 1,
    line_end: int = 1,
    role: str = "primary",
) -> CodeRef:
    return CodeRef(
        file_path=Path(f"{symbol}.py"),
        symbol=symbol,
        line_start=line_start,
        line_end=line_end,
        role=role,  # type: ignore[arg-type]
    )


def _build_spec(
    lesson_id: str,
    *,
    refs: tuple[CodeRef, ...],
    is_closing: bool = False,
) -> LessonSpec:
    return LessonSpec(
        id=lesson_id,
        title=lesson_id,
        teaches=f"Lesson {lesson_id}",
        code_refs=refs,
        is_closing=is_closing,
    )


def _build_manifest(specs: tuple[LessonSpec, ...]) -> LessonManifest:
    return LessonManifest(
        lessons=specs,
        metadata=ManifestMetadata(
            wiedunflow_version="0.2.1",
            total_lessons=len(specs),
            generated_at=datetime.now(UTC),
        ),
    )


def _build_ranked(symbols_with_scores: tuple[tuple[str, float], ...]) -> RankedGraph:
    """Minimal RankedGraph fixture with deterministic PageRank scores."""
    ranked = tuple(
        RankedSymbol(symbol_name=name, pagerank_score=score, community_id=0)
        for name, score in symbols_with_scores
    )
    return RankedGraph(
        ranked_symbols=ranked,
        communities=(frozenset(s for s, _ in symbols_with_scores),),
        topological_order=tuple(s for s, _ in symbols_with_scores),
        has_cycles=False,
    )


# ---------------------------------------------------------------------------
# enabled gate
# ---------------------------------------------------------------------------


def test_disabled_returns_unchanged_manifest_and_empty_helpers() -> None:
    spec = _build_spec("lesson-001", refs=(_build_ref("foo"),))
    manifest = _build_manifest((spec,))
    ranked = _build_ranked((("foo", 0.5),))

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=False)

    assert result_manifest is manifest
    assert helpers == ()


# ---------------------------------------------------------------------------
# Skip / keep parametrized
# ---------------------------------------------------------------------------


def test_one_liner_not_cited_elsewhere_skipped() -> None:
    """span<3, unique symbol, not entry point, not top-5% → skipped.

    Fixture design: 20 padding symbols at score=1.0 sit comfortably in the
    top-5% bucket; ``trivial_helper`` at 0.0 falls outside it.
    """
    spec_a = _build_spec(
        "lesson-001",
        refs=(_build_ref("trivial_helper", line_start=10, line_end=10),),
    )
    spec_b = _build_spec(
        "lesson-002",
        refs=(_build_ref("other", line_start=1, line_end=20),),  # span=19 → non-trivial
    )
    manifest = _build_manifest((spec_a, spec_b))
    scores = (
        ("trivial_helper", 0.0),
        ("other", 0.5),
        *((f"sym_{i}", 1.0) for i in range(20)),
    )
    ranked = _build_ranked(scores)

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    kept_ids = {lsn.id for lsn in result_manifest.lessons}
    assert "lesson-001" not in kept_ids
    assert "lesson-002" in kept_ids
    assert len(helpers) == 1
    assert helpers[0].symbol == "trivial_helper"


def test_one_liner_cited_as_primary_elsewhere_kept() -> None:
    """When symbol is primary in 2 lessons, neither is skipped (no orphan reference)."""
    spec_a = _build_spec(
        "lesson-001",
        refs=(_build_ref("shared", line_start=10, line_end=10),),
    )
    spec_b = _build_spec(
        "lesson-002",
        refs=(_build_ref("shared", line_start=10, line_end=10),),
    )
    manifest = _build_manifest((spec_a, spec_b))
    ranked = _build_ranked((("shared", 0.001),))

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    assert {lsn.id for lsn in result_manifest.lessons} == {"lesson-001", "lesson-002"}
    assert helpers == ()


def test_one_liner_in_entry_points_kept() -> None:
    """Entry-point symbols are never skipped, even when they are 1-liners."""
    spec = _build_spec(
        "lesson-001",
        refs=(_build_ref("main", line_start=1, line_end=1),),
    )
    manifest = _build_manifest((spec,))
    ranked = _build_ranked((("main", 0.001),))

    result_manifest, helpers = filter_trivial_helpers(
        manifest, ranked, frozenset({"main"}), enabled=True
    )

    assert len(result_manifest.lessons) == 1
    assert helpers == ()


def test_one_liner_in_top5_pagerank_kept() -> None:
    """Top-5% symbols are protected — even short ones carry the codebase."""
    # 100 symbols, score 1.0 for "important" → comfortably top-5%.
    scores = (("important", 1.0), *((f"sym_{i}", 0.001) for i in range(99)))
    spec = _build_spec(
        "lesson-001",
        refs=(_build_ref("important", line_start=1, line_end=1),),
    )
    manifest = _build_manifest((spec,))
    ranked = _build_ranked(scores)

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    assert len(result_manifest.lessons) == 1
    assert helpers == ()


def test_closing_lesson_never_filtered() -> None:
    """is_closing=True is an absolute keep — even with empty code_refs."""
    spec = _build_spec("lesson-closing", refs=(), is_closing=True)
    manifest = _build_manifest((spec,))
    ranked = _build_ranked((("dummy", 0.5),))

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    assert len(result_manifest.lessons) == 1
    assert helpers == ()


def test_lesson_without_primary_ref_kept() -> None:
    """Lesson with only 'referenced' role refs cannot be evaluated → keep."""
    spec = _build_spec(
        "lesson-001",
        refs=(_build_ref("ref_only", line_start=1, line_end=1, role="referenced"),),
    )
    manifest = _build_manifest((spec,))
    ranked = _build_ranked((("ref_only", 0.001),))

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    assert len(result_manifest.lessons) == 1
    assert helpers == ()


def test_span_three_or_more_kept() -> None:
    """Body span >= 3 is not trivial — keep regardless of other conditions."""
    spec = _build_spec(
        "lesson-001",
        refs=(_build_ref("not_trivial", line_start=1, line_end=4),),
    )
    manifest = _build_manifest((spec,))
    ranked = _build_ranked((("not_trivial", 0.001),))

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    assert len(result_manifest.lessons) == 1
    assert helpers == ()


def test_metadata_total_lessons_synced_after_filter() -> None:
    """When lessons are dropped, metadata.total_lessons reflects the new count."""
    spec_a = _build_spec(
        "lesson-001",
        refs=(_build_ref("trivial", line_start=1, line_end=1),),
    )
    spec_b = _build_spec(
        "lesson-002",
        refs=(_build_ref("other", line_start=1, line_end=20),),  # non-trivial span
    )
    spec_closing = _build_spec("lesson-closing", refs=(), is_closing=True)
    manifest = _build_manifest((spec_a, spec_b, spec_closing))
    scores = (
        ("trivial", 0.0),
        ("other", 0.5),
        *((f"sym_{i}", 1.0) for i in range(20)),
    )
    ranked = _build_ranked(scores)

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    assert len(result_manifest.lessons) == 2  # spec_a removed
    assert result_manifest.metadata.total_lessons == 2
    assert len(helpers) == 1


# ---------------------------------------------------------------------------
# Helper appendix attachment to closing lesson
# ---------------------------------------------------------------------------


def test_helpers_returned_as_tuple_for_orchestrator_attachment() -> None:
    """Skipped helpers are returned as a typed tuple, not mutated onto the spec.

    The orchestrator (`generate_tutorial.py`) takes the returned tuple and
    attaches a typed `HelperAppendixEntry` collection onto the *Lesson*
    entity post-narration. `LessonSpec.code_refs` are NOT mutated — the
    earlier `role="example"` smuggling path was dead code and is removed
    in v0.3.x polish.
    """
    spec_a = _build_spec(
        "lesson-001",
        refs=(_build_ref("trivial", line_start=1, line_end=1),),
    )
    closing = _build_spec("lesson-closing", refs=(), is_closing=True)
    manifest = _build_manifest((spec_a, closing))
    scores = (("trivial", 0.0), *((f"sym_{i}", 1.0) for i in range(20)))
    ranked = _build_ranked(scores)

    result_manifest, helper_refs = filter_trivial_helpers(
        manifest, ranked, frozenset(), enabled=True
    )

    # Returned tuple carries the skipped ref for the orchestrator.
    assert len(helper_refs) == 1
    assert helper_refs[0].symbol == "trivial"
    # Closing lesson spec is NOT mutated with role="example" refs anymore.
    closing_after = next(lsn for lsn in result_manifest.lessons if lsn.is_closing)
    assert all(r.role != "example" for r in closing_after.code_refs)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("span", [1, 2])
def test_span_below_threshold_eligible(span: int) -> None:
    """Spans 1 and 2 both qualify as trivial (< _TRIVIAL_SPAN = 3)."""
    spec = _build_spec(
        "lesson-001",
        refs=(_build_ref("trivial", line_start=10, line_end=10 + span - 1),),
    )
    manifest = _build_manifest((spec,))
    scores = (("trivial", 0.0), *((f"x_{i}", 1.0) for i in range(20)))
    ranked = _build_ranked(scores)

    _, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    assert len(helpers) == 1


def test_no_helpers_returns_unchanged_manifest_reference() -> None:
    """When nothing matches the skip rule, the original manifest is returned."""
    spec = _build_spec(
        "lesson-001",
        refs=(_build_ref("substantial", line_start=1, line_end=20),),
    )
    manifest = _build_manifest((spec,))
    ranked = _build_ranked((("substantial", 0.5),))

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    assert result_manifest is manifest
    assert helpers == ()


def test_empty_ranked_symbols_keeps_all_lessons() -> None:
    """An empty RankedGraph yields top5_threshold=0.0 — every symbol passes the >=
    comparison and survives the top-5% gate. Regression guard so degenerate ranking
    does not silently start filtering when scoring produces no symbols at all.
    """
    spec_a = _build_spec(
        "lesson-001",
        refs=(_build_ref("trivial", line_start=1, line_end=1),),
    )
    manifest = _build_manifest((spec_a,))
    ranked = RankedGraph(
        ranked_symbols=(),
        communities=(),
        topological_order=(),
        has_cycles=False,
    )

    result_manifest, helpers = filter_trivial_helpers(manifest, ranked, frozenset(), enabled=True)

    assert len(result_manifest.lessons) == 1
    assert helpers == ()
