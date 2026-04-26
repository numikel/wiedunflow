# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""S5 C0: NarrationSegment + CodeRef entities for structured narration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from wiedunflow.entities.lesson import CodeRef, Lesson, NarrationSegment


def test_narration_segment_is_frozen() -> None:
    segment = NarrationSegment(kind="p", text="hello")
    with pytest.raises(ValidationError):
        segment.text = "mutated"  # type: ignore[misc]


def test_narration_segment_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        NarrationSegment(kind="paragraph", text="hello")  # type: ignore[arg-type]


def test_narration_segment_accepts_code_ref() -> None:
    ref = CodeRef(file="src/x.py", lang="python", lines=("def f():",), highlight=(1,))
    segment = NarrationSegment(kind="p", text="explain", code_ref=ref)
    assert segment.code_ref is not None
    assert segment.code_ref.file == "src/x.py"
    assert segment.code_ref.highlight == (1,)


def test_lesson_with_segments() -> None:
    lesson = Lesson(
        id="lesson-001",
        title="Intro",
        narrative="narrative fallback",
        segments=(
            NarrationSegment(kind="p", text="first"),
            NarrationSegment(kind="p", text="second"),
        ),
    )
    assert len(lesson.segments) == 2
    assert lesson.confidence == "MEDIUM"


def test_lesson_confidence_literal() -> None:
    with pytest.raises(ValidationError):
        Lesson(
            id="x",
            title="x",
            narrative="x",
            confidence="VERY_HIGH",  # type: ignore[arg-type]
        )
