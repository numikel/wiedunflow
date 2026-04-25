# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

LessonStatus = Literal["generated", "skipped"]
SegmentKind = Literal["p", "code", "html"]
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


class HelperAppendixEntry(BaseModel):
    """Lightweight reference to a trivial helper folded into the closing lesson.

    Populated by ``use_cases.skip_trivial.filter_trivial_helpers`` and rendered
    by Track B JS as a "Helper functions you'll see along the way" list.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    file_path: str
    line_start: int
    line_end: int


class Lesson(BaseModel):
    """A single generated lesson within a tutorial."""

    model_config = ConfigDict(frozen=True)

    id: str  # e.g. "lesson-001"
    title: str
    narrative: str  # markdown-formatted narration (backwards-compatible fallback)
    segments: tuple[NarrationSegment, ...] = ()  # S5 structured narration (optional)
    code_refs: tuple[str, ...] = ()  # CodeSymbol names referenced in this lesson
    helper_appendix: tuple[HelperAppendixEntry, ...] = ()  # v0.2.1 closing-lesson appendix
    # v0.3.0 layout/render overrides for non-narration lessons:
    # ``layout`` controls the split-view: ``"split"`` (default 2-pane),
    # ``"single"`` (code pane minimised, narration spans the row — used by the
    # closing "Where to go next" lesson). Renderer toggles a CSS class.
    layout: Literal["split", "single"] = "split"
    # ``code_panel_html`` overrides the right-hand code pane with arbitrary
    # pre-rendered HTML (sanitised by mistune at build time). Used by the
    # synthetic Project README lesson to surface the README in the code pane
    # while the narration column carries the title and a one-liner pointer.
    code_panel_html: str | None = None
    status: LessonStatus = "generated"
    confidence: Confidence = "MEDIUM"

    @model_validator(mode="after")
    def narrative_not_empty_when_generated(self) -> Self:
        """A generated lesson must carry non-empty narrative text."""
        if self.status == "generated" and not self.narrative.strip():
            raise ValueError("Generated lesson must have non-empty narrative")
        return self
