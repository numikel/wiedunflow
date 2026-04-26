# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["SkippedLesson"]


class SkippedLesson(BaseModel):
    """Marker type for a lesson that failed grounding retry and becomes a placeholder in HTML.

    A ``SkippedLesson`` is produced by :func:`narrate_with_grounding_retry` when
    both the initial narration attempt and the single reinforcement retry fail
    grounding validation or word-count validation.  It is rendered as a
    dashed-border placeholder block in the HTML output (US-031).

    Attributes:
        lesson_id: The ``LessonSpec.id`` of the failed lesson.
        title: Human-readable lesson title (carried from ``LessonSpec``).
        missing_symbols: Symbols referenced in the LLM output that were absent
            from the AST snapshot's ``allowed_symbols`` set.
        reason: Machine-readable failure reason code.
    """

    model_config = ConfigDict(frozen=True)

    lesson_id: str
    title: str
    missing_symbols: tuple[str, ...]  # symbols that did not pass grounding
    reason: str = "grounding_retry_exhausted"
