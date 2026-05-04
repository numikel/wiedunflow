# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``StaticPricingCatalog`` — always-available hardcoded price lookup.

Used as the leaf fallback in every ``ChainedPricingCatalog``. Source of truth
is ``cost_estimator.MODEL_PRICES`` so the maintenance surface stays single.

ADR-0020 (v0.9.5): returns ``(input, output)`` USD/MTok tuples.
"""

from __future__ import annotations

from wiedunflow.cli.cost_estimator import MODEL_PRICES


class StaticPricingCatalog:
    """``PricingCatalog`` impl backed by the hardcoded ``MODEL_PRICES`` dict."""

    def __init__(self, prices: dict[str, tuple[float, float]] | None = None) -> None:
        """Initialize the catalog.

        Args:
            prices: Optional override for tests. Defaults to the live
                ``MODEL_PRICES`` map maintained in ``cost_estimator.py``.
                Each value is ``(input_per_mtok, output_per_mtok)``.
        """
        self._prices: dict[str, tuple[float, float]] = (
            dict(prices) if prices is not None else dict(MODEL_PRICES)
        )

    def prices_per_mtok(self, model_id: str) -> tuple[float, float] | None:
        """Return ``(input, output)`` USD/MTok for ``model_id`` (case-sensitive, exact match)."""
        return self._prices.get(model_id)
