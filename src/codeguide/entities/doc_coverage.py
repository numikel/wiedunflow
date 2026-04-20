# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator


class DocCoverage(BaseModel):
    """Documentation coverage metrics computed over the analysis stage symbols.

    Attributes:
        total_symbols: Total number of symbols discovered in Stage 1-2.
        symbols_with_docstring: Count of symbols that have a non-empty docstring.
        ratio: ``symbols_with_docstring / total_symbols``, or ``1.0`` when
            ``total_symbols == 0`` (empty repo is considered fully covered).
        is_low: ``True`` when ``ratio < 0.20`` and there is at least one symbol
            to document — triggers the warning banner in the rendered HTML.
    """

    model_config = ConfigDict(frozen=True)

    total_symbols: int
    symbols_with_docstring: int
    ratio: float
    is_low: bool  # True when ratio < 0.20 and total_symbols > 0

    @model_validator(mode="after")
    def validate_ratio_range(self) -> Self:
        """Ensure ratio is within [0, 1]."""
        if not 0.0 <= self.ratio <= 1.0:
            raise ValueError(f"ratio must be in [0, 1], got {self.ratio}")
        return self

    @model_validator(mode="after")
    def validate_symbols_consistency(self) -> Self:
        """Ensure symbols_with_docstring does not exceed total_symbols."""
        if self.symbols_with_docstring > self.total_symbols:
            raise ValueError(
                f"symbols_with_docstring ({self.symbols_with_docstring}) must be "
                f"<= total_symbols ({self.total_symbols})"
            )
        return self
