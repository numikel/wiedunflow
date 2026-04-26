# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 8 US-081, US-082, US-083: animated body output for StageReporter.

Coverage:

- ``progress_line`` (US-081): replace-line semantics on TTY, multiple updates,
  graceful close on stage_done.
- ``lesson_event`` (US-082): scroll semantics, every event preserved in
  transcript, mutual exclusion with progress_line.
- ``tick_counters`` (US-083): footer formatting, MM:SS elapsed, tokens with
  thousands separators.
- ``NoOpReporter``: every method is a no-op (for headless callers).

Tests use ``Console`` with ``force_terminal=False`` so ``rich.live.Live`` falls
back to per-update prints; we assert against the captured transcript rather
than against a moving cursor (which is not portable across terminals).
"""

from __future__ import annotations

import io

from rich.console import Console

from wiedunflow.cli.output import make_theme
from wiedunflow.cli.stage_reporter import NoOpReporter, StageReporter


def _capture() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    console = Console(
        theme=make_theme(),
        file=buffer,
        force_terminal=False,
        no_color=True,
        width=120,
        legacy_windows=False,
    )
    return console, buffer


# ---------------------------------------------------------------------------
# stage_start / detail / stage_done — basic lifecycle
# ---------------------------------------------------------------------------


def test_stage_start_prints_header_with_index_and_name() -> None:
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(2)

    out = buffer.getvalue()
    assert "[2/7]" in out
    assert "Analysis" in out


def test_stage_done_prints_check_and_summary() -> None:
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(1)
    reporter.stage_done("47 python files discovered")

    out = buffer.getvalue()
    assert "✓ done" in out
    assert "47 python files discovered" in out


def test_detail_prints_indented_static_line() -> None:
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(5)
    reporter.detail("generating lesson manifest…")

    out = buffer.getvalue()
    assert "generating lesson manifest" in out


# ---------------------------------------------------------------------------
# US-081 — progress_line (replace-line)
# ---------------------------------------------------------------------------


def test_progress_line_emits_text_with_indentation() -> None:
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(2)
    reporter.progress_line("[1/47] analysing src/foo.py")
    reporter.stage_done("47 files analysed")

    out = buffer.getvalue()
    assert "analysing src/foo.py" in out
    assert "✓ done" in out


def test_progress_line_multiple_updates_succeeds_without_crashing() -> None:
    """Sprint 8 / US-081: replace-line accepts an arbitrary update sequence."""
    console, _ = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(2)
    for i in range(1, 11):
        reporter.progress_line(f"[{i}/10] analysing src/file_{i}.py")
    reporter.stage_done("10 files analysed")
    # No assertions on transcript order (Live in non-TTY mode is implementation
    # specific); the contract under test is "no crashes, summary printed".


def test_progress_line_then_stage_done_closes_live_region() -> None:
    """Re-using the reporter for a second stage must not leave stale state."""
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(2)
    reporter.progress_line("[1/47] analysing src/foo.py")
    reporter.stage_done("47 files analysed")

    reporter.stage_start(3)
    reporter.detail("PageRank + community detection…")
    reporter.stage_done("412 ranked")

    out = buffer.getvalue()
    assert "[2/7]" in out
    assert "[3/7]" in out
    # Both headers must be present; second stage must not be swallowed by the
    # first stage's live region.


# ---------------------------------------------------------------------------
# US-082 — lesson_event (scroll)
# ---------------------------------------------------------------------------


def test_lesson_event_renders_idx_total_and_title() -> None:
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(6)
    reporter.lesson_event(1, 12, "Session basics: initialization and context")
    reporter.stage_done("12 lessons narrated")

    out = buffer.getvalue()
    assert "[1/12]" in out
    assert "Session basics" in out
    assert "narrating" in out


def test_lesson_event_appends_multiple_events_to_transcript() -> None:
    """Sprint 8 / US-082: every event must be present in the final output."""
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(6)
    reporter.lesson_event(1, 3, "First lesson")
    reporter.lesson_event(2, 3, "Second lesson")
    reporter.lesson_event(3, 3, "Third lesson")
    reporter.stage_done("3 lessons narrated")

    out = buffer.getvalue()
    assert "First lesson" in out
    assert "Second lesson" in out
    assert "Third lesson" in out


def test_lesson_event_after_progress_line_resets_state() -> None:
    """progress_line and lesson_event are mutually exclusive within a stage."""
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(2)
    reporter.progress_line("[1/47] analysing src/foo.py")
    # New stage with lesson_event — must not spill scroll state from previous.
    reporter.stage_done("done")

    reporter.stage_start(6)
    reporter.lesson_event(1, 1, "Only lesson")
    reporter.stage_done("1 lesson")

    out = buffer.getvalue()
    assert "Only lesson" in out


# ---------------------------------------------------------------------------
# US-083 — tick_counters (footer)
# ---------------------------------------------------------------------------


def test_tick_counters_formats_cost_tokens_and_elapsed() -> None:
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(5)
    reporter.tick_counters(tokens_in=98_234, tokens_out=2_856, cost_usd=0.15, elapsed_s=165.0)
    reporter.stage_done("manifest ready")

    out = buffer.getvalue()
    assert "$0.15" in out
    assert "98 234" in out  # thousands separator is " "
    assert "2 856" in out
    assert "2:45" in out  # 165s = 2:45


def test_tick_counters_pads_seconds_with_zero() -> None:
    console, buffer = _capture()
    reporter = StageReporter(console=console)

    reporter.stage_start(5)
    reporter.tick_counters(tokens_in=1, tokens_out=1, cost_usd=0.01, elapsed_s=65.0)
    reporter.stage_done("done")

    out = buffer.getvalue()
    assert "1:05" in out  # not "1:5"


# ---------------------------------------------------------------------------
# NoOpReporter — never crashes, never writes
# ---------------------------------------------------------------------------


def test_noop_reporter_methods_are_silent() -> None:
    reporter = NoOpReporter()

    # Every method must accept the same arguments as StageReporter and return
    # None without side effects. We don't assert anything about output because
    # there is no Console to capture from.
    reporter.stage_start(1)
    reporter.detail("x")
    reporter.progress_line("y")
    reporter.lesson_event(1, 2, "z")
    reporter.tick_counters(tokens_in=1, tokens_out=2, cost_usd=0.0, elapsed_s=0.0)
    reporter.stage_done("ok")
