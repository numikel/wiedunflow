# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Stage reporter — prints `[N/7] <Name>` headers and live counters (US-071).

Exact stage names and copy per .ai/ux-spec.md §CLI.stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from codeguide.cli.output import (
    render_stage_detail,
    render_stage_done,
    render_stage_header,
)

StageId = Literal[1, 2, 3, 4, 5, 6, 7]

_STAGE_NAMES: dict[int, str] = {
    1: "Clone",
    2: "Static analyse (Jedi)",
    3: "Concept clustering · claude-haiku-4-5",
    4: "Lesson outlining · claude-haiku-4-5",
    5: "Narration · claude-opus-4-7",
    6: "Grounding against AST",
    7: "Render + finalize",
}


@dataclass
class StageReporter:
    """Console-backed stage reporter. Thin wrapper over ``cli.output`` helpers."""

    console: object  # rich.console.Console; typed loosely to avoid rich imports leaking

    def stage_start(self, index: int) -> None:
        """Render the ``[N/7] <Name>`` header."""
        name = _STAGE_NAMES[index]
        render_stage_header(self.console, index=index, name=name)  # type: ignore[arg-type]

    def detail(self, text: str) -> None:
        """Render a 5-space-indented status line inside the current stage body."""
        render_stage_detail(self.console, text=text)  # type: ignore[arg-type]

    def stage_done(self, summary: str) -> None:
        """Render the ``✓ done · <summary>`` completion line in good tone."""
        render_stage_done(self.console, summary=summary)  # type: ignore[arg-type]
