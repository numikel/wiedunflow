# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for ``StaticPricingCatalog`` (ADR-0013 follow-up — pricing port)."""

from __future__ import annotations

from wiedunflow.adapters.static_pricing_catalog import StaticPricingCatalog
from wiedunflow.cli.cost_estimator import MODEL_PRICES
from wiedunflow.interfaces.pricing_catalog import PricingCatalog


def test_returns_known_anthropic_price() -> None:
    cat = StaticPricingCatalog()
    assert cat.blended_price_per_mtok("claude-opus-4-7") == MODEL_PRICES["claude-opus-4-7"]


def test_returns_known_openai_price() -> None:
    cat = StaticPricingCatalog()
    assert cat.blended_price_per_mtok("gpt-4.1") == MODEL_PRICES["gpt-4.1"]


def test_unknown_model_returns_none() -> None:
    cat = StaticPricingCatalog()
    assert cat.blended_price_per_mtok("not-a-real-model") is None


def test_custom_price_map_overrides_default() -> None:
    cat = StaticPricingCatalog(prices={"my-llama": 0.05})
    assert cat.blended_price_per_mtok("my-llama") == 0.05
    assert cat.blended_price_per_mtok("gpt-4.1") is None


def test_satisfies_pricing_catalog_protocol() -> None:
    cat: PricingCatalog = StaticPricingCatalog()
    assert isinstance(cat, PricingCatalog)
