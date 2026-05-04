# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Cross-cutting errors raised by use_cases and consumed by CLI.

Domain errors that cross the use_cases ↔ cli boundary live here so both
layers can import a single canonical class. Putting them in :mod:`cli.*`
would invert the Clean Architecture dependency direction (ADR-0003); the
inner ``use_cases`` layer must not depend on the outer ``cli`` layer.
"""

from __future__ import annotations


class MaxCostExceededError(RuntimeError):
    """Raised by the cost-gate pre-flight check when the estimate exceeds ``--max-cost``.

    US-019: the CLI translates this into a structured run-report with
    ``status="failed"`` and an exit code of 1 without making any narration calls.
    """

    def __init__(self, estimate_usd: float, cap_usd: float, lessons: int) -> None:
        super().__init__(
            f"Estimated cost ${estimate_usd:.2f} exceeds --max-cost cap ${cap_usd:.2f} "
            f"for {lessons} lessons"
        )
        self.estimate_usd = estimate_usd
        self.cap_usd = cap_usd
        self.lessons = lessons


class CostGateAbortedError(RuntimeError):
    """Raised when the user declines the interactive cost-gate prompt (US-084 — Sprint 8).

    Distinguished from :class:`MaxCostExceededError` because this is a clean
    user abort (exit code 0), not a failure (exit code 1). The CLI prints
    the spec-mandated abort message and writes a ``status="ok"`` run-report
    with zero cost.
    """

    def __init__(self, estimate_usd: float, lessons: int) -> None:
        super().__init__(
            f"User declined cost-gate prompt: estimate ${estimate_usd:.2f} for {lessons} lessons"
        )
        self.estimate_usd = estimate_usd
        self.lessons = lessons
