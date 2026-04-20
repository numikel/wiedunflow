# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import structlog
from pydantic import ValidationError

from codeguide.entities.lesson_manifest import (
    LessonManifest,
    LessonManifestValidationError,
    validate_against_graph,
)
from codeguide.interfaces.ports import LLMProvider

logger = structlog.get_logger(__name__)

_MAX_PLANNING_ATTEMPTS = 2


class PlanningFatalError(RuntimeError):
    """Raised when planning fails after the allowed retry budget is exhausted.

    The pipeline treats this as an unrecoverable failure (exit code 1).
    No partial/degraded tutorial is emitted — see ADR-0007.
    """

    def __init__(self, attempts: int, last_error: str) -> None:
        super().__init__(f"Planning failed after {attempts} attempts. Last error: {last_error}")
        self.attempts = attempts
        self.last_error = last_error


def plan_with_retry(
    llm: LLMProvider,
    outline: str,
    allowed_symbols: frozenset[str],
) -> LessonManifest:
    """Run the planning stage with one retry-with-reinforcement on validation failure.

    Retry budget: 1 extra attempt (2 total LLM calls max). On second failure,
    raises :exc:`PlanningFatalError` — there is no Stage 5 fallback (ADR-0007).

    Args:
        llm: The LLM provider implementing the ``plan`` method.
        outline: Code-graph outline string built by ``build_outline``.
        allowed_symbols: Frozenset of symbol names the manifest may reference.
            Derived from ``RankedGraph`` by :func:`_collect_allowed_symbols` in
            ``generate_tutorial``; excludes uncertain / dynamic-import / cyclic.

    Returns:
        A :class:`~codeguide.entities.lesson_manifest.LessonManifest` that
        passes grounding validation.

    Raises:
        PlanningFatalError: After exhausting the retry budget.
    """
    attempts = 0
    last_error = ""
    current_outline = outline

    while attempts < _MAX_PLANNING_ATTEMPTS:
        attempts += 1
        try:
            manifest = llm.plan(current_outline)
            validate_against_graph(manifest, allowed_symbols)
            logger.info("planning_ok", attempt=attempts, lessons=len(manifest.lessons))
            return manifest
        except (LessonManifestValidationError, ValidationError, ValueError) as exc:
            last_error = str(exc)
            logger.warning("planning_retry", attempt=attempts, error=last_error[:200])
            invalid_symbols: list[str] = getattr(exc, "invalid_symbols", [])
            current_outline = _build_reinforcement(
                outline, last_error, invalid_symbols, allowed_symbols
            )

    raise PlanningFatalError(attempts=attempts, last_error=last_error)


def _build_reinforcement(
    original_outline: str,
    error_msg: str,
    invalid_symbols: list[str],
    allowed_symbols: frozenset[str],
) -> str:
    """Construct the retry prompt by appending grounding-reinforcement instructions.

    Keeps the original outline intact and appends a clearly delimited section
    that names the failing symbols and the allowed subset, so the LLM can self-
    correct without re-processing the full codebase context.
    """
    allowed_preview = ", ".join(sorted(allowed_symbols)[:30])
    invalid_preview = ", ".join(invalid_symbols[:20]) if invalid_symbols else "(validation error)"
    return (
        f"{original_outline}\n\n"
        f"--- PREVIOUS ATTEMPT FAILED ---\n"
        f"Error: {error_msg[:500]}\n"
        f"Invalid symbols from last response: {invalid_preview}\n"
        f"You MUST use ONLY these allowed symbols "
        f"(top 30 shown, total={len(allowed_symbols)}): {allowed_preview}\n"
        f"Retry with corrected JSON output."
    )
