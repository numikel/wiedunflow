# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from wiedunflow.entities.code_ref import CodeRef
from wiedunflow.entities.doc_coverage import DocCoverage

__all__ = [
    "CodeRef",
    "LessonManifest",
    "LessonManifestValidationError",
    "LessonSpec",
    "ManifestMetadata",
    "validate_against_graph",
]


class ManifestMetadata(BaseModel):
    """Provenance and coverage metadata attached to every generated manifest.

    Carried into Stage 7 so the rendered HTML footer can surface schema_version,
    tool version, and documentation coverage metrics without re-computing them.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    wiedunflow_version: str
    total_lessons: int
    generated_at: datetime
    has_readme: bool = True
    doc_coverage: DocCoverage | None = None


class LessonSpec(BaseModel):
    """Single lesson specification returned by the LLM planning stage."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    teaches: str  # one-sentence learning objective
    prerequisites: tuple[str, ...] = ()  # lesson ids that must precede this one
    code_refs: tuple[CodeRef, ...] = ()  # structured references grounded in AST snapshot
    external_context_needed: bool = False
    # US-049: synthetic closing "Where to go next" lesson (+1 beyond max_lessons cap).
    # Closing specs have empty code_refs — grounding validation is skipped.
    is_closing: bool = False


class LessonManifest(BaseModel):
    """Full output of Stage 4 (planning) — returned by LLMProvider.plan().

    Invariants:
    - ``metadata.total_lessons`` must equal ``len(lessons)``.
    - Every ``code_refs[*].symbol`` must exist in the AST snapshot; enforced
      externally via :func:`validate_against_graph` (not here, because this
      model has no access to the allowed-symbols set).
    """

    model_config = ConfigDict(frozen=True)

    # Kept at root level for backward-compatibility with external JSON consumers
    # and the US-048 "schema_version in output JSON" requirement.
    schema_version: Literal["1.0.0"] = "1.0.0"
    lessons: tuple[LessonSpec, ...]
    metadata: ManifestMetadata

    @model_validator(mode="after")
    def validate_total_lessons_consistent(self) -> Self:
        if self.metadata.total_lessons != len(self.lessons):
            raise ValueError(
                f"metadata.total_lessons ({self.metadata.total_lessons}) "
                f"does not match len(lessons) ({len(self.lessons)})"
            )
        return self


# ---------------------------------------------------------------------------
# Grounding validation (external — requires allowed_symbols from Stage 3)
# ---------------------------------------------------------------------------


class LessonManifestValidationError(ValueError):
    """Raised when a manifest fails grounding against the AST snapshot."""

    def __init__(self, invalid_symbols: list[str], message: str = "") -> None:
        super().__init__(message or f"Invalid symbols: {invalid_symbols}")
        self.invalid_symbols = invalid_symbols


def validate_against_graph(
    manifest: LessonManifest,
    allowed_symbols: frozenset[str],
) -> None:
    """Raise :exc:`LessonManifestValidationError` if any code_ref symbol is not in *allowed_symbols*.

    This is the grounding invariant from ADR-0007: every symbol referenced in a
    lesson plan must exist in the AST snapshot produced by Stage 1-3.  The check
    is deliberately kept outside the Pydantic model because the model has no
    access to the allowed-symbol set at construction time.

    Args:
        manifest: Planning-stage output to validate.
        allowed_symbols: Frozenset of symbol names derived from ``RankedGraph``
            (excludes uncertain / dynamic-import / cyclic members).

    Raises:
        LessonManifestValidationError: If one or more symbols are not grounded.
    """
    invalid: list[str] = []
    for spec in manifest.lessons:
        for ref in spec.code_refs:
            if ref.symbol not in allowed_symbols:
                invalid.append(ref.symbol)
    if invalid:
        raise LessonManifestValidationError(
            invalid_symbols=invalid,
            message=f"Manifest references {len(invalid)} ungrounded symbols: {invalid[:5]}",
        )
