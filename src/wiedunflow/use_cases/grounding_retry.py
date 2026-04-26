# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import json
import re

import structlog

from codeguide.entities.lesson import Lesson
from codeguide.entities.lesson_manifest import LessonSpec
from codeguide.entities.skipped_lesson import SkippedLesson
from codeguide.interfaces.ports import LLMProvider
from codeguide.use_cases.snippet_validator import validate_narrative_snippets

__all__ = [
    "count_words",
    "narrate_with_grounding_retry",
    "truncate_at_sentence_boundary",
]

# Type alias used by the orchestrator to receive per-run hallucination data.
# A list[str] passed by the caller is mutated in-place so the orchestrator
# accumulates across all lesson calls without changing the return type.
HallucinationAccumulator = list[str]

logger = structlog.get_logger(__name__)

# v0.2.1: per-tier word count floors (replaces hard-coded _MIN_WORDS = 150).
_MIN_WORDS_DEFAULT = 150  # legacy fallback (no primary code_ref)
_MIN_WORDS_TRIVIAL = 80  # 2-9 lines
_MIN_WORDS_MODERATE = 220  # 10-30 lines
_MIN_WORDS_COMPLEX = 350  # >30 lines
# Kept for backward-compat — validators still use the tier logic, but
# callers may still reference this name in tests written before v0.2.1.
_MIN_WORDS = _MIN_WORDS_DEFAULT

# Span thresholds for word-count tier selection.
_SPAN_SINGLE_LINE = 1
_SPAN_TRIVIAL_MAX = 9  # inclusive upper bound for "trivial" tier (< 10 lines)
_SPAN_MODERATE_MAX = 30  # inclusive upper bound for "moderate" tier (<= 30 lines)

_MAX_WORDS = 1200

# Markdown constructs to strip before word counting.
_MD_STRIP_RE = re.compile(
    r"```.*?```"  # fenced code blocks
    r"|`[^`]+`"  # inline code
    r"|!\[.*?\]\(.*?\)"  # images
    r"|\[.*?\]\(.*?\)"  # links → keep link text implicitly via fallthrough
    r"|#{1,6}\s"  # ATX headings marker
    r"|\*{1,2}|_{1,2}"  # emphasis markers
    r"|>\s",  # blockquote markers
    re.DOTALL,
)

# Sentence boundary split pattern (US-034 AC2).
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def count_words(markdown: str) -> int:
    """Count words in a markdown string after stripping markdown syntax.

    Strips fenced code blocks, inline code, emphasis markers, heading markers,
    blockquote markers, and link syntax before splitting on whitespace.

    Args:
        markdown: Markdown-formatted text to count.

    Returns:
        Non-negative integer word count.
    """
    cleaned = _MD_STRIP_RE.sub(" ", markdown)
    return len(cleaned.split())


def truncate_at_sentence_boundary(text: str, max_words: int = _MAX_WORDS) -> str:
    """Truncate *text* so that it contains at most *max_words* words.

    Truncation happens at a sentence boundary (after ``.``, ``!``, or ``?``
    followed by whitespace) to avoid cutting off mid-sentence.  If no sentence
    boundary is found before *max_words* is exceeded, the text is hard-truncated
    at the word boundary.

    Args:
        text: Raw text (may contain markdown) to truncate.
        max_words: Maximum number of words to retain.

    Returns:
        Truncated string, never longer than *text*.
    """
    if count_words(text) <= max_words:
        return text

    # Split into sentences and accumulate until we would exceed the cap.
    sentences = _SENTENCE_SPLIT_RE.split(text)
    accumulated: list[str] = []
    total = 0
    for sentence in sentences:
        sentence_words = len(sentence.split())
        if total + sentence_words > max_words:
            break
        accumulated.append(sentence)
        total += sentence_words

    if accumulated:
        return " ".join(accumulated)

    # Fallback: hard word-boundary truncation (no sentence found in budget).
    words = text.split()
    return " ".join(words[:max_words])


