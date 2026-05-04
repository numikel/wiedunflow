# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import pytest

from wiedunflow.use_cases.spend_meter import (
    _FALLBACK_BLENDED_PRICE_PER_MTOK,
    SpendMeter,
)

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


class _FixedPricing:
    """Stub PricingCatalog that always returns a fixed blended rate."""

    def __init__(self, rate: float) -> None:
        self._rate = rate

    def blended_price_per_mtok(self, model_id: str) -> float | None:
        return self._rate


class _NullPricing:
    """Stub PricingCatalog that always returns None (unknown model)."""

    def blended_price_per_mtok(self, model_id: str) -> float | None:
        return None


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_init_default_values() -> None:
    meter = SpendMeter(budget_usd=10.0)
    assert meter.budget_usd == 10.0
    assert meter.abort_factor == 1.1
    assert meter.total_cost_usd == 0.0
    assert meter.calls == 0


def test_init_custom_abort_factor() -> None:
    meter = SpendMeter(budget_usd=5.0, abort_factor=2.0)
    assert meter.abort_factor == 2.0


def test_init_invalid_budget_raises() -> None:
    with pytest.raises(ValueError, match="budget_usd"):
        SpendMeter(budget_usd=0.0)


def test_init_negative_budget_raises() -> None:
    with pytest.raises(ValueError, match="budget_usd"):
        SpendMeter(budget_usd=-1.0)


def test_init_invalid_abort_factor_raises() -> None:
    with pytest.raises(ValueError, match="abort_factor"):
        SpendMeter(budget_usd=10.0, abort_factor=0.0)


# ---------------------------------------------------------------------------
# charge() / cost accumulation
# ---------------------------------------------------------------------------


def test_charge_accumulates_cost() -> None:
    meter = SpendMeter(budget_usd=1.0)
    meter.charge(model="gpt-5.4", input_tokens=1_000, output_tokens=500)
    assert meter.total_cost_usd > 0


def test_charge_increments_call_counter() -> None:
    meter = SpendMeter(budget_usd=1.0)
    meter.charge(model="gpt-5.4", input_tokens=100, output_tokens=100)
    meter.charge(model="gpt-5.4", input_tokens=100, output_tokens=100)
    assert meter.calls == 2


def test_charge_uses_fallback_when_no_pricing() -> None:
    # 1M tokens x fallback rate / 1M = fallback_rate USD
    meter = SpendMeter(budget_usd=100.0)
    meter.charge(model="unknown-model", input_tokens=1_000_000, output_tokens=0)
    expected = _FALLBACK_BLENDED_PRICE_PER_MTOK
    assert abs(meter.total_cost_usd - expected) < 0.01


def test_charge_uses_fallback_when_pricing_returns_none() -> None:
    pricing = _NullPricing()
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    meter.charge(model="mystery-model", input_tokens=1_000_000, output_tokens=0)
    assert abs(meter.total_cost_usd - _FALLBACK_BLENDED_PRICE_PER_MTOK) < 0.01


def test_charge_zero_tokens_adds_zero_cost() -> None:
    meter = SpendMeter(budget_usd=1.0)
    meter.charge(model="gpt-5.4", input_tokens=0, output_tokens=0)
    assert meter.total_cost_usd == 0.0
    assert meter.calls == 1


# ---------------------------------------------------------------------------
# would_exceed()
# ---------------------------------------------------------------------------


def test_would_exceed_false_below_budget() -> None:
    meter = SpendMeter(budget_usd=100.0)
    meter.charge(model="gpt-5.4", input_tokens=100, output_tokens=100)
    assert not meter.would_exceed()


def test_would_exceed_true_above_abort_factor() -> None:
    # With a very small budget and abort_factor=1.0 even a tiny spend exceeds.
    meter = SpendMeter(budget_usd=0.001, abort_factor=1.0)
    meter.charge(model="gpt-5.4", input_tokens=100_000, output_tokens=100_000)
    assert meter.would_exceed()


def test_would_exceed_false_exactly_at_threshold() -> None:
    # actual == budget * factor should NOT trigger (strict greater-than).
    pricing = _FixedPricing(10.0)  # $10 / MTok
    # 1 MTok x $10 = $10 exactly. budget=$10, factor=1.0 -> threshold $10.
    # would_exceed is actual > threshold — so exactly equal → False.
    meter = SpendMeter(budget_usd=10.0, abort_factor=1.0, pricing=pricing)
    meter.charge(model="any", input_tokens=1_000_000, output_tokens=0)
    assert not meter.would_exceed()


def test_would_exceed_true_just_over_threshold() -> None:
    pricing = _FixedPricing(10.0)
    # Budget $10, factor 1.0 → threshold $10.  Charge 1_000_001 tokens ≈ $10.00001
    meter = SpendMeter(budget_usd=10.0, abort_factor=1.0, pricing=pricing)
    meter.charge(model="any", input_tokens=1_000_001, output_tokens=0)
    assert meter.would_exceed()


# ---------------------------------------------------------------------------
# assert_within_budget()
# ---------------------------------------------------------------------------


def test_assert_within_budget_raises() -> None:
    meter = SpendMeter(budget_usd=0.001, abort_factor=1.0)
    meter.charge(model="gpt-5.4", input_tokens=100_000, output_tokens=100_000)
    with pytest.raises(RuntimeError, match="budget exceeded"):
        meter.assert_within_budget()


def test_assert_within_budget_passes_when_ok() -> None:
    meter = SpendMeter(budget_usd=1_000.0)
    meter.charge(model="gpt-5.4", input_tokens=100, output_tokens=100)
    # Should not raise.
    meter.assert_within_budget()


# ---------------------------------------------------------------------------
# total_cost_cents
# ---------------------------------------------------------------------------


def test_total_cost_cents_is_int() -> None:
    meter = SpendMeter(budget_usd=1.0)
    meter.charge(model="gpt-5.4", input_tokens=1_000, output_tokens=500)
    assert isinstance(meter.total_cost_cents, int)


def test_total_cost_cents_zero_when_no_charge() -> None:
    meter = SpendMeter(budget_usd=1.0)
    assert meter.total_cost_cents == 0


def test_total_cost_cents_rounds_down() -> None:
    # 0.009 USD → 0 cents (int truncation, not rounding)
    pricing = _FixedPricing(9.0)  # $9 / MTok
    # 1000 tokens -> $9 x (1000/1_000_000) = $0.009 -> 0 cents
    meter = SpendMeter(budget_usd=10.0, pricing=pricing)
    meter.charge(model="any", input_tokens=1_000, output_tokens=0)
    assert meter.total_cost_cents == 0  # int(0.009 * 100) = int(0.9) = 0


# ---------------------------------------------------------------------------
# With mock PricingCatalog
# ---------------------------------------------------------------------------


def test_with_mock_pricing_catalog() -> None:
    """PricingCatalog mock returns 10.0 USD/MTok blended."""
    pricing = _FixedPricing(10.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    # 500k tokens x $10/MTok = $5.0
    meter.charge(model="custom-model", input_tokens=250_000, output_tokens=250_000)
    assert abs(meter.total_cost_usd - 5.0) < 1e-6


def test_with_mock_pricing_cost_exceeds_budget() -> None:
    pricing = _FixedPricing(20.0)  # expensive
    meter = SpendMeter(budget_usd=1.0, abort_factor=1.0, pricing=pricing)
    # 200k tokens x $20/MTok = $4.0 > $1.0 budget
    meter.charge(model="expensive", input_tokens=100_000, output_tokens=100_000)
    assert meter.would_exceed()
    with pytest.raises(RuntimeError):
        meter.assert_within_budget()
