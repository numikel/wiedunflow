# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class LessonSpec(BaseModel):
    """Single lesson specification returned by the LLM planning stage."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    teaches: str  # one-sentence learning objective
    prerequisites: tuple[str, ...] = ()  # lesson ids that must precede this one
    code_refs: tuple[str, ...] = ()  # CodeSymbol names this lesson will reference
    external_context_needed: bool = False


class LessonManifest(BaseModel):
    """Full output of Stage 5 (planning) — returned by LLMProvider.plan()."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    lessons: tuple[LessonSpec, ...]