def _floor_for_lesson(spec: LessonSpec, *, min_words_trivial: int) -> int:
    """Determine the minimum word count for a lesson based on its primary code_ref body span.

    Args:
        spec: The lesson spec to inspect for a primary code_ref.
        min_words_trivial: Configurable floor for 1-line spans (from
            ``config.narration_min_words_trivial``; default 50 per plan).

    Returns:
        Minimum word count integer.  Falls back to :data:`_MIN_WORDS_DEFAULT`
        when the spec has no primary code_ref.
    """
    primary = next((r for r in spec.code_refs if r.role == "primary"), None)
    if primary is None:
        return _MIN_WORDS_DEFAULT
    span = primary.line_end - primary.line_start + 1
    if span <= _SPAN_SINGLE_LINE:
        return min_words_trivial
    if span <= _SPAN_TRIVIAL_MAX:
        return _MIN_WORDS_TRIVIAL
    if span <= _SPAN_MODERATE_MAX:
        return _MIN_WORDS_MODERATE
    return _MIN_WORDS_COMPLEX


def _spec_to_json(spec: LessonSpec, *, project_context: str | None = None) -> str:
    """Serialise *spec* to the JSON string expected by ``LLMProvider.narrate``.

    Includes ``source_excerpt`` when populated so the narration LLM can quote
    exact signatures rather than inventing them (v0.2.1 anti-hallucination fix).

    When *project_context* is supplied (typically the README excerpt loaded by
    :func:`~codeguide.use_cases.readme_excerpt.load_readme_excerpt`), the LLM
    receives the project-level intent alongside the per-symbol code refs so
    it can keep narrations tight rather than padding with generic prose.
    """
    payload: dict[str, object] = {
        "id": spec.id,
        "title": spec.title,
        "teaches": spec.teaches,
        "is_closing": spec.is_closing,
        "code_refs": [
            {
                "file_path": str(ref.file_path),
                "symbol": ref.symbol,
                "line_start": ref.line_start,
                "line_end": ref.line_end,
                "role": ref.role,
                "source_excerpt": ref.source_excerpt,
            }
            for ref in spec.code_refs
        ],
    }
    if project_context:
        payload["project_context"] = project_context
    return json.dumps(payload)


def _validate_grounding(lesson: Lesson, allowed_symbols: frozenset[str]) -> list[str]:
    """Return list of ``lesson.code_refs`` symbols absent from *allowed_symbols*.

    For closing lessons (empty *allowed_symbols*), grounding is always satisfied.
    """
    if not allowed_symbols:
        return []
    return [sym for sym in lesson.code_refs if sym not in allowed_symbols]


def _build_reinforcement_spec_json(
    spec: LessonSpec,
    invalid_symbols: list[str],
    allowed_symbols: frozenset[str],
    *,
    project_context: str | None = None,
) -> str:
    """Build the reinforcement prompt JSON for the retry call.

    Appends a ``grounding_error`` field to the spec JSON so the LLM provider
    can inject it into the narration prompt.  Mirrors the pattern used in
    :func:`~codeguide.use_cases.plan_lesson_manifest._build_reinforcement` for
    consistency (ADR-0007).
    """
    allowed_preview = ", ".join(sorted(allowed_symbols)[:30])
    invalid_preview = ", ".join(invalid_symbols[:20]) if invalid_symbols else "(word count too low)"
    base = json.loads(_spec_to_json(spec, project_context=project_context))
    base["grounding_error"] = (
        f"Your previous response referenced these non-existent symbols: {invalid_preview}. "
        f"Rewrite the lesson using ONLY symbols from this AST slice: {allowed_preview}"
    )
    return json.dumps(base)


def _validate_lesson(
    lesson: Lesson,
    allowed_symbols: frozenset[str],
    *,
    min_words: int = _MIN_WORDS_DEFAULT,
) -> tuple[bool, list[str], bool]:
    """Check a lesson for grounding validity and word count.

    Args:
        lesson: The generated lesson to validate.
        allowed_symbols: Set of permitted symbol names; empty set means no grounding
            constraint (closing lesson).
        min_words: Minimum word count floor for this lesson (computed per-tier by
            :func:`_floor_for_lesson`).  Defaults to :data:`_MIN_WORDS_DEFAULT` (150).

    Returns:
        ``(ok, invalid_symbols, word_count_low)`` where *ok* is ``True`` when
        the lesson passes all checks, *invalid_symbols* is the list of failing
        symbol names, and *word_count_low* is ``True`` when the word count is
        below *min_words*.
    """
    wc = count_words(lesson.narrative)
    word_count_low = wc < min_words
    invalid = _validate_grounding(lesson, allowed_symbols)
    ok = not word_count_low and not invalid
    return ok, invalid, word_count_low


