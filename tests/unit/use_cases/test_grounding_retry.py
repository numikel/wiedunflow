# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path
from typing import Any

from wiedunflow.entities.code_ref import CodeRef
from wiedunflow.entities.lesson import Lesson
from wiedunflow.entities.lesson_manifest import LessonSpec
from wiedunflow.entities.skipped_lesson import SkippedLesson
from wiedunflow.use_cases.grounding_retry import (
    _MAX_WORDS,
    _MIN_WORDS_COMPLEX,
    _MIN_WORDS_DEFAULT,
    _MIN_WORDS_MODERATE,
    _MIN_WORDS_TRIVIAL,
    _floor_for_lesson,
    count_words,
    narrate_with_grounding_retry,
    truncate_at_sentence_boundary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALLOWED = frozenset({"mod.add", "mod.subtract", "mod.main"})


def _make_spec(
    lesson_id: str = "lesson-001",
    title: str = "Test Lesson",
    teaches: str = "something",
    symbol: str = "mod.add",
    is_closing: bool = False,
) -> LessonSpec:
    if is_closing:
        return LessonSpec(
            id=lesson_id,
            title=title,
            teaches=teaches,
            code_refs=(),
            is_closing=True,
        )
    return LessonSpec(
        id=lesson_id,
        title=title,
        teaches=teaches,
        code_refs=(
            CodeRef(
                file_path=Path("mod.py"),
                symbol=symbol,
                line_start=1,
                line_end=5,
            ),
        ),
    )


def _make_lesson(
    lesson_id: str = "lesson-001",
    title: str = "Test Lesson",
    code_refs: tuple[str, ...] = ("mod.add",),
    word_count: int = 200,
) -> Lesson:
    """Build a Lesson with exactly *word_count* words in the narrative."""
    words = " ".join(["word"] * word_count)
    narrative = f"## {title}\n\n{words}"
    return Lesson(
        id=lesson_id,
        title=title,
        narrative=narrative,
        code_refs=code_refs,
        status="generated",
    )


class StubNarrateLLM:
    """Configurable stub that records calls and returns pre-set Lesson responses."""

    def __init__(self, responses: list[Lesson | Exception]) -> None:
        self._responses: list[Lesson | Exception] = list(responses)
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def plan(self, outline: str) -> Any:
        raise NotImplementedError

    def describe_symbol(self, symbol: Any, context: str) -> str:
        raise NotImplementedError

    def narrate(self, spec_json: str, concepts_introduced: tuple[str, ...]) -> Lesson:
        self.calls.append((spec_json, concepts_introduced))
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


# ---------------------------------------------------------------------------
# count_words tests
# ---------------------------------------------------------------------------


def test_count_words_plain_text() -> None:
    assert count_words("hello world foo") == 3


def test_count_words_strips_fenced_code_block() -> None:
    text = "intro\n```python\nsome code here\n```\noutro"
    wc = count_words(text)
    # fenced block stripped; only "intro" and "outro" remain
    assert wc < 5


def test_count_words_strips_heading_markers() -> None:
    assert count_words("## My heading") < count_words("My heading   with extra") + 2


def test_count_words_empty() -> None:
    assert count_words("") == 0


# ---------------------------------------------------------------------------
# truncate_at_sentence_boundary tests
# ---------------------------------------------------------------------------


def test_truncate_at_sentence_boundary_no_truncation_needed() -> None:
    text = "Hello world."
    result = truncate_at_sentence_boundary(text, max_words=100)
    assert result == text


def test_truncate_at_sentence_boundary_truncates() -> None:
    sentences = ["Sentence one here." * 1, "Sentence two is long enough to matter."]
    text = "  ".join(sentences * 100)  # many sentences, definitely > 1200 words
    result = truncate_at_sentence_boundary(text, max_words=10)
    assert count_words(result) <= 15  # some tolerance for sentence boundary
    assert len(result) < len(text)


def test_truncate_at_sentence_boundary_fallback_on_no_period() -> None:
    # No sentence boundary present
    text = " ".join(["word"] * 1300)
    result = truncate_at_sentence_boundary(text, max_words=5)
    assert count_words(result) <= 5


# ---------------------------------------------------------------------------
# narrate_with_grounding_retry tests
# ---------------------------------------------------------------------------


def test_us_030_grounding_retry_pass_on_first_attempt() -> None:
    """AC: lesson grounded on first attempt → no retry, lesson returned."""
    lesson = _make_lesson(code_refs=("mod.add",))
    stub = StubNarrateLLM([lesson])
    spec = _make_spec(symbol="mod.add")
    result = narrate_with_grounding_retry(spec, _ALLOWED, stub, ())
    assert isinstance(result, Lesson)
    assert result is lesson
    assert len(stub.calls) == 1


def test_us_030_grounding_retry_once_on_hallucination_then_pass() -> None:
    """AC1/AC2: First attempt hallucinated symbol, retry succeeds → lesson accepted."""
    bad_lesson = _make_lesson(code_refs=("mod.HALLUCINATED",))
    good_lesson = _make_lesson(code_refs=("mod.add",))
    stub = StubNarrateLLM([bad_lesson, good_lesson])
    spec = _make_spec(symbol="mod.add")
    result = narrate_with_grounding_retry(spec, _ALLOWED, stub, ())
    assert isinstance(result, Lesson)
    assert result is good_lesson
    assert len(stub.calls) == 2


def test_us_030_grounding_retry_exactly_once() -> None:
    """AC1: Retry happens EXACTLY ONCE — no third attempt on double failure."""
    bad_lesson = _make_lesson(code_refs=("mod.GHOST",))
    stub = StubNarrateLLM([bad_lesson, bad_lesson])
    spec = _make_spec(symbol="mod.add")
    result = narrate_with_grounding_retry(spec, _ALLOWED, stub, ())
    assert isinstance(result, SkippedLesson)
    assert len(stub.calls) == 2  # exactly 2, not 3


def test_us_030_reinforcement_prompt_contains_invalid_symbols() -> None:
    """AC1: Reinforcement prompt must name the non-existent symbol."""
    bad_lesson = _make_lesson(code_refs=("mod.GHOST",))
    good_lesson = _make_lesson(code_refs=("mod.add",))
    stub = StubNarrateLLM([bad_lesson, good_lesson])
    spec = _make_spec(symbol="mod.add")
    narrate_with_grounding_retry(spec, _ALLOWED, stub, ())
    retry_spec_json = stub.calls[1][0]
    assert "mod.GHOST" in retry_spec_json


def test_us_030_retry_on_hallucination_fail_returns_skipped_lesson() -> None:
    """AC3: Double failure → SkippedLesson with reason=grounding_retry_exhausted."""
    bad_lesson = _make_lesson(code_refs=("mod.PHANTOM",))
    stub = StubNarrateLLM([bad_lesson, bad_lesson])
    spec = _make_spec(symbol="mod.add")
    result = narrate_with_grounding_retry(spec, _ALLOWED, stub, ())
    assert isinstance(result, SkippedLesson)
    assert result.reason == "grounding_retry_exhausted"
    assert "mod.PHANTOM" in result.missing_symbols


def test_us_034_word_count_below_150_triggers_retry() -> None:
    """AC1: Narrative < 150 words → triggers regeneration (retry)."""
    short_lesson = _make_lesson(code_refs=("mod.add",), word_count=50)
    good_lesson = _make_lesson(code_refs=("mod.add",), word_count=200)
    stub = StubNarrateLLM([short_lesson, good_lesson])
    spec = _make_spec(symbol="mod.add")
    result = narrate_with_grounding_retry(spec, _ALLOWED, stub, ())
    assert isinstance(result, Lesson)
    assert len(stub.calls) == 2


def test_us_034_word_count_above_1200_truncated_at_sentence_boundary() -> None:
    """AC2: Narrative > 1200 words → truncated at sentence boundary."""
    long_narrative = ". ".join(["This is a sentence with many filler words indeed"] * 100) + "."
    over_limit_lesson = Lesson(
        id="lesson-001",
        title="Test",
        narrative=long_narrative,
        code_refs=("mod.add",),
        status="generated",
    )
    stub = StubNarrateLLM([over_limit_lesson])
    spec = _make_spec(symbol="mod.add")
    result = narrate_with_grounding_retry(spec, _ALLOWED, stub, ())
    assert isinstance(result, Lesson)
    assert count_words(result.narrative) <= _MAX_WORDS + 20  # small tolerance for sentence boundary
    assert len(stub.calls) == 1  # no retry needed, just truncation


def test_us_030_concepts_introduced_forwarded_to_both_attempts() -> None:
    """Concepts already taught must be forwarded verbatim to both narrate calls."""
    prior_concepts = ("concept-A", "concept-B")
    bad_lesson = _make_lesson(code_refs=("mod.GHOST",))
    good_lesson = _make_lesson(code_refs=("mod.add",))
    stub = StubNarrateLLM([bad_lesson, good_lesson])
    spec = _make_spec(symbol="mod.add")
    narrate_with_grounding_retry(spec, _ALLOWED, stub, prior_concepts)
    assert stub.calls[0][1] == prior_concepts
    assert stub.calls[1][1] == prior_concepts


def test_closing_lesson_empty_allowed_symbols_always_passes_grounding() -> None:
    """Closing lesson with empty allowed_symbols → grounding validation skipped."""
    # Even with an arbitrary code_ref symbol, grounding passes when allowed is empty.
    lesson = _make_lesson(code_refs=("any.symbol.at.all",), word_count=200)
    stub = StubNarrateLLM([lesson])
    spec = _make_spec(is_closing=True)
    result = narrate_with_grounding_retry(spec, frozenset(), stub, ())
    assert isinstance(result, Lesson)
    assert len(stub.calls) == 1


# ---------------------------------------------------------------------------
# v0.2.1 — _floor_for_lesson tier scaling
# ---------------------------------------------------------------------------


def _spec_with_span(span: int, *, role: str = "primary") -> LessonSpec:
    """Build a LessonSpec whose primary code_ref covers *span* lines."""
    return LessonSpec(
        id="lesson-x",
        title="t",
        teaches="t",
        code_refs=(
            CodeRef(
                file_path=Path("a.py"),
                symbol="m.fn",
                line_start=1,
                line_end=span,  # span lines: 1..span inclusive
                role=role,  # type: ignore[arg-type]
            ),
        ),
    )


def test_floor_for_lesson_one_line_uses_min_words_trivial() -> None:
    """1-line span returns the configured min_words_trivial."""
    spec = _spec_with_span(1)
    assert _floor_for_lesson(spec, min_words_trivial=50) == 50
    assert _floor_for_lesson(spec, min_words_trivial=20) == 20


def test_floor_for_lesson_trivial_span_2_to_9() -> None:
    """Spans 2-9 use _MIN_WORDS_TRIVIAL (80)."""
    for span in (2, 5, 9):
        spec = _spec_with_span(span)
        assert _floor_for_lesson(spec, min_words_trivial=50) == _MIN_WORDS_TRIVIAL


def test_floor_for_lesson_moderate_span_10_to_30() -> None:
    """Spans 10-30 use _MIN_WORDS_MODERATE (220)."""
    for span in (10, 20, 30):
        spec = _spec_with_span(span)
        assert _floor_for_lesson(spec, min_words_trivial=50) == _MIN_WORDS_MODERATE


def test_floor_for_lesson_complex_span_above_30() -> None:
    """Spans >30 use _MIN_WORDS_COMPLEX (350)."""
    for span in (31, 50, 200):
        spec = _spec_with_span(span)
        assert _floor_for_lesson(spec, min_words_trivial=50) == _MIN_WORDS_COMPLEX


def test_floor_for_lesson_no_primary_ref_returns_default() -> None:
    """LessonSpec with only 'referenced' role refs returns the legacy 150 fallback."""
    spec = LessonSpec(
        id="lesson-y",
        title="t",
        teaches="t",
        code_refs=(
            CodeRef(
                file_path=Path("a.py"),
                symbol="m.fn",
                line_start=1,
                line_end=10,
                role="referenced",
            ),
        ),
    )
    assert _floor_for_lesson(spec, min_words_trivial=50) == _MIN_WORDS_DEFAULT


def test_floor_for_lesson_empty_code_refs_returns_default() -> None:
    """Closing-style spec with empty code_refs returns the legacy 150 fallback."""
    spec = LessonSpec(id="lesson-z", title="t", teaches="t", code_refs=(), is_closing=True)
    assert _floor_for_lesson(spec, min_words_trivial=50) == _MIN_WORDS_DEFAULT
