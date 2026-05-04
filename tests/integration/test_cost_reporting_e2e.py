# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Cost reporting end-to-end integration test.

Validates that total_cost_usd is propagated correctly through the pipeline:
  SpendMeter created in _run_pipeline
  → passed to generate_tutorial()
  → passed to _stage_generation()
  → passed to run_lesson() / run_closing_lesson()
  → FakeLLMProvider.run_agent() calls spend_meter.charge()
  → GenerationResult.total_cost_usd > 0
  → RunReport.total_cost_usd > 0 (written to run-report.json)
  → Success banner includes total_cost line

Uses FakeLLMProvider which now simulates 100+50 tokens per agent call.
"""

from __future__ import annotations

import json
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from wiedunflow.adapters.fake_llm_provider import FakeLLMProvider
from wiedunflow.cli.main import cli as cli_main

pytestmark = pytest.mark.integration

_TINY_REPO = Path(__file__).parent.parent / "fixtures" / "tiny_repo"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_repo_copy(tmp_path: Path) -> Path:
    """Clone ``tiny_repo`` into ``tmp_path`` so run-report writes are isolated."""
    dst = tmp_path / "tiny_repo"
    shutil.copytree(_TINY_REPO, dst)
    return dst


@pytest.fixture(autouse=True)
def _patch_llm_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap ``_build_llm_provider`` for the deterministic FakeLLMProvider."""
    monkeypatch.setattr(
        "wiedunflow.cli.main._build_llm_provider",
        lambda config, **_kwargs: FakeLLMProvider(),
    )


@pytest.fixture(autouse=True)
def _patch_sigint_handler_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace :class:`SigintHandler` with a no-op."""

    class _NoopHandler:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            event = threading.Event()
            self.should_finish = event

        def install(self) -> None:
            pass

        def restore(self) -> None:
            pass

    monkeypatch.setattr("wiedunflow.cli.main.SigintHandler", _NoopHandler)


def _invoke_cli(repo: Path, extra: list[str] | None = None) -> Any:
    """Run the CLI inside an isolated filesystem."""
    runner = CliRunner()
    argv = [str(repo), "--yes", *(extra or [])]
    with runner.isolated_filesystem():
        result = runner.invoke(cli_main, argv, standalone_mode=True)
    return result


def _load_report(repo: Path) -> dict[str, Any]:
    report_path = repo / ".wiedunflow" / "run-report.json"
    assert report_path.exists(), f"run-report.json missing at {report_path}"
    data: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    return data


# ---------------------------------------------------------------------------
# Test: SpendMeter is instantiated and total_cost_usd is > 0
# ---------------------------------------------------------------------------


def test_cost_reporting_run_report_has_nonzero_cost(tiny_repo_copy: Path, tmp_path: Path) -> None:
    """Full pipeline run with FakeLLMProvider charging 150 tokens/call → total_cost > 0.

    FakeLLMProvider.run_agent() calls spend_meter.charge(model, 100, 50) whenever
    a spend_meter is passed.  The SpendMeter uses the conservative per-token-class
    fallbacks ($5/MTok input, $25/MTok output — ADR-0020) when no pricing catalog
    can look up the fake model id.

    Assertions:
    - exit 0 (pipeline succeeded)
    - run-report.json total_cost_usd > 0
    - total_cost_usd is a finite float (not NaN, not inf)
    """
    result = _invoke_cli(
        tiny_repo_copy,
        extra=["--cache-path", str(tmp_path / "cache.db")],
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}"

    report = _load_report(tiny_repo_copy)
    assert report["status"] == "ok"

    cost = report["total_cost_usd"]
    assert isinstance(cost, float), f"total_cost_usd should be float, got {type(cost)}"
    assert cost > 0.0, f"total_cost_usd should be > 0 after FakeLLM charges tokens, got {cost}"
    import math

    assert math.isfinite(cost), f"total_cost_usd should be finite, got {cost}"


def test_cost_reporting_spend_meter_propagated_to_generation_result(
    tiny_repo_copy: Path, tmp_path: Path
) -> None:
    """Verifies the cost propagation chain: SpendMeter → GenerationResult → RunReport.

    We can't easily intercept GenerationResult directly from the CLI, but we can
    assert that the run-report (which reads from result.total_cost_usd) has a
    nonzero value, confirming the full wire-through is active.
    """
    result = _invoke_cli(
        tiny_repo_copy,
        extra=["--cache-path", str(tmp_path / "cache.db")],
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}"

    report = _load_report(tiny_repo_copy)
    # The tiny_repo has 3 regular lessons + 1 closing = 4 agent calls minimum
    # (each Orchestrator call charges 100 input + 50 output tokens at fallback
    # rates $5/MTok in and $25/MTok out → ~$0.00000175/call). Even 1 call > 0.
    assert report["total_cost_usd"] > 0.0, (
        "total_cost_usd must be > 0 — SpendMeter not propagated to run-report"
    )
