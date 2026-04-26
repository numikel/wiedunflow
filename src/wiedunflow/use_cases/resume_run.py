# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Resume-run logic — pure functions for slicing a lesson manifest at the first incomplete lesson.

Used by the ``--resume`` CLI flag (US-017) to determine which lessons have
already been generated (and can be reused from the checkpoint cache) and which
lessons still need to be generated.

Design notes
------------
- The manifest is **ordered** (leaves → roots).  Lesson N depends on the
  ``concepts_introduced`` state from lessons 1..N-1.  We therefore resume from
  the first *contiguous* gap in the cache, not from every individual missing
  lesson.  A gap in the middle (e.g. lessons 1 + 3 cached, 2 missing) forces
  re-generation from lesson 2 onward to preserve narrative coherence.
- All functions are pure (no I/O), making them trivially testable.
"""

from __future__ import annotations

from wiedunflow.entities.lesson_manifest import LessonManifest, LessonSpec


def slice_manifest_at_first_incomplete(
    manifest: LessonManifest,
    cached_lesson_ids: set[str],
) -> tuple[tuple[str, ...], tuple[LessonSpec, ...]]:
    """Partition a manifest into already-cached lessons and lessons to generate.

    Scans the manifest in order and returns a split at the *first* lesson whose
    ID is absent from *cached_lesson_ids*.  Any lessons after that point are
    included in ``todo_specs`` regardless of their individual cache status,
    because their narrative context depends on all prior lessons being present.

    Args:
        manifest: The full lesson manifest produced by Stage 4 (planning).
        cached_lesson_ids: Set of lesson IDs that are already persisted in the
            checkpoint cache (from :meth:`SQLiteCache.load_checkpoints`).

    Returns:
        A 2-tuple ``(reused_ids, todo_specs)`` where:
        - ``reused_ids`` is an ordered tuple of lesson IDs that are in the cache
          *and* precede the first missing lesson.
        - ``todo_specs`` is an ordered tuple of :class:`LessonSpec` objects
          starting from the first missing lesson to the end of the manifest.

    Examples:
        >>> # All lessons cached → nothing to do
        >>> reused, todo = slice_manifest_at_first_incomplete(manifest, {"L1", "L2", "L3"})
        >>> assert reused == ("L1", "L2", "L3") and todo == ()

        >>> # No lessons cached → everything is todo
        >>> reused, todo = slice_manifest_at_first_incomplete(manifest, set())
        >>> assert reused == () and len(todo) == len(manifest.lessons)

        >>> # Gap: lessons 1+3 cached but not 2 → resume from position 2
        >>> reused, todo = slice_manifest_at_first_incomplete(manifest, {"L1", "L3"})
        >>> assert reused == ("L1",) and todo[0].id == "L2"
    """
    reused: list[str] = []
    for spec in manifest.lessons:
        if spec.id in cached_lesson_ids:
            reused.append(spec.id)
        else:
            # First incomplete lesson found — everything from here goes to todo
            first_incomplete_idx = len(reused)
            todo_specs = tuple(manifest.lessons[first_incomplete_idx:])
            return tuple(reused), todo_specs

    # All lessons were in the cache
    return tuple(reused), ()
