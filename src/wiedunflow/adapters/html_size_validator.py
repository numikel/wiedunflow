# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""HTML output size budget validator (US-050).

Spec budgets:
- Target: <8 MB for a medium repo
- Hard warn: >20 MB (strongly discourage shipping)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SizeVerdict = Literal["ok", "over_soft_budget", "over_hard_budget"]

_SOFT_BUDGET_BYTES = 8 * 1024 * 1024
_HARD_BUDGET_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class SizeReport:
    """Size-budget check result for a single HTML output."""

    path: Path
    size_bytes: int
    verdict: SizeVerdict
    message: str

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def validate_size(path: Path) -> SizeReport:
    """Inspect the rendered HTML file size against the MVP budget.

    Args:
        path: Path to the rendered ``tutorial.html``.

    Returns:
        SizeReport with verdict ``ok`` / ``over_soft_budget`` / ``over_hard_budget``
        and a human-readable message. Callers decide whether to log warn/error.
    """
    size = path.stat().st_size
    if size > _HARD_BUDGET_BYTES:
        return SizeReport(
            path=path,
            size_bytes=size,
            verdict="over_hard_budget",
            message=(
                f"tutorial.html size {size / (1024 * 1024):.1f} MB exceeds hard budget 20 MB — "
                "consider pruning code excerpts or lowering --max-lessons"
            ),
        )
    if size > _SOFT_BUDGET_BYTES:
        return SizeReport(
            path=path,
            size_bytes=size,
            verdict="over_soft_budget",
            message=(
                f"tutorial.html size {size / (1024 * 1024):.1f} MB exceeds target 8 MB — "
                "medium repos should fit comfortably below this threshold"
            ),
        )
    return SizeReport(
        path=path,
        size_bytes=size,
        verdict="ok",
        message=f"tutorial.html size {size / (1024 * 1024):.2f} MB within budget",
    )
