# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for §4 (Limits & Audience) and §5 (Summary & Launch) — Step 7."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wiedunflow.cli.menu import (
    _SUMMARY_CANCEL,
    _SUMMARY_LAUNCH,
    _ask_int,
    _format_cost_lines,
    _format_summary_lines,
    _heuristic_estimate,
    _subwizard_limits,
    _subwizard_summary_and_launch,
    _validate_int_in_range,
)
from tests.unit.cli._fake_menu_io import FakeMenuIO

# ---------------------------------------------------------------------------
# _validate_int_in_range / _ask_int
# ---------------------------------------------------------------------------


def test_validate_int_accepts_value_in_range() -> None:
    value, error = _validate_int_in_range("10", 1, 20)
    assert value == 10
    assert error is None


def test_validate_int_rejects_below_low() -> None:
    value, error = _validate_int_in_range("0", 1, 20)
    assert value is None
    assert error is not None and "between 1 and 20" in error


def test_validate_int_rejects_above_high() -> None:
    value, error = _validate_int_in_range("21", 1, 20)
    assert value is None
    assert error is not None and "between 1 and 20" in error


def test_validate_int_rejects_non_integer() -> None:
    value, error = _validate_int_in_range("abc", 1, 20)
    assert value is None
    assert "whole number" in (error or "")


def test_ask_int_retries_on_invalid() -> None:
    io = FakeMenuIO(responses=["xyz", "5"])

    result = _ask_int(io, "Concurrency:", default=10, low=1, high=20)

    assert result == 5


def test_ask_int_abort_returns_none() -> None:
    io = FakeMenuIO(responses=[None])

    assert _ask_int(io, "Concurrency:", default=10, low=1, high=20) is None


# ---------------------------------------------------------------------------
# _subwizard_limits
# ---------------------------------------------------------------------------


def test_subwizard_limits_skip_returns_defaults() -> None:
    io = FakeMenuIO(responses=[False])

    result = _subwizard_limits(io, saved=None)

    assert result == {
        "llm_concurrency": 10,
        "llm_max_retries": 5,
        "llm_max_wait_s": 60,
        "max_lessons": 30,
        "target_audience": "mid",
    }


def test_subwizard_limits_skip_with_saved_uses_saved() -> None:
    from wiedunflow.cli.config import CodeguideConfig

    saved = CodeguideConfig(
        llm_concurrency=15,
        llm_max_retries=7,
        llm_max_wait_s=90,
        max_lessons=20,
        target_audience="senior",
    )
    io = FakeMenuIO(responses=[False])

    result = _subwizard_limits(io, saved=saved)

    assert result == {
        "llm_concurrency": 15,
        "llm_max_retries": 7,
        "llm_max_wait_s": 90,
        "max_lessons": 20,
        "target_audience": "senior",
    }


def test_subwizard_limits_full_flow() -> None:
    io = FakeMenuIO(
        responses=[
            True,  # customize? yes
            "expert",  # audience
            "25",  # max_lessons
            "8",  # concurrency
            "3",  # retries
            "45",  # wait
        ]
    )

    result = _subwizard_limits(io, saved=None)

    assert result == {
        "llm_concurrency": 8,
        "llm_max_retries": 3,
        "llm_max_wait_s": 45,
        "max_lessons": 25,
        "target_audience": "expert",
    }


def test_subwizard_limits_abort_on_customize_prompt() -> None:
    io = FakeMenuIO(responses=[None])

    assert _subwizard_limits(io) is None


def test_subwizard_limits_abort_on_audience() -> None:
    io = FakeMenuIO(responses=[True, None])

    assert _subwizard_limits(io) is None


def test_subwizard_limits_abort_on_max_lessons() -> None:
    io = FakeMenuIO(responses=[True, "mid", None])

    assert _subwizard_limits(io) is None


# ---------------------------------------------------------------------------
# _heuristic_estimate / _format_summary_lines / _format_cost_lines
# ---------------------------------------------------------------------------


