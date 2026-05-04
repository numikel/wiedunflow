# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Stage reporter — prints `[N/7] <Name>` headers and live counters (US-071).

Sprint 8 (v0.2.0) extends the v0.1.0 thin wrapper with stateful animation:

- ``progress_line(text)`` — replace-in-place body line for mass-scan stages
  (Stage 2 Jedi analysis: ``[42/47] analysing src/foo.py`` updates one row).
- ``lesson_event(idx, total, title)`` — append-only scrolling body line for
  event-rich stages (Stage 5 narration: each lesson stays in the transcript).
- ``tick_counters(tokens_in, tokens_out, cost_usd, elapsed_s)`` — refresh a
  footer line with running cost/token/elapsed counters during LLM stages.
- ``stage_done(summary)`` — flush any active live region and print ``✓ done``.

Animation strategy follows ``.ai/ux-spec.md §4.5.1`` (Sprint 8 decision Q3):
replace-line for Stage 2 (mass scan, no-history), scroll for Stage 5 (each
lesson is a costly event worth keeping). Stages 1/3/4/6/7 use ``detail()``
(static print) plus ``tick_counters()`` for live counter footers.

Two-sink rule (Sprint 5 #6): rich imports live only in ``cli/output.py``;
this module drives the live region through the opaque ``LiveStageHandle``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from wiedunflow.cli.output import (
    LiveStageHandle,
    render_stage_detail,
    render_stage_done,
    render_stage_header,
    start_live_stage,
    stop_live_stage,
    update_live_stage,
)

StageId = Literal[1, 2, 3, 4, 5, 6, 7]

# Stage names match the actual 7-stage pipeline (CLAUDE.md §PIPELINE).
# ux-spec.md §4.5 still describes a wishful v0.5+ pipeline (separate
# clustering / outlining / narration / grounding stages); reconciling that
# with the current implementation is tracked for a future sprint.
_STAGE_NAMES: dict[int, str] = {
    1: "Ingestion",
    2: "Analysis",
    3: "Graph",
    4: "RAG",
    5: "Planning",
    6: "Generation",
    7: "Build",
}


@dataclass
class StageReporter:
    """Console-backed stage reporter with stateful live regions (US-071, US-081, US-082, US-083).

    The reporter holds at most one active live region per stage, used for
    replace-line progress (Stage 2) or scrolling event log (Stage 5). The
    live region is started lazily on the first ``progress_line`` /
    ``lesson_event`` / ``tick_counters`` call and closed by ``stage_done``
    (or by the next ``stage_start`` for safety).

    Attributes:
        console: ``rich.console.Console`` to render into. Typed loosely as
            ``object`` so use-case code can hold a reference without leaking
            ``rich`` imports past the ``cli/`` boundary.
    """

    console: object  # rich.console.Console; loose typing keeps rich confined to output.py
    _live: LiveStageHandle | None = field(default=None, init=False, repr=False)
    _scroll_lines: list[str] = field(default_factory=list, init=False, repr=False)
    _progress_text: str | None = field(default=None, init=False, repr=False)
    _counters_text: str | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    # Stage lifecycle
    # ------------------------------------------------------------------

    def stage_start(self, index: int) -> None:
        """Render the ``[N/7] <Name>`` header in accent tone.

        Closes any live region that lingered from the previous stage (defensive
        — callers should always call ``stage_done`` first, but a missed
        ``stage_done`` should not corrupt subsequent output).
        """
        self._close_live()
        name = _STAGE_NAMES[index]
        render_stage_header(self.console, index=index, name=name)  # type: ignore[arg-type]

    def detail(self, text: str) -> None:
        """Render a 5-space-indented status line as static output.

        Use for stage-level messages that should remain visible in the
        transcript without animation (e.g., "tokens: 98 234 in · 2 856 out"
        summary lines per ux-spec §4.5).
        """
        self._close_live()
        render_stage_detail(self.console, text=text)  # type: ignore[arg-type]

    def stage_done(self, summary: str) -> None:
        """Render the ``✓ done · <summary>`` line and close the live region."""
        self._close_live()
        render_stage_done(self.console, summary=summary)  # type: ignore[arg-type]
        self._scroll_lines = []
        self._progress_text = None
        self._counters_text = None

    # ------------------------------------------------------------------
    # Animated body output
    # ------------------------------------------------------------------

    def progress_line(self, text: str) -> None:
        """Replace-line body update — for mass-scan stages (Stage 2 Jedi).

        Each call replaces the previous progress line in place. On non-TTY
        output (``console.is_terminal`` is False) the underlying live region
        falls back to per-update prints, so CI / log-capture mode preserves
        history while TTY mode shows a single updating row.
        """
        self._scroll_lines = []  # progress_line and lesson_event are mutually exclusive
        self._progress_text = text
        self._refresh_live()

    def lesson_event(self, idx: int, total: int, title: str) -> None:
        """Append-only body update — for event-rich stages (Stage 5 narration).

        Each call adds a new line to the scrolling event log. All previously
        appended lines remain visible. Counter footer (if any) stays pinned
        below the scrolling list.
        """
        self._progress_text = None  # progress_line and lesson_event are mutually exclusive
        line = f"[{idx}/{total}] narrating '{title}'"
        self._scroll_lines.append(line)
        self._refresh_live()

    def tick_counters(
        self,
        *,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        elapsed_s: float,
    ) -> None:
        """Refresh the running counters footer (US-083, ux-spec §4.6).

        Footer format: ``cost: $X.XX · tokens: N in / M out · elapsed MM:SS``.
        Footer pins below the active body region (progress line or scroll
        list) and persists until the next ``stage_done`` / ``stage_start``.
        """
        elapsed_mm = int(elapsed_s) // 60
        elapsed_ss = int(elapsed_s) % 60
        tok_in_fmt = f"{tokens_in:,}".replace(",", " ")
        tok_out_fmt = f"{tokens_out:,}".replace(",", " ")
        self._counters_text = (
            f"cost: ${cost_usd:.2f} · tokens: {tok_in_fmt} in / {tok_out_fmt} out "
            f"· elapsed {elapsed_mm}:{elapsed_ss:02d}"
        )
        self._refresh_live()

    # ------------------------------------------------------------------
    # Internal live-region management
    # ------------------------------------------------------------------

    def _refresh_live(self) -> None:
        """Open or refresh the live region with current body + footer state."""
        if self._live is None:
            self._live = start_live_stage(self.console)  # type: ignore[arg-type]
        update_live_stage(
            self._live,
            progress_text=self._progress_text,
            scroll_lines=self._scroll_lines,
            counters_text=self._counters_text,
        )

    def _close_live(self) -> None:
        """Stop the active live region (if any) without erasing its last frame."""
        if self._live is not None:
            stop_live_stage(self._live)
            self._live = None


@dataclass
class NoOpReporter:
    """Null-object reporter — used when the orchestrator is run without a CLI.

    Tests and headless callers (``--log-format=json`` mode, library use) inject
    this sentinel to avoid spinning up a Rich Console. Every method is a
    no-op, so the orchestrator can call into the reporter unconditionally.
    """

    def stage_start(self, index: int) -> None:
        return None

    def detail(self, text: str) -> None:
        return None

    def stage_done(self, summary: str) -> None:
        return None

    def progress_line(self, text: str) -> None:
        return None

    def lesson_event(self, idx: int, total: int, title: str) -> None:
        return None

    def tick_counters(
        self,
        *,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        elapsed_s: float,
    ) -> None:
        return None
