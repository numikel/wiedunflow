# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from wiedunflow.entities.lesson import Lesson


class LessonPlan(BaseModel):
    """Ordered collection of lessons produced by the generation stage."""

    model_config = ConfigDict(frozen=True)

    lessons: tuple[Lesson, ...]
    concepts_introduced: tuple[str, ...]  # cumulative across all lessons
    repo_commit_hash: str = "unknown"
    repo_branch: str = "unknown"

    @model_validator(mode="after")
    def validate_lesson_ids_unique(self) -> Self:
        """Lesson IDs must be globally unique within a plan."""
        ids = [lesson.id for lesson in self.lessons]
        if len(ids) != len(set(ids)):
            raise ValueError("Lesson IDs must be unique within a LessonPlan")
        return self

    @property
    def generated_count(self) -> int:
        """Number of lessons with status 'generated'."""
        return sum(1 for lesson in self.lessons if lesson.status == "generated")

    @property
    def skipped_count(self) -> int:
        """Number of lessons with status 'skipped'."""
        return sum(1 for lesson in self.lessons if lesson.status == "skipped")
