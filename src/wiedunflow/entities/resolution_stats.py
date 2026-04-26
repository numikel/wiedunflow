# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

_MIN_PCT = 0.0
_MAX_PCT = 100.0


class ResolutionStats(BaseModel):
    """Jedi resolution 3-tier coverage summary (US-039).

    Tiers:
      - resolved:   symbol's definition was found statically via Jedi.
      - uncertain:  partial resolution (e.g. attribute on ambiguous type) or dynamic marker.
      - unresolved: Jedi returned empty set for this reference.

    resolved_pct := 100 * resolved / max(resolved + uncertain + unresolved, 1).
    """

    model_config = ConfigDict(frozen=True)

    resolved_pct: float  # 0.0 — 100.0
    uncertain_count: int
    unresolved_count: int

    @model_validator(mode="after")
    def validate_resolved_pct_range(self) -> Self:
        if not _MIN_PCT <= self.resolved_pct <= _MAX_PCT:
            raise ValueError(f"resolved_pct must be in [0, 100], got {self.resolved_pct}")
        return self

    @model_validator(mode="after")
    def validate_counts_non_negative(self) -> Self:
        if self.uncertain_count < 0:
            raise ValueError("uncertain_count must be >= 0")
        if self.unresolved_count < 0:
            raise ValueError("unresolved_count must be >= 0")
        return self
