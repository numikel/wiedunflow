# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 5 follow-up: full enforcement of --dry-run / --review-plan / --max-cost.

Exercises ``generate_tutorial(dry_run=..., review_plan=..., max_cost_usd=...)``
end-to-end via the walking-skeleton stubs + FakeLLMProvider so the tests stay
deterministic and offline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from wiedunflow.adapters import (
    FakeClock,
    FakeLLMProvider,
    InMemoryCache,
    StubBm25Store,
    StubJediResolver,
    StubRanker,
    StubTreeSitterParser,
)
from wiedunflow.use_cases.generate_tutorial import (
    MaxCostExceededError,
    Providers,
    generate_tutorial,
)

_TINY_REPO = Path(__file__).parent.parent / "fixtures" / "tiny_repo"


def _providers() -> Providers:
    return Providers(
        llm=FakeLLMProvider(),
        parser=StubTreeSitterParser(),
        resolver=StubJediResolver(),
        ranker=StubRanker(),
        vector_store=StubBm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )


class TestDryRun:
    """US-015: --dry-run skips Stages 5-6 and emits a preview HTML."""

    def test_dry_run_writes_preview_file(self, tmp_path: Path) -> None:
        output = tmp_path / "tutorial.html"
        result = generate_tutorial(_TINY_REPO, _providers(), output_path=output, dry_run=True)
        assert result.output_path.name == "tutorial-preview.html"
        assert result.output_path.exists()
        assert result.skipped_lessons == ()
        assert result.degraded is False

    def test_dry_run_preview_lessons_have_preview_prefix(self, tmp_path: Path) -> None:
        output = tmp_path / "tutorial.html"
        result = generate_tutorial(_TINY_REPO, _providers(), output_path=output, dry_run=True)
        html = result.output_path.read_text(encoding="utf-8")
        # Every lesson narration gets the [preview] marker.
        assert "[preview]" in html

    def test_dry_run_embeds_expected_lesson_count(self, tmp_path: Path) -> None:
        output = tmp_path / "tutorial.html"
        result = generate_tutorial(_TINY_REPO, _providers(), output_path=output, dry_run=True)
        html = result.output_path.read_text(encoding="utf-8")
        start = html.find('id="tutorial-lessons"')
        payload_start = html.find(">", start) + 1
        payload_end = html.find("</script>", payload_start)
        lessons = json.loads(html[payload_start:payload_end])
        # FakeLLMProvider produces 3 regular lessons; dry-run renders them as previews.
        assert result.total_planned == len(lessons)
        assert all(lesson["status"] == "generated" for lesson in lessons)


class TestMaxCostPreflight:
    """US-019: --max-cost aborts before any Stage 5/6 LLM call when the estimate exceeds the cap."""

    def test_tight_cap_raises_before_generation(self, tmp_path: Path) -> None:
        output = tmp_path / "tutorial.html"
        with pytest.raises(MaxCostExceededError) as excinfo:
            generate_tutorial(
                _TINY_REPO,
                _providers(),
                output_path=output,
                max_cost_usd=0.0001,
            )
        # Pre-flight abort — no HTML file written.
        assert not output.exists()
        assert excinfo.value.cap_usd == pytest.approx(0.0001)
        assert excinfo.value.estimate_usd > 0

    def test_generous_cap_allows_run(self, tmp_path: Path) -> None:
        output = tmp_path / "tutorial.html"
        result = generate_tutorial(
            _TINY_REPO,
            _providers(),
            output_path=output,
            max_cost_usd=1000.0,
        )
        assert result.output_path.exists()
        assert result.total_planned >= 1


class TestReviewPlan:
    """US-016: --review-plan writes the manifest, opens $EDITOR, and re-validates on save."""

    def test_review_plan_invokes_editor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[Path] = []

        def fake_editor(path: Path) -> int:
            calls.append(path)
            return 0  # user saved without modifications

        gt_mod = sys.modules["wiedunflow.use_cases.generate_tutorial"]
        monkeypatch.setattr(gt_mod, "_open_in_editor", fake_editor)

        output = tmp_path / "tutorial.html"
        result = generate_tutorial(
            _TINY_REPO,
            _providers(),
            output_path=output,
            review_plan=True,
        )
        assert len(calls) == 1
        assert calls[0].name == "manifest.edited.json"
        assert calls[0].parent.name == ".codeguide"
        assert result.output_path.exists()

    def test_review_plan_handles_invalid_edit_gracefully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An invalid manifest edit must fall back to the original planner output,
        not crash the run."""

        def fake_editor(path: Path) -> int:
            path.write_text("{ not valid json }", encoding="utf-8")
            return 0

        gt_mod = sys.modules["wiedunflow.use_cases.generate_tutorial"]
        monkeypatch.setattr(gt_mod, "_open_in_editor", fake_editor)

        output = tmp_path / "tutorial.html"
        result = generate_tutorial(
            _TINY_REPO,
            _providers(),
            output_path=output,
            review_plan=True,
        )
        assert result.output_path.exists()
        assert result.total_planned >= 1
