# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 8 US-084: cost-gate prompt — v0.10.0 5-row multi-agent layout.

Coverage matrix (Q4 in plan):

| auto_yes | no_cost_prompt | is_tty | expected        | scenario                  |
|----------|----------------|--------|-----------------|---------------------------|
| False    | False          | True   | prompt shown    | default TTY interactive   |
| True     | False          | True   | bypassed → True | --yes flag                |
| False    | True           | True   | bypassed → True | --no-cost-prompt flag     |
| False    | False          | False  | bypassed → True | non-TTY (CI / pipe)       |

The 5-row breakdown (Planning / Orchestrator / Researcher x N / Writer /
Reviewer) replaces the v0.9.5 2-row plan/narrate layout (ADR-0016 clean-up).
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner
from rich.console import Console

from wiedunflow.cli.cost_estimator import estimate
from wiedunflow.cli.cost_gate import (
    prompt_cost_gate,
    should_skip_prompt,
)
from wiedunflow.cli.output import CostGateRow, make_theme
from wiedunflow.use_cases.errors import CostGateAbortedError


def _make_console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    console = Console(
        theme=make_theme(),
        file=buffer,
        force_terminal=False,
        no_color=True,
        width=80,
        legacy_windows=False,
    )
    return console, buffer


def _sample_estimate() -> object:
    return estimate(symbols=400, lessons=12, clusters=4)


# ---------------------------------------------------------------------------
# should_skip_prompt — bypass matrix (US-084 Q4)
# ---------------------------------------------------------------------------


def test_skip_prompt_when_auto_yes() -> None:
    assert should_skip_prompt(auto_yes=True, prompt_disabled=False, is_tty=True) is True


def test_skip_prompt_when_prompt_disabled() -> None:
    assert should_skip_prompt(auto_yes=False, prompt_disabled=True, is_tty=True) is True


def test_skip_prompt_when_non_tty() -> None:
    assert should_skip_prompt(auto_yes=False, prompt_disabled=False, is_tty=False) is True


def test_do_not_skip_in_default_tty_interactive() -> None:
    assert should_skip_prompt(auto_yes=False, prompt_disabled=False, is_tty=True) is False


# ---------------------------------------------------------------------------
# prompt_cost_gate — short-circuit bypass paths (no console interaction)
# ---------------------------------------------------------------------------


def test_prompt_cost_gate_returns_true_with_auto_yes() -> None:
    console, buffer = _make_console()
    result = prompt_cost_gate(
        console,
        estimate=_sample_estimate(),  # type: ignore[arg-type]
        auto_yes=True,
        prompt_disabled=False,
        is_tty=True,
    )
    assert result is True
    # When bypassed, the panel must NOT render — bypassed prompts are silent.
    assert buffer.getvalue() == ""


def test_prompt_cost_gate_returns_true_with_no_cost_prompt() -> None:
    console, buffer = _make_console()
    result = prompt_cost_gate(
        console,
        estimate=_sample_estimate(),  # type: ignore[arg-type]
        auto_yes=False,
        prompt_disabled=True,
        is_tty=True,
    )
    assert result is True
    assert buffer.getvalue() == ""


def test_prompt_cost_gate_returns_true_when_non_tty() -> None:
    console, buffer = _make_console()
    result = prompt_cost_gate(
        console,
        estimate=_sample_estimate(),  # type: ignore[arg-type]
        auto_yes=False,
        prompt_disabled=False,
        is_tty=False,
    )
    assert result is True
    assert buffer.getvalue() == ""


# ---------------------------------------------------------------------------
# prompt_cost_gate — interactive path (renders panel + calls click.confirm)
# ---------------------------------------------------------------------------


def test_prompt_cost_gate_renders_panel_and_returns_user_choice() -> None:
    """When all bypass conditions are False, the panel renders and click.confirm decides."""
    console, buffer = _make_console()

    with patch("wiedunflow.cli.cost_gate.click.confirm", return_value=True) as confirm_mock:
        result = prompt_cost_gate(
            console,
            estimate=_sample_estimate(),  # type: ignore[arg-type]
            auto_yes=False,
            prompt_disabled=False,
            is_tty=True,
        )

    assert result is True
    confirm_mock.assert_called_once()
    # The panel should have been rendered before click.confirm was called.
    assert "ESTIMATED COST" in buffer.getvalue()


def test_prompt_cost_gate_returns_false_when_user_declines() -> None:
    console, buffer = _make_console()

    with patch("wiedunflow.cli.cost_gate.click.confirm", return_value=False):
        result = prompt_cost_gate(
            console,
            estimate=_sample_estimate(),  # type: ignore[arg-type]
            auto_yes=False,
            prompt_disabled=False,
            is_tty=True,
        )

    assert result is False
    # Panel still rendered even on decline (user saw the cost before saying no).
    assert "ESTIMATED COST" in buffer.getvalue()


def test_prompt_cost_gate_uses_custom_confirm_fn() -> None:
    """When confirm_fn is provided it replaces click.confirm."""
    console, _buffer = _make_console()
    confirm_fn = MagicMock(return_value=True)

    result = prompt_cost_gate(
        console,
        estimate=_sample_estimate(),  # type: ignore[arg-type]
        auto_yes=False,
        prompt_disabled=False,
        is_tty=True,
        confirm_fn=confirm_fn,
    )

    assert result is True
    confirm_fn.assert_called_once_with("Proceed?")


