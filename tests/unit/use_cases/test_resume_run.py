# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for resume_run.slice_manifest_at_first_incomplete (US-017)."""

from __future__ import annotations

from datetime import UTC, datetime

from wiedunflow.entities.lesson_manifest import LessonManifest, LessonSpec, ManifestMetadata
from wiedunflow.use_cases.resume_run import slice_manifest_at_first_incomplete

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manifest(*lesson_ids: str) -> LessonManifest:
    """Build a minimal LessonManifest from an ordered list of lesson IDs."""
    specs = tuple(
        LessonSpec(
            id=lid,
            title=f"Lesson {lid}",
            teaches=f"How to do {lid}",
        )
        for lid in lesson_ids
    )
    metadata = ManifestMetadata(
        codeguide_version="0.0.4",
        total_lessons=len(specs),
        generated_at=datetime.now(UTC),
    )
    return LessonManifest(lessons=specs, metadata=metadata)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_us_017_empty_cache_returns_all_as_todo() -> None:
    """No cached lessons → reused is empty, todo contains all specs (AC1, AC4)."""
    manifest = _make_manifest("L1", "L2", "L3")
    reused, todo = slice_manifest_at_first_incomplete(manifest, cached_lesson_ids=set())

    assert reused == ()
    assert len(todo) == 3
    assert tuple(s.id for s in todo) == ("L1", "L2", "L3")


def test_us_017_full_cache_returns_all_as_reused() -> None:
    """All lesson IDs in cache → reused contains all IDs, todo is empty (AC1, AC2)."""
    manifest = _make_manifest("L1", "L2", "L3")
    reused, todo = slice_manifest_at_first_incomplete(
        manifest, cached_lesson_ids={"L1", "L2", "L3"}
    )

    assert reused == ("L1", "L2", "L3")
    assert todo == ()


def test_us_017_partial_cache_resumes_from_first_missing() -> None:
    """Lessons L1..L3 cached out of L1..L5 → reused=(L1,L2,L3), todo starts at L4."""
    manifest = _make_manifest("L1", "L2", "L3", "L4", "L5")
    reused, todo = slice_manifest_at_first_incomplete(
        manifest, cached_lesson_ids={"L1", "L2", "L3"}
    )

    assert reused == ("L1", "L2", "L3")
    assert len(todo) == 2
    assert todo[0].id == "L4"
    assert todo[1].id == "L5"


def test_us_017_gap_in_cache_resumes_from_first_gap() -> None:
    """Gap in cache: L1+L3 cached but L2 missing → resume from L2 (preserves coherence).

    Lesson L3 is NOT reused even though it's in the cache, because lesson L2
    (its predecessor) was not generated — narrative coherence would be broken.
    """
    manifest = _make_manifest("L1", "L2", "L3", "L4")
    reused, todo = slice_manifest_at_first_incomplete(
        manifest,
        cached_lesson_ids={"L1", "L3"},  # L3 cached but L2 not
    )

    assert reused == ("L1",)
    assert len(todo) == 3
    assert todo[0].id == "L2"
    assert todo[1].id == "L3"
    assert todo[2].id == "L4"


def test_us_017_single_lesson_manifest_all_cached() -> None:
    """Single-lesson manifest where the lesson is cached → all reused."""
    manifest = _make_manifest("L1")
    reused, todo = slice_manifest_at_first_incomplete(manifest, cached_lesson_ids={"L1"})

    assert reused == ("L1",)
    assert todo == ()


def test_us_017_single_lesson_manifest_not_cached() -> None:
    """Single-lesson manifest with no cache → todo has the one lesson."""
    manifest = _make_manifest("L1")
    reused, todo = slice_manifest_at_first_incomplete(manifest, cached_lesson_ids=set())

    assert reused == ()
    assert len(todo) == 1
    assert todo[0].id == "L1"


def test_us_017_only_first_lesson_cached() -> None:
    """Only the first lesson cached → reused=(L1,), todo starts at L2."""
    manifest = _make_manifest("L1", "L2", "L3")
    reused, todo = slice_manifest_at_first_incomplete(manifest, cached_lesson_ids={"L1"})

    assert reused == ("L1",)
    assert len(todo) == 2
    assert todo[0].id == "L2"


def test_us_017_only_last_lesson_cached_forces_full_redo() -> None:
    """Only the last lesson is cached — L1 is missing so resume starts from L1."""
    manifest = _make_manifest("L1", "L2", "L3")
    reused, todo = slice_manifest_at_first_incomplete(
        manifest,
        cached_lesson_ids={"L3"},  # last only
    )

    assert reused == ()
    assert len(todo) == 3
    assert todo[0].id == "L1"


def test_us_017_reused_preserves_manifest_order() -> None:
    """The reused tuple preserves the manifest ordering, not the set iteration order."""
    manifest = _make_manifest("A", "B", "C", "D", "E")
    reused, todo = slice_manifest_at_first_incomplete(
        manifest,
        cached_lesson_ids={"C", "B", "A"},  # unordered set
    )

    assert reused == ("A", "B", "C")  # must be manifest order
    assert todo[0].id == "D"


def test_us_017_superset_cached_ids_treated_correctly() -> None:
    """Extra IDs in the cache (not in manifest) are ignored gracefully."""
    manifest = _make_manifest("L1", "L2")
    reused, todo = slice_manifest_at_first_incomplete(
        manifest,
        cached_lesson_ids={"L1", "L2", "L99"},  # L99 not in manifest
    )

    assert reused == ("L1", "L2")
    assert todo == ()
