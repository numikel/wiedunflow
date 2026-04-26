# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from wiedunflow.adapters import (
    FakeClock,
    FakeLLMProvider,
    InMemoryCache,
    StubBm25Store,
    StubJediResolver,
    StubRanker,
    StubTreeSitterParser,
)
from wiedunflow.entities.lesson_manifest import LessonSpec, ManifestMetadata
from wiedunflow.use_cases.generate_tutorial import Providers, generate_tutorial

_TINY_REPO = Path(__file__).parent.parent.parent / "fixtures" / "tiny_repo"
_NOW = datetime(2026, 4, 20, 0, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metadata(total_lessons: int) -> ManifestMetadata:
    return ManifestMetadata(
        codeguide_version="0.0.3",
        total_lessons=total_lessons,
        generated_at=_NOW,
        has_readme=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_us_049_closing_lesson_appended_to_output(tmp_path: Path) -> None:
    """AC1: Final closing lesson generated and appended to tutorial HTML."""
    output = tmp_path / "tutorial.html"
    providers = Providers(
        llm=FakeLLMProvider(),
        parser=StubTreeSitterParser(),
        resolver=StubJediResolver(),
        ranker=StubRanker(),
        vector_store=StubBm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )
    generate_tutorial(_TINY_REPO, providers, output_path=output)
    html = output.read_text(encoding="utf-8")
    # The closing lesson must appear in the rendered HTML.
    assert "lesson-closing" in html or "Where to go next" in html


def test_us_049_closing_lesson_is_beyond_cap(tmp_path: Path) -> None:
    """AC1 / decision: Closing lesson is +1 beyond regular cap.

    v0.3.0: when the repo has a README, an additional standalone "Project README"
    lesson is appended after the closing one. The tiny_repo fixture ships a
    README, so the expected total is 3 regular + 1 closing + 1 README = 5.
    """
    output = tmp_path / "tutorial.html"
    providers = Providers(
        llm=FakeLLMProvider(),
        parser=StubTreeSitterParser(),
        resolver=StubJediResolver(),
        ranker=StubRanker(),
        vector_store=StubBm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )
    generate_tutorial(_TINY_REPO, providers, output_path=output, max_lessons=3)
    html = output.read_text(encoding="utf-8")
    # Sprint 5 ADR-0009: lessons live in their own script block.
    data_start = html.find('id="tutorial-lessons"')
    json_start = html.find(">", data_start) + 1
    json_end = html.find("</script>", json_start)
    lessons = json.loads(html[json_start:json_end])
    # 3 regular + 1 closing + 1 README = 5 (README appended because the
    # tiny_repo fixture ships a README.md).
    assert len(lessons) == 5
    # Closing must still come BEFORE the README appendix lesson.
    ids = [lsn["id"] for lsn in lessons]
    assert ids[-2] == "lesson-closing"
    assert ids[-1] == "lesson-readme"


def test_us_049_closing_lesson_is_closing_flag_in_spec() -> None:
    """AC: LessonSpec with is_closing=True exists and has correct defaults."""
    spec = LessonSpec(
        id="lesson-closing",
        title="Where to go next",
        teaches="Further reading",
        code_refs=(),
        is_closing=True,
    )
    assert spec.is_closing is True
    assert spec.code_refs == ()


def test_us_049_closing_lesson_same_grounding_validation(tmp_path: Path) -> None:
    """AC3: Closing lesson subject to same grounding validation."""
    output = tmp_path / "tutorial.html"
    providers = Providers(
        llm=FakeLLMProvider(),
        parser=StubTreeSitterParser(),
        resolver=StubJediResolver(),
        ranker=StubRanker(),
        vector_store=StubBm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )
    generate_tutorial(_TINY_REPO, providers, output_path=output)
    html = output.read_text(encoding="utf-8")
    # Sprint 5 ADR-0009: closing lesson carries status="generated" in the new
    # per-lesson script block (the ``is_skipped`` legacy field was removed).
    json_start = html.find('id="tutorial-lessons"')
    content_start = html.find(">", json_start) + 1
    content_end = html.find("</script>", content_start)
    lessons = json.loads(html[content_start:content_end])
    closing_lessons = [lesson for lesson in lessons if lesson["id"] == "lesson-closing"]
    assert len(closing_lessons) == 1
    assert closing_lessons[0]["status"] == "generated"