# ---------------------------------------------------------------------------
# 5-row layout — stage labels and model label propagation
# ---------------------------------------------------------------------------


def test_five_rows_are_rendered_with_correct_stage_labels() -> None:
    """The cost-gate panel must contain all 5 stage labels from the multi-agent pipeline."""
    console, buffer = _make_console()

    with patch("wiedunflow.cli.cost_gate.click.confirm", return_value=True):
        prompt_cost_gate(
            console,
            estimate=_sample_estimate(),  # type: ignore[arg-type]
            auto_yes=False,
            prompt_disabled=False,
            is_tty=True,
        )

    rendered = buffer.getvalue()
    assert "Planning (Stage 4)" in rendered
    assert "Orchestrator" in rendered
    assert "Researcher" in rendered
    assert "Writer" in rendered
    assert "Reviewer" in rendered


def test_custom_per_role_model_labels_appear_in_panel() -> None:
    """Custom model labels must be propagated to CostGateRow.model field."""
    console, buffer = _make_console()

    with patch("wiedunflow.cli.cost_gate.click.confirm", return_value=True):
        prompt_cost_gate(
            console,
            estimate=_sample_estimate(),  # type: ignore[arg-type]
            auto_yes=False,
            prompt_disabled=False,
            is_tty=True,
            plan_model_label="claude-sonnet-4-6",
            orchestrator_model_label="claude-opus-4-7",
            researcher_model_label="claude-haiku-4-5",
            writer_model_label="claude-opus-4-7",
            reviewer_model_label="claude-haiku-4-5",
        )

    rendered = buffer.getvalue()
    assert "claude-sonnet-4-6" in rendered
    assert "claude-opus-4-7" in rendered
    assert "claude-haiku-4-5" in rendered


def test_rows_constructed_with_correct_token_sums(monkeypatch: pytest.MonkeyPatch) -> None:
    """CostGateRow.est_tokens must equal role.input_tokens + role.output_tokens."""
    est = estimate(symbols=100, lessons=5, clusters=2)
    captured_rows: list[CostGateRow] = []

    original_render = __import__(
        "wiedunflow.cli.output", fromlist=["render_cost_gate"]
    ).render_cost_gate

    def _capturing_render(console: object, *, rows: list[CostGateRow], **kwargs: object) -> None:
        captured_rows.extend(rows)
        original_render(console, rows=rows, **kwargs)

    monkeypatch.setattr("wiedunflow.cli.cost_gate.render_cost_gate", _capturing_render)
    console, _ = _make_console()

    with patch("wiedunflow.cli.cost_gate.click.confirm", return_value=True):
        prompt_cost_gate(
            console,
            estimate=est,
            auto_yes=False,
            prompt_disabled=False,
            is_tty=True,
        )

    assert len(captured_rows) == 5

    planning_row, orch_row, res_row, wri_row, rev_row = captured_rows

    assert planning_row.est_tokens == est.planning.input_tokens + est.planning.output_tokens
    assert planning_row.est_cost_usd == est.planning.cost_usd

    assert orch_row.est_tokens == est.orchestrator.input_tokens + est.orchestrator.output_tokens
    assert orch_row.est_cost_usd == est.orchestrator.cost_usd

    assert res_row.est_tokens == est.researcher.input_tokens + est.researcher.output_tokens
    assert res_row.est_cost_usd == est.researcher.cost_usd

    assert wri_row.est_tokens == est.writer.input_tokens + est.writer.output_tokens
    assert wri_row.est_cost_usd == est.writer.cost_usd

    assert rev_row.est_tokens == est.reviewer.input_tokens + est.reviewer.output_tokens
    assert rev_row.est_cost_usd == est.reviewer.cost_usd


# ---------------------------------------------------------------------------
# CostGateAbortedError — exception payload
# ---------------------------------------------------------------------------


def test_cost_gate_aborted_error_carries_estimate_and_lessons() -> None:
    err = CostGateAbortedError(estimate_usd=2.28, lessons=12)
    assert err.estimate_usd == 2.28
    assert err.lessons == 12
    assert "$2.28" in str(err)
    assert "12 lessons" in str(err)


# ---------------------------------------------------------------------------
# Click integration smoke — confirm honours the y/N input
# ---------------------------------------------------------------------------


def test_click_confirm_honours_input_y() -> None:
    """Sanity: click.confirm reads 'y' as accept (used by prompt_cost_gate)."""

    @click.command()
    def cmd() -> None:
        if click.confirm("Proceed?", default=False):
            click.echo("yes")
        else:
            click.echo("no")

    runner = CliRunner()
    result = runner.invoke(cmd, input="y\n")
    assert result.exit_code == 0
    assert "yes" in result.output


def test_click_confirm_honours_input_n() -> None:
    @click.command()
    def cmd() -> None:
        if click.confirm("Proceed?", default=False):
            click.echo("yes")
        else:
            click.echo("no")

    runner = CliRunner()
    result = runner.invoke(cmd, input="n\n")
    assert result.exit_code == 0
    assert "no" in result.output
