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

__all__ = [
    "count_words",
    "narrate_with_grounding_retry",
    "truncate_at_sentence_boundary",
]

logger = structlog.get_logger(__name__)

_MIN_WORDS = 150
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


def _spec_to_json(spec: LessonSpec) -> str:
    """Serialise *spec* to the JSON string expected by ``LLMProvider.narrate``."""
    return json.dumps(
        {
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
                }
                for ref in spec.code_refs
            ],
        }
    )


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
) -> str:
    """Build the reinforcement prompt JSON for the retry call.

    Appends a ``grounding_error`` field to the spec JSON so the LLM provider
    can inject it into the narration prompt.  Mirrors the pattern used in
    :func:`~codeguide.use_cases.plan_lesson_manifest._build_reinforcement` for
    consistency (ADR-0007).
    """
    allowed_preview = ", ".join(sorted(allowed_symbols)[:30])
    invalid_preview = ", ".join(invalid_symbols[:20]) if invalid_symbols else "(word count too low)"
    base = json.loads(_spec_to_json(spec))
    base["grounding_error"] = (
        f"Your previous response referenced these non-existent symbols: {invalid_preview}. "
        f"Rewrite the lesson using ONLY symbols from this AST slice: {allowed_preview}"
    )
    return json.dumps(base)


def _validate_lesson(
    lesson: Lesson,
    allowed_symbols: frozenset[str],
) -> tuple[bool, list[str], bool]:
    """Check a lesson for grounding validity and word count.

    Args:
        lesson: The generated lesson to validate.
        allowed_symbols: Set of permitted symbol names; empty set means no grounding
            constraint (closing lesson).

    Returns:
        ``(ok, invalid_symbols, word_count_low)`` where *ok* is ``True`` when
        the lesson passes all checks, *invalid_symbols* is the list of failing
        symbol names, and *word_count_low* is ``True`` when the word count is
        below :data:`_MIN_WORDS`.
    """
    wc = count_words(lesson.narrative)
    word_count_low = wc < _MIN_WORDS
    invalid = _validate_grounding(lesson, allowed_symbols)
    ok = not word_count_low and not invalid
    return ok, invalid, word_count_low


def narrate_with_grounding_retry(
    spec: LessonSpec,
    allowed_symbols: frozenset[str],
    llm: LLMProvider,
    concepts_introduced: tuple[str, ...],
) -> Lesson | SkippedLesson:
    """Narrate a single lesson spec with one grounding-reinforcement retry.

    Algorithm (US-030 / US-031 / US-034):

    1. Call ``llm.narrate(spec_json, concepts_introduced)`` → ``lesson``.
    2. Word-count validate (US-034):
       - ``> 1200`` words → truncate at sentence boundary → return.
       - ``< 150`` words → treat as failure, proceed to retry.
    3. Grounding validate (US-030):
       - All ``lesson.code_refs`` ⊆ ``allowed_symbols`` → return.
    4. On any failure: build reinforcement prompt; call ``llm.narrate`` once more.
    5. Validate again.  Pass → return ``lesson``.  Fail → return
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

    Returns:
        A :class:`~codeguide.entities.lesson.Lesson` on success or a
        :class:`~codeguide.entities.skipped_lesson.SkippedLesson` on double failure.
    """
    spec_json = _spec_to_json(spec)

    # --- Attempt 1 ---
    lesson = llm.narrate(spec_json, concepts_introduced)

    # Word-count upper bound: truncate silently (US-034 AC2).
    if count_words(lesson.narrative) > _MAX_WORDS:
        truncated_narrative = truncate_at_sentence_boundary(lesson.narrative)
        lesson = lesson.model_copy(update={"narrative": truncated_narrative})
        logger.info(
            "lesson_truncated",
            lesson_id=spec.id,
            original_words=count_words(lesson.narrative),
        )

    ok, invalid, word_count_low = _validate_lesson(lesson, allowed_symbols)
    if ok:
        logger.debug("lesson_grounded_first_attempt", lesson_id=spec.id)
        return lesson

    logger.warning(
        "lesson_grounding_failed_attempt_1",
        lesson_id=spec.id,
        invalid_symbols=invalid,
        word_count_low=word_count_low,
    )

    # --- Attempt 2 (reinforcement retry) ---
    reinforced_json = _build_reinforcement_spec_json(spec, invalid, allowed_symbols)
    lesson2 = llm.narrate(reinforced_json, concepts_introduced)

    # Word-count upper bound on retry.
    if count_words(lesson2.narrative) > _MAX_WORDS:
        truncated_narrative2 = truncate_at_sentence_boundary(lesson2.narrative)
        lesson2 = lesson2.model_copy(update={"narrative": truncated_narrative2})

    ok2, invalid2, word_count_low2 = _validate_lesson(lesson2, allowed_symbols)
    if ok2:
        logger.info("lesson_grounded_after_retry", lesson_id=spec.id)
        return lesson2

    # Both attempts failed — produce SkippedLesson placeholder.
    all_invalid = list({*invalid, *invalid2})
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
