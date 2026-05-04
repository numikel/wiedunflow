# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Shared helper for parsing an LLM plan response into a LessonManifest.

Extracted from provider adapters to eliminate code duplication and fix
the hardcoded has_readme=True bug.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from wiedunflow import __version__
from wiedunflow.entities.lesson_manifest import LessonManifest, LessonSpec, ManifestMetadata


def parse_plan_response(raw: str, *, has_readme: bool = False) -> LessonManifest:
    """Parse an LLM JSON plan response into a fully-constructed LessonManifest.

    The LLM returns ``{"schema_version": "1.0.0", "lessons": [...]}`` — a subset
    of the full ``LessonManifest`` schema (``ManifestMetadata`` is server-side
    provenance that the LLM does not produce).  This function:

    1. Validates the ``lessons`` list via ``LessonSpec.model_validate``.
    2. Constructs ``ManifestMetadata`` using the current timestamp and version.
    3. Returns a fully-valid ``LessonManifest``.

    Args:
        raw: Raw JSON string returned by the LLM.
        has_readme: Whether the repository contains a README file.  Defaults to
            ``False`` — the correct value is known only during ingestion
            (Stage 1) and must be forwarded by the caller.  Hardcoding
            ``True`` here was the pre-extraction bug.

    Raises:
        pydantic.ValidationError: On schema mismatch in the LLM output.
        json.JSONDecodeError: On invalid JSON.
    """
    data: Any = json.loads(raw)
    raw_lessons: list[Any] = data.get("lessons", [])
    lessons: tuple[LessonSpec, ...] = tuple(LessonSpec.model_validate(spec) for spec in raw_lessons)
    metadata = ManifestMetadata(
        schema_version="1.0.0",
        wiedunflow_version=__version__,
        total_lessons=len(lessons),
        generated_at=datetime.now(UTC),
        has_readme=has_readme,
        doc_coverage=None,
    )
    return LessonManifest(
        schema_version="1.0.0",
        lessons=lessons,
        metadata=metadata,
    )
