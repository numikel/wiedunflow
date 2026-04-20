# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import pytest
from pydantic import ValidationError

from codeguide.entities.lesson import Lesson
from codeguide.entities.lesson_plan import LessonPlan


def _lesson(lesson_id: str, title: str = "Test Lesson") -> Lesson:
    return Lesson(id=lesson_id, title=title, narrative="Content for " + lesson_id)


def test_lesson_plan_unique_ids() -> None:
    lessons = (_lesson("L-001"), _lesson("L-002"))
    plan = LessonPlan(lessons=lessons, concepts_introduced=("a", "b"))
    assert len(plan.lessons) == 2


def test_lesson_plan_duplicate_ids_raises() -> None:
    with pytest.raises(ValueError, match="unique"):
        LessonPlan(
            lessons=(_lesson("L-001"), _lesson("L-001")),
            concepts_introduced=(),
        )


def test_lesson_generated_empty_narrative_raises() -> None:
    with pytest.raises(ValidationError):
        Lesson(id="L-001", title="T", narrative="", status="generated")


def test_lesson_skipped_empty_narrative_ok() -> None:
    lesson = Lesson(id="L-001", title="T", narrative="", status="skipped")
    assert lesson.status == "skipped"


def test_lesson_plan_counts() -> None:
    lessons = (
        _lesson("L-001"),
        Lesson(id="L-002", title="Skipped", narrative="", status="skipped"),
    )
    plan = LessonPlan(lessons=lessons, concepts_introduced=())
    assert plan.generated_count == 1
    assert plan.skipped_count == 1