def test_heuristic_estimate_uses_file_count(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2", encoding="utf-8")

    estimate = _heuristic_estimate(tmp_path, max_lessons=30)

    assert estimate.symbols >= 5  # at minimum 1 file x 5 symbols
    assert estimate.lessons >= 1
    assert estimate.total_cost_usd > 0


def test_heuristic_estimate_capped_by_max_lessons(tmp_path: Path) -> None:
    """File count > max_lessons: lessons are clamped to max_lessons."""
    for i in range(50):
        (tmp_path / f"f{i}.py").write_text("x = 1", encoding="utf-8")

    estimate = _heuristic_estimate(tmp_path, max_lessons=10)

    assert estimate.lessons == 10


def test_heuristic_estimate_empty_repo(tmp_path: Path) -> None:
    estimate = _heuristic_estimate(tmp_path, max_lessons=30)

    # Even with 0 files, the heuristic must produce a non-zero estimate so the
    # cost gate has something to render rather than crashing on division by zero.
    assert estimate.symbols >= 1
    assert estimate.lessons >= 1


def test_format_summary_lines_rendering(tmp_path: Path) -> None:
    payload: dict[str, Any] = {
        "repo_path": tmp_path / "demo",
        "output_path": None,
        "llm_provider": "anthropic",
        "llm_model_plan": "claude-sonnet-4-6",
        "llm_model_narrate": "claude-opus-4-7",
        "llm_concurrency": 10,
        "max_lessons": 30,
        "target_audience": "mid",
        "exclude_patterns": ["tests/**"],
        "include_patterns": [],
    }

    lines = _format_summary_lines(payload)

    label_to_value = dict(lines)
    assert label_to_value["Provider"] == "anthropic"
    assert label_to_value["Audience"] == "mid"
    assert label_to_value["Output"] == "./tutorial.html (default)"
    assert "1 pattern" in label_to_value["Excludes"]
    assert label_to_value["Includes"] == "(none)"


def test_format_cost_lines_includes_total(tmp_path: Path) -> None:
    estimate = _heuristic_estimate(tmp_path, max_lessons=30)
    rows, total = _format_cost_lines(estimate)

    assert {label for label, _ in rows} == {"haiku", "opus"}
    assert total[0] == "TOTAL"
    assert "$" in total[1]


# ---------------------------------------------------------------------------
# _subwizard_summary_and_launch — Cancel path (does NOT call _launch_pipeline)
# ---------------------------------------------------------------------------


def _make_payload(repo_path: Path) -> dict[str, Any]:
    return {
        "repo_path": repo_path,
        "output_path": None,
        "llm_provider": "anthropic",
        "llm_model_plan": "claude-sonnet-4-6",
        "llm_model_narrate": "claude-opus-4-7",
        "llm_api_key": None,
        "llm_base_url": None,
        "llm_concurrency": 10,
        "llm_max_retries": 5,
        "llm_max_wait_s": 60,
        "max_lessons": 30,
        "target_audience": "mid",
        "exclude_patterns": [],
        "include_patterns": [],
    }


def test_summary_cancel_does_not_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[bool] = []

    def _fake_launch(_payload: dict[str, Any]) -> None:
        launched.append(True)

    monkeypatch.setattr("wiedunflow.cli.menu._launch_pipeline", _fake_launch)
    io = FakeMenuIO(responses=[_SUMMARY_CANCEL])

    _subwizard_summary_and_launch(io, _make_payload(tmp_path))

    assert launched == []


def test_summary_esc_does_not_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    launched: list[bool] = []
    monkeypatch.setattr(
        "wiedunflow.cli.menu._launch_pipeline",
        lambda _p: launched.append(True),
    )
    io = FakeMenuIO(responses=[None])

    _subwizard_summary_and_launch(io, _make_payload(tmp_path))

    assert launched == []


def test_summary_launch_calls_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "wiedunflow.cli.menu._launch_pipeline",
        lambda payload: captured.append(payload),
    )
    # After the pipeline returns, the wizard waits on Enter so the run report
    # stays visible — supply that ack as the second response.
    io = FakeMenuIO(responses=[_SUMMARY_LAUNCH, ""])
    payload = _make_payload(tmp_path)

    _subwizard_summary_and_launch(io, payload)

    assert len(captured) == 1
    assert captured[0]["repo_path"] == tmp_path


# ---------------------------------------------------------------------------
# End-to-end orchestrator test through _run_generate_from_menu (Cancel path)
# ---------------------------------------------------------------------------


def test_run_generate_from_menu_full_cancel_flow(
    git_repo_fixture: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end §1 → §2 → §3 → §4 → §5 cancel path with no saved config."""
    from wiedunflow.cli.menu import _run_generate_from_menu

    monkeypatch.setattr("wiedunflow.cli.menu._try_load_saved_config", lambda: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    launched: list[bool] = []
    monkeypatch.setattr(
        "wiedunflow.cli.menu._launch_pipeline",
        lambda _p: launched.append(True),
    )

    class _StubCatalog:
        def list_models(self) -> list[str]:
            return ["claude-opus-4-7", "claude-sonnet-4-6"]

    io = FakeMenuIO(
        responses=[
            # §1
            str(git_repo_fixture),
            "",
            # §2 — anthropic, env key set so no password prompt
            "anthropic",
            "claude-sonnet-4-6",
            "claude-opus-4-7",
            # §3 — skip
            False,
            # §4 — skip
            False,
            # §5 — cancel
            _SUMMARY_CANCEL,
        ]
    )

    _run_generate_from_menu(io, anthropic_catalog=_StubCatalog(), openai_catalog=_StubCatalog())

    assert launched == []


@pytest.fixture
def git_repo_fixture(tmp_path: Path) -> Path:
    """Tiny git repo for end-to-end orchestrator tests."""
    import subprocess

    repo = tmp_path / "demo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo
