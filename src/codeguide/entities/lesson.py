# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

LessonStatus = Literal["generated", "skipped"]


class Lesson(BaseModel):
    """A single generated lesson within a tutorial."""

    model_config = ConfigDict(frozen=True)

    id: str  # e.g. "lesson-001"
    title: str
    narrative: str  # markdown-formatted narration
    code_refs: tuple[str, ...] = ()  # CodeSymbol names referenced in this lesson
    status: LessonStatus = "generated"

    @model_validator(mode="after")
    def narrative_not_empty_when_generated(self) -> Self:
        """A generated lesson must carry non-empty narrative text."""
        if self.status == "generated" and not self.narrative.strip():
            raise ValueError("Generated lesson must have non-empty narrative")
        return self
