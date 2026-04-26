# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-070: cost-gate rich.panel renders table + totals + runtime summary."""

from __future__ import annotations

import io

from rich.console import Console

from wiedunflow.cli.output import CostGateRow, make_theme, render_cost_gate


def _capture() -> tuple[Console, io.StringIO]:
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


def test_cost_gate_renders_title_and_totals() -> None:
    console, buffer = _capture()
    render_cost_gate(
        console,
        rows=[
            CostGateRow(model="haiku", stage="stages 1-4", est_tokens=410_000, est_cost_usd=0.41),
            CostGateRow(model="opus", stage="stages 5-6", est_tokens=280_000, est_cost_usd=1.87),
        ],
        total_tokens=690_000,
        total_cost_usd=2.28,
        runtime_min=18,
        runtime_max=26,
        lessons=12,
        clusters=4,
    )
    out = buffer.getvalue()
    assert "ESTIMATED COST" in out
    assert "haiku" in out and "opus" in out
    assert "TOTAL" in out
    assert "$2.28" in out
    assert "18-26 min" in out
    assert "12 lessons" in out


def test_cost_gate_uses_heavy_border() -> None:
    console, buffer = _capture()
    render_cost_gate(
        console,
        rows=[CostGateRow("haiku", "x", 1000, 0.01)],
        total_tokens=1000,
        total_cost_usd=0.01,
        runtime_min=1,
        runtime_max=2,
        lessons=1,
        clusters=1,
    )
    out = buffer.getvalue()
    # HEAVY box characters: ┏, ┓, ┗, ┛
    assert "┏" in out and "┛" in out
