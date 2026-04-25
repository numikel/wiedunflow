# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Rich-based user-facing output sink for the CodeGuide CLI (Sprint 5, decision #6).

Two-sinks architecture:
- ``output.py`` (this module) renders user-facing UI: cost gate, stage headers,
  run report card, error banners. Uses ``rich.Console`` + ``rich.theme.Theme``.
- ``logging.py`` emits structured events (JSON when ``--log-format=json``).

Pipeline code in ``use_cases/`` and ``adapters/`` MUST NOT import from ``rich``;
a lint test (`tests/unit/cli/test_no_rich_outside_output.py`) enforces this.

UX spec: `.ai/ux-spec.md §CLI` (8 color roles, cost gate, stage headers, run card).
ADR-0011 decision 1: Modern CLI only.
"""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from rich.box import HEAVY
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.style import Style
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Exact hex values per .ai/ux-spec.md §CLI.color-roles (Modern palette).
_COLOR_ROLES: dict[str, Style] = {
    "default": Style(),
    "dim": Style(color="#868a93"),
    "good": Style(color="#2d9f61"),
    "warn": Style(color="#d89f13"),
    "err": Style(color="#c23d1b"),
    "accent": Style(color="#3d5ee7"),
    "link": Style(color="#00aaaa", underline=True, bold=True),
    "prompt": Style(),
}


def make_theme() -> Theme:
    """Return the Rich Theme with all 8 CodeGuide color roles (US-074)."""
    return Theme({name: style for name, style in _COLOR_ROLES.items()})


def init_console(
    *,
    json_mode: bool = False,
    stream: TextIO | None = None,
    force_no_color: bool = False,
) -> Console:
    """Create a Rich ``Console`` that honours CI/no-TTY environments.

    Args:
        json_mode: When ``True`` the caller is rendering JSON logs to stderr;
            stdout should stay minimal — returns a no-color Console.
        stream: Override output stream (``sys.stdout`` by default).
        force_no_color: Disable colors regardless of TTY detection.

    Returns:
        Configured ``rich.console.Console``.
    """
    target = stream if stream is not None else sys.stdout

    # Sprint 8: force UTF-8 on stdout so Rich's unicode glyphs (✓, ─, ┏, ⚠)
    # don't crash on Windows code pages (cp1250 / cp1252). ``reconfigure`` is
    # available on standard ``TextIOWrapper`` streams; non-standard streams
    # (StringIO in tests, custom wrappers) are left untouched.
    reconfigure = getattr(target, "reconfigure", None)
    if callable(reconfigure):
        with contextlib.suppress(OSError, ValueError):
            reconfigure(encoding="utf-8", errors="replace")

    is_tty = hasattr(target, "isatty") and target.isatty()
    no_color = force_no_color or json_mode or not is_tty
    return Console(
        theme=make_theme(),
        file=target,
        force_terminal=is_tty,
        no_color=no_color,
        highlight=False,
        emoji=False,
        legacy_windows=False,
    )


@dataclass(frozen=True)
class CostGateRow:
    """One row in the cost-gate estimate panel (US-070)."""

    model: str
    stage: str
    est_tokens: int
    est_cost_usd: float


def render_cost_gate(
    console: Console,
    *,
    rows: list[CostGateRow],
    total_tokens: int,
    total_cost_usd: float,
    runtime_min: int,
    runtime_max: int,
    lessons: int,
    clusters: int,
) -> None:
    """Render the cost-gate panel exactly as specified in `.ai/ux-spec.md §CLI.cost-gate`.

    Layout: HEAVY border, title "ESTIMATED COST", table (Model|Stage|Tokens|Cost),
    totals row, runtime+lessons+clusters summary line. The caller prompts for y/N
    via ``click.prompt`` immediately after this returns.
    """
    table = Table(show_header=True, header_style="accent", box=None, pad_edge=False)
    table.add_column("Model", style="default")
    table.add_column("Stage", style="default")
    table.add_column("Est. tokens", justify="right", style="dim")
    table.add_column("Cost", justify="right", style="default")

    for row in rows:
        table.add_row(
            row.model,
            row.stage,
            f"~{row.est_tokens:,}".replace(",", " "),
            f"${row.est_cost_usd:.2f}",
        )
    table.add_section()
    total_fmt = f"~{total_tokens:,}".replace(",", " ")
    table.add_row("TOTAL", "", total_fmt, f"${total_cost_usd:.2f}", style="accent")

    summary = (
        f"\nRuntime est. {runtime_min}-{runtime_max} min "
        f"· {lessons} lessons across {clusters} clusters"
    )
    panel = Panel.fit(
        table,
        title="ESTIMATED COST",
        box=HEAVY,
        border_style="accent",
        padding=(1, 2),
        subtitle=summary.strip(),
    )
    console.print(panel)


def render_run_report(
    console: Console,
    *,
    status: str,
    lines: list[tuple[str, str]],
) -> None:
    """Render the framed run-report card (US-072) with status-colored border.

    Args:
        console: Rich console.
        status: ``"success"`` / ``"degraded"`` / ``"failed"``.
        lines: Key-value rows rendered as ``key    value`` aligned two-column list.
    """
    colors = {
        "success": ("good", "✓ success"),
        "degraded": ("warn", "⚠ degraded"),
        "failed": ("err", "✗ failed"),
    }
    border, header = colors.get(status, ("default", status))
    body_table = Table(show_header=False, box=None, pad_edge=False)
    body_table.add_column("key", style="dim", no_wrap=True)
    body_table.add_column("value", style="default")
    for key, value in lines:
        body_table.add_row(key, value)
    panel = Panel(
        body_table,
        title=header,
        title_align="left",
        box=HEAVY,
        border_style=border,
        padding=(1, 2),
    )
    console.print(panel)


def osc8_hyperlink(path: Path, label: str | None = None) -> str:
    """Return an OSC 8 terminal hyperlink escape sequence (US-055).

    Modern terminals (iTerm2, Windows Terminal, VS Code, kitty, WezTerm, recent
    gnome-terminal) render this as a clickable link; terminals that don't
    support OSC 8 simply show the plain label text.
    """
    url = path.resolve().as_uri()
    link_text = label if label is not None else str(path)
    return f"\x1b]8;;{url}\x1b\\{link_text}\x1b]8;;\x1b\\"


def print_done_summary(console: Console, *, path: Path) -> None:
    """Print the final clickable summary pointing at the generated tutorial (US-055)."""
    console.print(f"open  [link]{osc8_hyperlink(path)}[/link]")


def print_cost_abort(console: Console, *, elapsed: str) -> None:
    """Print the cost-gate abort message (ux-spec §CLI.error-scenarios.cost-gate-abort)."""
    console.print("aborted by user. no API calls were made.")
    console.print(f"total cost: [dim]$0.00 · elapsed {elapsed}[/dim]")


def print_rate_limit_event(console: Console, *, attempt: int, backoff_s: int) -> None:
    """Print a rate-limit backoff banner (US-073)."""
    console.print("     [warn]⚠ HTTP 429 rate_limit_error (tokens-per-minute)[/warn]")
    console.print(f"     [warn]⟳ backoff {backoff_s}s (attempt {attempt}/5)[/warn]")


def print_rate_limit_resumed(console: Console) -> None:
    """Print the resume banner after a successful retry (US-073)."""
    console.print("     [good]✓ resumed · rate-limit window cleared[/good]")


def render_stage_header(console: Console, *, index: int, name: str) -> None:
    """Print the ``[N/7] <Name>`` stage header in accent tone (US-071)."""
    console.print(f"\n[accent][{index}/7] {name}[/accent]")


def render_stage_detail(console: Console, *, text: str) -> None:
    """Print a 5-space-indented detail line inside a stage body (US-071)."""
    console.print(f"     {text}")


def render_stage_done(console: Console, *, summary: str) -> None:
    """Print the stage completion line in ``good`` tone (US-071)."""
    console.print(f"     [good]✓ done · {summary}[/good]")


def render_banner(console: Console, *, version: str) -> None:
    """Print the CodeGuide startup banner (US-086, Sprint 8 gap-fill).

    UX-spec §4.1 was silent on a startup banner — this function fills the gap
    with a minimal accent-toned identification line shown before preflight.
    Mirrors the ``claude`` CLI startup feel without external assets.
    """
    console.print()
    console.print(f"[accent]CodeGuide[/accent] [dim]v{version}[/dim]")
    console.print("[dim]offline-friendly tutorial generator from local Git repos[/dim]")
    console.print()


def render_preflight_ok(console: Console, *, lines: list[str]) -> None:
    """Print the preflight-checks section with green check marks (US-086).

    Each entry is rendered as ``  ✓ <line>``. Caller decides what to check
    (API key present, repo is git, etc.); this function only handles layout.
    UX-spec §4.3 (line 536).
    """
    console.print("[accent]preflight[/accent]")
    for line in lines:
        console.print(f"  [good]✓ {line}[/good]")
    console.print()


def render_preflight_warn(console: Console, *, line: str) -> None:
    """Print a single preflight warning entry (e.g., editor not found)."""
    console.print(f"  [warn]⚠ {line}[/warn]")


# ---------------------------------------------------------------------------
# Live stage region (Sprint 8 — animated body output)
# ---------------------------------------------------------------------------
#
# Stage 2/5 use a stateful live region rendered below the stage header. The
# rich.live.Live machinery is confined to this module per the Sprint 5 #6
# two-sink rule (see test_no_rich_outside_output.py); ``stage_reporter.py``
# manipulates the region through the opaque ``LiveStageHandle`` only.


@dataclass
class LiveStageHandle:
    """Opaque handle returned by :func:`start_live_stage`.

    Wraps a ``rich.live.Live`` instance so callers in ``stage_reporter`` can
    drive a live region without importing rich directly. All fields are
    private — interact with the handle via the module-level helpers.
    """

    _live: Live


def start_live_stage(console: Console) -> LiveStageHandle:
    """Open a new live region under the current console position (US-081, US-082, US-083)."""
    live = Live(
        Text(""),
        console=console,
        transient=False,
        refresh_per_second=10,
        auto_refresh=False,
    )
    live.start()
    return LiveStageHandle(_live=live)


def update_live_stage(
    handle: LiveStageHandle,
    *,
    progress_text: str | None,
    scroll_lines: list[str],
    counters_text: str | None,
) -> None:
    """Refresh the live region with the new body + footer state.

    Args:
        handle: Handle returned by :func:`start_live_stage`.
        progress_text: Replace-line text (Stage 2 mode); mutually exclusive
            with ``scroll_lines``.
        scroll_lines: Append-only event log (Stage 5 mode); mutually exclusive
            with ``progress_text``.
        counters_text: Optional pinned footer line (running cost / tokens /
            elapsed). Renders below the body in dim tone.
    """
    parts: list[RenderableType] = []
    if progress_text is not None:
        parts.append(Text(f"     {progress_text}"))
    else:
        parts.extend(Text(f"     {line}") for line in scroll_lines)
    if counters_text is not None:
        parts.append(Text(f"     {counters_text}", style="dim"))
    renderable: RenderableType = Group(*parts) if parts else Text("")
    handle._live.update(renderable)
    handle._live.refresh()


def stop_live_stage(handle: LiveStageHandle) -> None:
    """Close the live region, leaving its last frame in the transcript.

    On non-TTY consoles ``Live`` falls back to per-update prints without a
    trailing newline, which would visually merge the live body into the
    following ``✓ done`` line. We always emit an explicit newline after stop
    so the transcript stays readable in CI / pipes / log files.
    """
    handle._live.stop()
    handle._live.console.line()
