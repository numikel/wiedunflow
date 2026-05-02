# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, computed_field, model_validator

_MIN_PCT = 0.0
_MAX_PCT = 100.0


class ResolutionStats(BaseModel):
    """Jedi resolution 4-tier coverage summary (US-039, Tier 2 added v0.9.0).

    Tiers:
      - resolved:            symbol's definition found statically via Jedi infer().
      - resolved_heuristic:  Jedi infer() returned [] but name-based fallback matched
                             exactly one symbol in the AST snapshot (Tier 2).
      - uncertain:           partial resolution (Jedi infer() non-empty but no symbol
                             match, OR ambiguous heuristic with >1 candidates).
      - unresolved:          Jedi infer() empty AND no heuristic match (or caller symbol
                             not found / source unreadable / Jedi exception).

    resolved_pct := 100 * strict_resolved / max(total, 1)   — backward-compatible.
    resolved_pct_with_heuristic := 100 * (strict_resolved + heuristic_resolved) / max(total, 1).
    """

    model_config = ConfigDict(frozen=True)

    resolved_pct: float  # 0.0 — 100.0  (strict Jedi only — backward compat)
    uncertain_count: int
    unresolved_count: int
    resolved_heuristic_count: int = 0  # Tier 2: name-based fallback resolutions

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
        if self.resolved_heuristic_count < 0:
            raise ValueError("resolved_heuristic_count must be >= 0")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_pct_with_heuristic(self) -> float:
        """Informational: strict + heuristic resolved as percentage of total edges.

        Not used for quality gates (use ``resolved_pct`` for backward-compat gating).
        Useful for logging cold-start improvement diagnostics.
        """
        # Derive strict_resolved_count from resolved_pct and the other counts.
        # total = strict_resolved + uncertain + unresolved + heuristic
        # resolved_pct = 100 * strict_resolved / total  (when total > 0)
        # => strict_resolved = resolved_pct * total / 100
        total_non_strict = (
            self.uncertain_count + self.unresolved_count + self.resolved_heuristic_count
        )
        # We cannot reconstruct strict_resolved_count without storing it, but we can
        # compute it indirectly: use resolved_pct to derive the combined numerator.
        # combined_pct = resolved_pct + 100 * heuristic / total
        # Instead: re-derive total from resolved_pct definition.
        # Let R = strict_resolved.  resolved_pct = 100*R/total  => R = resolved_pct*total/100
        # total = R + uncertain + unresolved + heuristic
        # total = (resolved_pct/100)*total + total_non_strict
        # total*(1 - resolved_pct/100) = total_non_strict
        # total = total_non_strict / (1 - resolved_pct/100)   [when resolved_pct < 100]
        if total_non_strict == 0 and self.resolved_pct == _MAX_PCT:
            # Either total==0 OR all edges strictly resolved — heuristic adds nothing.
            return _MAX_PCT
        if self.resolved_pct >= _MAX_PCT:
            return _MAX_PCT
        denom_fraction = 1.0 - self.resolved_pct / _MAX_PCT
        if denom_fraction <= 0.0:
            return _MAX_PCT
        total = total_non_strict / denom_fraction
        if total <= 0.0:
            return _MAX_PCT
        strict_resolved = self.resolved_pct * total / _MAX_PCT
        combined = strict_resolved + self.resolved_heuristic_count
        return min(_MAX_PCT, _MAX_PCT * combined / total)
