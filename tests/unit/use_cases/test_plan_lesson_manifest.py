# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from codeguide.entities.code_ref import CodeRef
from codeguide.entities.lesson import Lesson
from codeguide.entities.lesson_manifest import (
    LessonManifest,
    LessonSpec,
    ManifestMetadata,
)
from codeguide.use_cases.plan_lesson_manifest import PlanningFatalError, plan_with_retry

# ---------------------------------------------------------------------------
# Stub LLM provider
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 20, 0, 0, 0, tzinfo=UTC)


class StubPlanLLM:
    """Minimal LLMProvider stub with configurable plan() responses."""

    def __init__(self, responses: list[LessonManifest | Exception]) -> None:
        self.responses: list[LessonManifest | Exception] = list(responses)
        self.calls: list[str] = []

    def plan(self, outline: str) -> LessonManifest:
        self.calls.append(outline)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def narrate(self, spec_json: str, concepts_introduced: tuple[str, ...]) -> Lesson:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_metadata(total_lessons: int) -> ManifestMetadata:
    return ManifestMetadata(
        codeguide_version="0.0.3",
        total_lessons=total_lessons,
        generated_at=_NOW,
        has_readme=True,
    )


def _make_manifest(symbols: list[str]) -> LessonManifest:
    specs = tuple(
        LessonSpec(
            id=f"lesson-{i:03d}",
            title=f"Lesson {i}",
            teaches=f"Teaching about {sym}",
            code_refs=(
                CodeRef(
                    file_path=Path("mod.py"),
                    symbol=sym,
                    line_start=1,
                    line_end=5,
                ),
            ),
        )
        for i, sym in enumerate(symbols, start=1)
    )
    return LessonManifest(
        schema_version="1.0.0",
        lessons=specs,
        metadata=_make_metadata(total_lessons=len(specs)),
    )


_ALLOWED = frozenset({"mod.add", "mod.subtract", "mod.main"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path_returns_manifest() -> None:
    manifest = _make_manifest(["mod.add", "mod.subtract"])
    stub = StubPlanLLM([manifest])
    result = plan_with_retry(stub, "outline", frozenset({"mod.add", "mod.subtract"}))
    assert result is manifest
    assert len(stub.calls) == 1


def test_first_fails_second_succeeds_returns_manifest() -> None:
    """ValidationError on attempt 1 → retry → success on attempt 2."""
    bad_manifest = _make_manifest(["mod.MISSING"])
    good_manifest = _make_manifest(["mod.add"])
    stub = StubPlanLLM([bad_manifest, good_manifest])
    result = plan_with_retry(stub, "outline", frozenset({"mod.add"}))
    assert result is good_manifest
    assert len(stub.calls) == 2


def test_ungrounded_symbol_triggers_retry() -> None:
    """Ungrounded symbol on attempt 1 → retry → clean manifest returned."""
    ungrounded = _make_manifest(["mod.DOES_NOT_EXIST"])
    grounded = _make_manifest(["mod.add"])
    stub = StubPlanLLM([ungrounded, grounded])
    result = plan_with_retry(stub, "outline", frozenset({"mod.add"}))
    assert result is grounded
    assert len(stub.calls) == 2


def test_two_consecutive_failures_raise_planning_fatal_error() -> None:
    bad = _make_manifest(["mod.GHOST"])
    stub = StubPlanLLM([bad, bad])
    with pytest.raises(PlanningFatalError) as exc_info:
        plan_with_retry(stub, "outline", frozenset({"mod.add"}))
    assert exc_info.value.attempts == 2
    assert len(stub.calls) == 2


def test_planning_fatal_error_carries_last_error_message() -> None:
    bad = _make_manifest(["nope"])
    stub = StubPlanLLM([bad, bad])
    with pytest.raises(PlanningFatalError) as exc_info:
        plan_with_retry(stub, "outline", frozenset())
    assert exc_info.value.last_error != ""


def test_reinforcement_prompt_contains_failure_marker() -> None:
    """The outline sent on the second attempt must contain the PREVIOUS ATTEMPT marker."""
    bad = _make_manifest(["mod.NOPE"])
    good = _make_manifest(["mod.add"])
    stub = StubPlanLLM([bad, good])
    plan_with_retry(stub, "original outline", frozenset({"mod.add"}))
    assert len(stub.calls) == 2
    retry_outline = stub.calls[1]
    assert "PREVIOUS ATTEMPT FAILED" in retry_outline


def test_reinforcement_prompt_contains_invalid_symbols() -> None:
    """The retry prompt must name the invalid symbol so the LLM can self-correct."""
    bad = _make_manifest(["mod.GHOST"])
    good = _make_manifest(["mod.add"])
    stub = StubPlanLLM([bad, good])
    plan_with_retry(stub, "outline", frozenset({"mod.add"}))
    retry_outline = stub.calls[1]
    assert "mod.GHOST" in retry_outline


def test_validation_error_from_pydantic_triggers_retry() -> None:
    """A raw ValidationError (e.g. bad JSON schema) also triggers the retry path."""
    ve = ValidationError.from_exception_data(
        title="LessonManifest",
        input_type="python",
        line_errors=[
            {
                "type": "missing",
                "loc": ("lessons",),
                "msg": "Field required",
                "input": {},
                "ctx": {},
                "url": "https://errors.pydantic.dev/2/v/missing",
            }
        ],
    )
    good = _make_manifest(["mod.add"])
    stub = StubPlanLLM([ve, good])
    result = plan_with_retry(stub, "outline", frozenset({"mod.add"}))
    assert result is good
    assert len(stub.calls) == 2
