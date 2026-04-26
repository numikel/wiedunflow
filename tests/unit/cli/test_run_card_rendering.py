# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-072: framed run-report card with status-colored border."""

from __future__ import annotations

import io

from rich.console import Console

from wiedunflow.cli.output import make_theme, render_run_report


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


def test_success_card_renders_title_and_rows() -> None:
    console, buffer = _capture()
    render_run_report(
        console,
        status="success",
        lines=[
            ("lessons", "12 of 12 narrated"),
            ("elapsed", "18:43"),
            ("cost", "$2.28"),
        ],
    )
    out = buffer.getvalue()
    assert "✓ success" in out
    assert "lessons" in out and "12 of 12 narrated" in out
    assert "elapsed" in out and "18:43" in out


def test_degraded_card_shows_warn_symbol() -> None:
    console, buffer = _capture()
    render_run_report(
        console,
        status="degraded",
        lines=[("lessons", "8 of 12 narrated · 4 skipped")],
    )
    out = buffer.getvalue()
    assert "⚠ degraded" in out
    assert "4 skipped" in out


def test_failed_card_shows_error_symbol() -> None:
    console, buffer = _capture()
    render_run_report(
        console,
        status="failed",
        lines=[("failed at", "stage 5 (narration)")],
    )
    out = buffer.getvalue()
    assert "✗ failed" in out
    assert "stage 5" in out
