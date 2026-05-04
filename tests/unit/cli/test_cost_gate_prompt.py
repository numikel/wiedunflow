# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 8 US-084: cost-gate prompt with bypass conditions.

Coverage matrix (Q4 in plan):

| auto_yes | no_cost_prompt | is_tty | expected     | scenario                  |
|----------|----------------|--------|--------------|---------------------------|
| False    | False          | True   | prompt shown | default TTY interactive   |
| True     | False          | True   | bypassed → True | --yes flag                |
| False    | True           | True   | bypassed → True | --no-cost-prompt flag     |
| False    | False          | False  | bypassed → True | non-TTY (CI / pipe)       |

The prompt itself uses ``click.confirm`` which is exercised via ``CliRunner``
in the integration tests; here we cover the bypass logic and the abort path.
"""

from __future__ import annotations

import io
from unittest.mock import patch

import click
from click.testing import CliRunner
from rich.console import Console

from wiedunflow.cli.cost_estimator import estimate
from wiedunflow.cli.cost_gate import (
    prompt_cost_gate,
    should_skip_prompt,
)
from wiedunflow.cli.output import make_theme
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
# prompt_cost_gate — short-circuit paths (no console interaction)
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