def narrate_with_grounding_retry(  # noqa: PLR0912 — grounding+snippet validation requires multiple branches
    spec: LessonSpec,
    allowed_symbols: frozenset[str],
    llm: LLMProvider,
    concepts_introduced: tuple[str, ...],
    *,
    hallucination_accumulator: HallucinationAccumulator | None = None,
    min_words_trivial: int = 50,
    snippet_validation: bool = True,
    project_context: str | None = None,
) -> Lesson | SkippedLesson:
    """Narrate a single lesson spec with one grounding-reinforcement retry.

    Algorithm (US-030 / US-031 / US-034 / v0.2.1):

    1. Call ``llm.narrate(spec_json, concepts_introduced)`` → ``lesson``.
    2. Word-count validate (US-034, v0.2.1 tiers):
       - ``> 1200`` words → truncate at sentence boundary → continue.
       - ``< floor`` words → treat as failure, proceed to retry.
         ``floor`` is determined per lesson by :func:`_floor_for_lesson` using
         the primary code_ref body span (1-liner=50, trivial=80, moderate=220,
         complex=350).
    3. Grounding validate (US-030):
       - All ``lesson.code_refs`` ⊆ ``allowed_symbols`` → continue.
    4. Snippet validation (v0.2.1, when *snippet_validation* is True):
       - Parse ```python fenced blocks; compare ``def`` signatures against
         ``source_excerpt`` in code_refs.  Mismatches trigger a retry with
         an explicit hint containing the real signature.
    5. On any failure: build reinforcement prompt; call ``llm.narrate`` once more.
    6. Validate again.  Pass → return ``lesson``.  Fail → return
       ``SkippedLesson(reason="grounding_retry_exhausted")``.

    Closing lessons (``spec.is_closing=True``) are narrated with an empty
    *allowed_symbols* set — grounding validation always passes, but word-count
    validation still applies.

    Args:
        spec: The ``LessonSpec`` to narrate.
        allowed_symbols: Frozenset of allowed symbol names from Stage 3.  Pass
            an empty frozenset for closing lessons (no grounding constraint).
        llm: Provider used to call :meth:`~codeguide.interfaces.ports.LLMProvider.narrate`.
        concepts_introduced: Concepts already taught; forwarded verbatim to
            each ``narrate`` call to prevent re-teaching.
        hallucination_accumulator: Optional mutable list into which any invalid
            symbol names discovered during either attempt are appended.  The
            orchestrator passes a shared list to collect per-run hallucination
            data without changing the return type of this function.  Duplicates
            are intentionally preserved; deduplication is the caller's concern.
        min_words_trivial: Minimum word count for 1-line-body lessons (configurable
            via ``config.narration_min_words_trivial``; default 50).
        snippet_validation: When ``True`` (default), validate ``def`` signatures
            in fenced code blocks against ``source_excerpt``.  When ``False``,
            skip snippet validation entirely (bypass for debugging / rollback).

    Returns:
        A :class:`~codeguide.entities.lesson.Lesson` on success or a
        :class:`~codeguide.entities.skipped_lesson.SkippedLesson` on double failure.
    """
    spec_json = _spec_to_json(spec, project_context=project_context)

    # Compute per-lesson minimum word count floor.
    min_words_floor = _floor_for_lesson(spec, min_words_trivial=min_words_trivial)

    # --- Attempt 1 ---
    lesson = llm.narrate(spec_json, concepts_introduced)

    # Word-count upper bound: truncate silently (US-034 AC2).
    # v0.3.0 Fix (P1 from code review): capture the pre-truncation word count
    # before model_copy reassigns ``lesson``, so ``original_words`` actually
    # reports the original — not the post-truncation length.
    original_wc = count_words(lesson.narrative)
    if original_wc > _MAX_WORDS:
        truncated_narrative = truncate_at_sentence_boundary(lesson.narrative)
        lesson = lesson.model_copy(update={"narrative": truncated_narrative})
        logger.info(
            "lesson_truncated",
            lesson_id=spec.id,
            original_words=original_wc,
            truncated_words=count_words(lesson.narrative),
        )

    ok, invalid, word_count_low = _validate_lesson(
        lesson, allowed_symbols, min_words=min_words_floor
    )

    # Snippet validation (v0.2.1): check fenced def signatures against source_excerpt.
    snippet_errors: list[str] = []
    if ok and snippet_validation:
        snippet_errors = validate_narrative_snippets(lesson.narrative, spec.code_refs)
        if snippet_errors:
            ok = False
            logger.warning(
                "lesson_snippet_validation_failed_attempt_1",
                lesson_id=spec.id,
                errors=snippet_errors[:5],
            )

    if ok:
        logger.debug("lesson_grounded_first_attempt", lesson_id=spec.id)
        return lesson

    # Push symbols from failed attempt 1 into the orchestrator accumulator so
    # that even retried-and-recovered lessons contribute to hallucination tracking
    # (US-065: hallucinated_symbols_count covers all invalid references, not only
    # those from ultimately-skipped lessons).
    if hallucination_accumulator is not None and invalid:
        hallucination_accumulator.extend(invalid)

    logger.warning(
        "lesson_grounding_failed_attempt_1",
        lesson_id=spec.id,
        invalid_symbols=invalid,
        word_count_low=word_count_low,
    )

    # --- Attempt 2 (reinforcement retry) ---
    # Build reinforcement prompt — include snippet hints when relevant.
    if snippet_errors and not invalid and not word_count_low:
        reinforced_json = _build_snippet_reinforcement_json(
            spec, snippet_errors, project_context=project_context
        )
    else:
        reinforced_json = _build_reinforcement_spec_json(
            spec, invalid, allowed_symbols, project_context=project_context
        )

    lesson2 = llm.narrate(reinforced_json, concepts_introduced)

    # Word-count upper bound on retry.
    if count_words(lesson2.narrative) > _MAX_WORDS:
        truncated_narrative2 = truncate_at_sentence_boundary(lesson2.narrative)
        lesson2 = lesson2.model_copy(update={"narrative": truncated_narrative2})

    ok2, invalid2, word_count_low2 = _validate_lesson(
        lesson2, allowed_symbols, min_words=min_words_floor
    )

    # Snippet validation on retry.
    if ok2 and snippet_validation:
        snippet_errors2 = validate_narrative_snippets(lesson2.narrative, spec.code_refs)
        if snippet_errors2:
            ok2 = False
            logger.warning(
                "lesson_snippet_validation_failed_attempt_2",
                lesson_id=spec.id,
                errors=snippet_errors2[:5],
            )

    if ok2:
        logger.info("lesson_grounded_after_retry", lesson_id=spec.id)
        return lesson2

    # Both attempts failed -- produce SkippedLesson placeholder.
    all_invalid = list({*invalid, *invalid2})

    # Push any new symbols from attempt 2 not already recorded from attempt 1.
    if hallucination_accumulator is not None:
        seen_from_attempt1 = set(invalid)
        for sym in invalid2:
            if sym not in seen_from_attempt1:
                hallucination_accumulator.append(sym)
    logger.error(
        "lesson_skipped_grounding_retry_exhausted",
        lesson_id=spec.id,
        missing_symbols=all_invalid,
        word_count_low_retry=word_count_low2,
    )
    return SkippedLesson(
        lesson_id=spec.id,
        title=spec.title,
        missing_symbols=tuple(all_invalid),
        reason="grounding_retry_exhausted",
    )


def _build_snippet_reinforcement_json(
    spec: LessonSpec,
    snippet_errors: list[str],
    *,
    project_context: str | None = None,
) -> str:
    """Build a reinforcement prompt focused on correcting misquoted function signatures.

    Used when the only failure reason is snippet-signature mismatch (grounding
    and word-count passed but the LLM paraphrased a ``def`` line incorrectly).

    Args:
        spec: The original lesson spec (with ``source_excerpt`` attached).
        snippet_errors: Human-readable error messages from :func:`validate_narrative_snippets`.
        project_context: Optional README excerpt threaded through the retry so the
            reinforcement prompt carries the same project intent as the first attempt.

    Returns:
        JSON string with a ``snippet_validation_error`` field appended to the
        serialised spec.
    """
    error_block = "\n".join(snippet_errors)
    base = json.loads(_spec_to_json(spec, project_context=project_context))
    base["snippet_validation_error"] = (
        f"Snippet validation failed:\n{error_block}\n"
        "Rewrite the affected ```python code blocks using the EXACT signatures "
        "from the source_excerpt fields in code_refs. "
        "Do NOT invent parameter names or change their order."
    )
    return json.dumps(base)
