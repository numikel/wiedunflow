# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

LessonStatus = Literal["generated", "skipped"]
SegmentKind = Literal["p", "code"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


class CodeRef(BaseModel):
    """A reference to a specific code location cited by a narration segment."""

    model_config = ConfigDict(frozen=True)

    file: str
    lang: str = "python"
    lines: tuple[str, ...] = ()
    highlight: tuple[int, ...] = ()


class NarrationSegment(BaseModel):
    """One entry in a lesson's narration stream (S5 structured narration).

    Desktop renders `p` segments in narration column and `code` segments / `code_ref`
    targets in code column. Mobile (<1024px) interleaves them in document order.
    """

    model_config = ConfigDict(frozen=True)

    kind: SegmentKind
    text: str
    code_ref: CodeRef | None = None


class Lesson(BaseModel):
    """A single generated lesson within a tutorial."""

    model_config = ConfigDict(frozen=True)

    id: str  # e.g. "lesson-001"
    title: str
    narrative: str  # markdown-formatted narration (backwards-compatible fallback)
    segments: tuple[NarrationSegment, ...] = ()  # S5 structured narration (optional)
    code_refs: tuple[str, ...] = ()  # CodeSymbol names referenced in this lesson
    status: LessonStatus = "generated"
    confidence: Confidence = "MEDIUM"

    @model_validator(mode="after")
    def narrative_not_empty_when_generated(self) -> Self:
        """A generated lesson must carry non-empty narrative text."""
        if self.status == "generated" and not self.narrative.strip():
            raise ValueError("Generated lesson must have non-empty narrative")
        return self
