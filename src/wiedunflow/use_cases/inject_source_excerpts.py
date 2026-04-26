# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Inject raw source excerpts into primary CodeRef entries.

After Stage 5 (planning) the planner knows *which* symbols each lesson
covers, but the narration prompt only receives ``{symbol, file, line_start,
line_end, role}`` — no actual code.  This module reads the real source lines
from disk and attaches them as ``source_excerpt`` so the narration LLM can
quote exact signatures instead of inventing them.

Design decisions:
- Only ``role == "primary"`` refs with span < *primary_max_lines* are injected.
  Larger bodies would bloat the prompt past acceptable token counts (ADR context
  budget: ~4500 tokens for 30 lessons x 30 lines).
- File reads are cached within a single call via a ``dict[str, list[str]]``
  so each unique file is opened at most once per ``inject_source_excerpts`` call.
- Pydantic models are immutable (``frozen=True``) — we use ``model_copy(update={})``
  chains to rebuild CodeRef, LessonSpec, and LessonManifest without mutation.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from wiedunflow.entities.code_ref import CodeRef
from wiedunflow.entities.lesson_manifest import LessonManifest, LessonSpec

__all__ = ["inject_source_excerpts"]

logger = structlog.get_logger(__name__)

# Must match Field(max_length=4000) on CodeRef.source_excerpt.
_EXCERPT_MAX_LEN = 4000


def inject_source_excerpts(
    manifest: LessonManifest,
    repo_root: Path,
    *,
    primary_max_lines: int = 30,
) -> LessonManifest:
    """Return a manifest where primary code_refs with short spans have ``source_excerpt`` populated.

    For every ``CodeRef`` where:
    - ``role == "primary"``
    - ``(line_end - line_start) < primary_max_lines``

    the function reads raw file lines ``[line_start-1 : line_end]`` (1-indexed
    to 0-indexed conversion) and joins them with ``\\n`` to populate
    ``source_excerpt``.

    File reads are cached per call — each unique ``file_path`` is opened at most
    once, even when multiple refs point to the same file.

    Pydantic models are immutable; this function builds new instances via
    ``model_copy(update={...})`` rather than mutating in place.

    Args:
        manifest: The planning-stage output whose ``code_refs`` will be enriched.
        repo_root: Absolute path to the repository root.  ``CodeRef.file_path``
            values are resolved relative to this root.
        primary_max_lines: Maximum body span (``line_end - line_start``) for
            which an excerpt is injected.  Refs with larger bodies are skipped
            to keep prompt token counts bounded.  Defaults to 30.

    Returns:
        A new :class:`~wiedunflow.entities.lesson_manifest.LessonManifest` with
        ``source_excerpt`` populated where eligible.  The original manifest is
        not mutated.
    """
    # Cache: absolute-path string → list of raw lines (without trailing newline).
    file_cache: dict[str, list[str]] = {}

    def _get_lines(file_path: Path) -> list[str] | None:
        """Return cached lines for *file_path*, loading from disk on first access."""
        abs_path = (repo_root / file_path).resolve()
        key = str(abs_path)
        if key not in file_cache:
            try:
                file_cache[key] = abs_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError as exc:
                logger.warning(
                    "inject_source_excerpts_read_error",
                    file=str(abs_path),
                    error=str(exc),
                )
                file_cache[key] = []
        lines = file_cache[key]
        return lines if lines else None

    def _inject_ref(ref: CodeRef) -> CodeRef:
        """Inject excerpt into a single CodeRef if eligible; return unchanged otherwise."""
        span = ref.line_end - ref.line_start
        if ref.role != "primary" or span >= primary_max_lines:
            return ref
        lines = _get_lines(ref.file_path)
        if lines is None:
            return ref
        # Convert 1-indexed [line_start, line_end] to 0-indexed slice.
        slice_start = max(0, ref.line_start - 1)
        slice_end = min(len(lines), ref.line_end)
        excerpt = "\n".join(lines[slice_start:slice_end])
        if not excerpt:
            return ref
        # Enforce max_length from Field(max_length=4000).
        if len(excerpt) > _EXCERPT_MAX_LEN:
            excerpt = excerpt[:_EXCERPT_MAX_LEN]
        logger.debug(
            "inject_source_excerpt",
            symbol=ref.symbol,
            lines=f"{ref.line_start}-{ref.line_end}",
        )
        return ref.model_copy(update={"source_excerpt": excerpt})

    def _inject_spec(spec: LessonSpec) -> LessonSpec:
        """Rebuild a LessonSpec with injected code_refs."""
        new_refs = tuple(_inject_ref(r) for r in spec.code_refs)
        if new_refs == spec.code_refs:
            return spec
        return spec.model_copy(update={"code_refs": new_refs})

    new_lessons = tuple(_inject_spec(s) for s in manifest.lessons)
    if new_lessons == manifest.lessons:
        return manifest

    injected_count = sum(
        1 for spec in new_lessons for ref in spec.code_refs if ref.source_excerpt is not None
    )
    logger.info("inject_source_excerpts_done", injected_refs=injected_count)
    return manifest.model_copy(update={"lessons": new_lessons})
