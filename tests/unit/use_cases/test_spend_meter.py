# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import pytest

from wiedunflow.use_cases.spend_meter import (
    _FALLBACK_INPUT_PRICE_PER_MTOK,
    _FALLBACK_OUTPUT_PRICE_PER_MTOK,
    SpendMeter,
)

# ---------------------------------------------------------------------------
# Helpers / stubs
# ---------------------------------------------------------------------------


class _FixedPricing:
    """Stub PricingCatalog that always returns fixed (input, output) rates."""

    def __init__(self, *, input_rate: float, output_rate: float) -> None:
        self._input = input_rate
        self._output = output_rate

    def prices_per_mtok(self, model_id: str) -> tuple[float, float] | None:
        return self._input, self._output


class _NullPricing:
    """Stub PricingCatalog that always returns None (unknown model)."""

    def prices_per_mtok(self, model_id: str) -> tuple[float, float] | None:
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
    # 1M input tokens at fallback input rate.
    meter = SpendMeter(budget_usd=100.0)
    meter.charge(model="unknown-model", input_tokens=1_000_000, output_tokens=0)
    assert abs(meter.total_cost_usd - _FALLBACK_INPUT_PRICE_PER_MTOK) < 0.01


def test_charge_uses_fallback_when_pricing_returns_none() -> None:
    pricing = _NullPricing()
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    meter.charge(model="mystery-model", input_tokens=0, output_tokens=1_000_000)
    assert abs(meter.total_cost_usd - _FALLBACK_OUTPUT_PRICE_PER_MTOK) < 0.01


def test_charge_zero_tokens_adds_zero_cost() -> None:
    meter = SpendMeter(budget_usd=1.0)
    meter.charge(model="gpt-5.4", input_tokens=0, output_tokens=0)
    assert meter.total_cost_usd == 0.0
    assert meter.calls == 1


def test_charge_applies_input_and_output_rates_separately() -> None:
    """Output tokens are 5x more expensive than input -- meter must reflect it."""
    pricing = _FixedPricing(input_rate=2.0, output_rate=10.0)  # 1:5 spread
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    # 1M input @ $2 = $2; 1M output @ $10 = $10; total $12.
    meter.charge(model="any", input_tokens=1_000_000, output_tokens=1_000_000)
    assert meter.total_cost_usd == pytest.approx(12.0)


def test_charge_output_dominates_typical_workload() -> None:
    """Generation-heavy workload (1:5 in:out tokens) is dominated by output cost."""
    pricing = _FixedPricing(input_rate=2.0, output_rate=10.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    # 100k input @ $2/MTok = $0.20; 500k output @ $10/MTok = $5.00. Total $5.20.
    meter.charge(model="any", input_tokens=100_000, output_tokens=500_000)
    assert meter.total_cost_usd == pytest.approx(5.20)


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
    pricing = _FixedPricing(input_rate=10.0, output_rate=10.0)  # uniform $10 / MTok
    # 1 MTok input @ $10 = $10 exactly. budget=$10, factor=1.0 -> threshold $10.
    # would_exceed is actual > threshold — so exactly equal → False.
    meter = SpendMeter(budget_usd=10.0, abort_factor=1.0, pricing=pricing)
    meter.charge(model="any", input_tokens=1_000_000, output_tokens=0)
    assert not meter.would_exceed()


def test_would_exceed_true_just_over_threshold() -> None:
    pricing = _FixedPricing(input_rate=10.0, output_rate=10.0)
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


def test_total_cost_cents_rounds_to_nearest() -> None:
    """Sub-cent fractions round half-to-even (banker's), not toward zero.

    $0.0095 -> 0.95 cents -> 1 cent (nearest).
    """
    pricing = _FixedPricing(input_rate=9.5, output_rate=9.5)  # $9.5 / MTok
    # 1000 tokens -> $9.5 x (1000/1_000_000) = $0.0095 -> 1 cent
    meter = SpendMeter(budget_usd=10.0, pricing=pricing)
    meter.charge(model="any", input_tokens=1_000, output_tokens=0)
    assert meter.total_cost_cents == 1


def test_total_cost_cents_rounds_below_half_to_zero() -> None:
    pricing = _FixedPricing(input_rate=4.0, output_rate=4.0)
    # 1000 tokens -> $4 x (1000/1_000_000) = $0.004 -> 0.4 cents -> 0
    meter = SpendMeter(budget_usd=10.0, pricing=pricing)
    meter.charge(model="any", input_tokens=1_000, output_tokens=0)
    assert meter.total_cost_cents == 0


# ---------------------------------------------------------------------------
# With mock PricingCatalog
# ---------------------------------------------------------------------------


def test_with_mock_pricing_catalog() -> None:
    """PricingCatalog mock returns explicit input/output rates."""
    pricing = _FixedPricing(input_rate=10.0, output_rate=10.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    # 250k input + 250k output @ $10 each = $5.0
    meter.charge(model="custom-model", input_tokens=250_000, output_tokens=250_000)
    assert abs(meter.total_cost_usd - 5.0) < 1e-6


def test_with_mock_pricing_cost_exceeds_budget() -> None:
    pricing = _FixedPricing(input_rate=20.0, output_rate=20.0)  # expensive
    meter = SpendMeter(budget_usd=1.0, abort_factor=1.0, pricing=pricing)
    # 100k + 100k tokens x $20/MTok = $4.0 > $1.0 budget
    meter.charge(model="expensive", input_tokens=100_000, output_tokens=100_000)
    assert meter.would_exceed()
    with pytest.raises(RuntimeError):
        meter.assert_within_budget()


# ---------------------------------------------------------------------------
# Cache token accounting (Anthropic + OpenAI multipliers)
# ---------------------------------------------------------------------------


def test_charge_anthropic_cache_write_costs_125_percent_of_input() -> None:
    """Anthropic cache_creation tokens bill at 1.25x the regular input rate.

    Cleanly isolated: 0 regular input, 0 output, 1M cache write tokens.
    With a 10.0 input rate the call costs 1M * 10 * 1.25 / 1M = $12.50.
    """
    pricing = _FixedPricing(input_rate=10.0, output_rate=10.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    meter.charge(
        model="claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000_000,
        provider="anthropic",
    )
    assert meter.total_cost_usd == pytest.approx(12.50, rel=1e-6)


def test_charge_anthropic_cache_read_costs_10_percent_of_input() -> None:
    """Anthropic cache_read tokens bill at 0.1x the regular input rate."""
    pricing = _FixedPricing(input_rate=10.0, output_rate=10.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    meter.charge(
        model="claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=1_000_000,
        provider="anthropic",
    )
    assert meter.total_cost_usd == pytest.approx(1.00, rel=1e-6)


def test_charge_anthropic_all_three_tiers_summed() -> None:
    """Anthropic charges regular + cache_write x 1.25 + cache_read x 0.1 + output."""
    pricing = _FixedPricing(input_rate=10.0, output_rate=20.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    # 100k regular input + 200k cache write + 300k cache read + 50k output
    # = 100k*10 + 200k*10*1.25 + 300k*10*0.1 + 50k*20 = 1.0 + 2.5 + 0.3 + 1.0 = 4.8
    meter.charge(
        model="claude-sonnet-4-6",
        input_tokens=100_000,
        output_tokens=50_000,
        cache_creation_input_tokens=200_000,
        cache_read_input_tokens=300_000,
        provider="anthropic",
    )
    assert meter.total_cost_usd == pytest.approx(4.80, rel=1e-6)


def test_charge_openai_cached_tokens_subtract_from_input_then_bill_at_half() -> None:
    """OpenAI cached tokens are already in prompt_tokens — subtract then bill at 0.5x.

    1M total prompt_tokens of which 600k were cache hits at 0.5x and 400k
    regular: 400k*10 + 600k*10*0.5 = 4.0 + 3.0 = $7.0.
    """
    pricing = _FixedPricing(input_rate=10.0, output_rate=10.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    meter.charge(
        model="gpt-5.4",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_input_tokens=600_000,
        provider="openai",
    )
    assert meter.total_cost_usd == pytest.approx(7.00, rel=1e-6)


def test_charge_provider_auto_detects_anthropic_from_claude_prefix() -> None:
    """provider='auto' (default) routes claude-* models through Anthropic accounting."""
    pricing = _FixedPricing(input_rate=10.0, output_rate=10.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    meter.charge(
        model="claude-opus-4-7",
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=1_000_000,
        # provider defaults to "auto"
    )
    # Anthropic: 1M * 10 * 0.1 = $1.0. OpenAI accounting would give a different result.
    assert meter.total_cost_usd == pytest.approx(1.00, rel=1e-6)


def test_charge_provider_auto_detects_openai_from_gpt_prefix() -> None:
    """provider='auto' routes gpt-* models through OpenAI accounting (cached subtracted)."""
    pricing = _FixedPricing(input_rate=10.0, output_rate=10.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    meter.charge(
        model="gpt-5.4-mini",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_input_tokens=1_000_000,  # entirely cached
    )
    # OpenAI: 0 regular + 1M * 10 * 0.5 = $5.0.
    assert meter.total_cost_usd == pytest.approx(5.00, rel=1e-6)


def test_charge_unknown_model_prefix_falls_back_to_anthropic_style() -> None:
    """Unknown prefixes (custom / OSS) use Anthropic-style — bit-equivalent legacy path.

    When no cache_* kwargs are passed, this branch yields the same cost as
    the pre-cache pricing formula, so test fixtures with names like
    'expensive' keep working.
    """
    pricing = _FixedPricing(input_rate=10.0, output_rate=20.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    meter.charge(model="ollama-mistral:7b", input_tokens=100_000, output_tokens=50_000)
    # input 100k*10 + output 50k*20 = 1.0 + 1.0 = $2.0 — matches legacy.
    assert meter.total_cost_usd == pytest.approx(2.00, rel=1e-6)


def test_charge_explicit_provider_overrides_prefix_detection() -> None:
    """Passing provider='openai' with a claude-* model name forces OpenAI accounting."""
    pricing = _FixedPricing(input_rate=10.0, output_rate=10.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    # Trick: claude-* prefix would normally route to Anthropic, but explicit
    # provider hint overrides. OpenAI's cached-tokens accounting subtracts.
    meter.charge(
        model="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_input_tokens=1_000_000,
        provider="openai",
    )
    # OpenAI: 0 regular + 1M * 10 * 0.5 = $5.0 (NOT Anthropic's $1.0).
    assert meter.total_cost_usd == pytest.approx(5.00, rel=1e-6)


# ---------------------------------------------------------------------------
# Per-lesson budget window (begin_lesson / end_lesson lifecycle)
# ---------------------------------------------------------------------------


def test_begin_lesson_rejects_non_positive_cap() -> None:
    meter = SpendMeter(budget_usd=10.0)
    with pytest.raises(ValueError):
        meter.begin_lesson(cap_usd=0.0)
    with pytest.raises(ValueError):
        meter.begin_lesson(cap_usd=-1.0)


def test_per_lesson_window_aborts_when_lesson_cap_exceeded() -> None:
    """would_exceed must trigger when a single lesson burns past its cap,
    even though the global budget is nowhere near exhausted.
    """
    pricing = _FixedPricing(input_rate=1.0, output_rate=4.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)
    # Pre-spend $5 unrelated to any lesson — sets baseline drift for the
    # window snapshot.
    meter.charge(model="gpt-4o", input_tokens=1_000_000, output_tokens=1_000_000)
    assert meter.total_cost_usd == pytest.approx(5.0, rel=1e-6)

    # Open per-lesson window with a tight $1 cap.
    meter.begin_lesson(cap_usd=1.0)
    assert meter.would_exceed() is False  # nothing spent inside the window yet

    # Spend $0.50 inside the window — still under the cap (+10% buffer).
    meter.charge(model="gpt-4o", input_tokens=100_000, output_tokens=100_000)
    assert meter.would_exceed() is False

    # Spend another $1.50 inside the window — now over $1 * 1.1 buffer.
    meter.charge(model="gpt-4o", input_tokens=300_000, output_tokens=300_000)
    assert meter.would_exceed() is True
    # Global budget ($100) is nowhere near exhausted — the trigger is
    # specifically the per-lesson cap.
    assert meter.total_cost_usd < meter.budget_usd


def test_end_lesson_reverts_to_global_only_checks() -> None:
    """After end_lesson the meter must not consider the per-lesson cap anymore."""
    pricing = _FixedPricing(input_rate=1.0, output_rate=4.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)

    meter.begin_lesson(cap_usd=0.50)
    meter.charge(model="gpt-4o", input_tokens=300_000, output_tokens=300_000)
    assert meter.would_exceed() is True  # over the lesson cap

    meter.end_lesson()
    assert meter.would_exceed() is False  # window closed, only global matters
    assert meter.total_cost_usd < meter.budget_usd


def test_begin_lesson_can_be_called_repeatedly_to_reset_baseline() -> None:
    """Opening a new window without an explicit end resets the baseline
    snapshot — supports the orchestrator-retries-same-lesson scenario.
    """
    pricing = _FixedPricing(input_rate=1.0, output_rate=4.0)
    meter = SpendMeter(budget_usd=100.0, pricing=pricing)

    meter.begin_lesson(cap_usd=2.0)
    meter.charge(model="gpt-4o", input_tokens=200_000, output_tokens=200_000)  # $1.0
    assert meter.would_exceed() is False

    # Re-open with a fresh $1 cap — baseline is "now", so the next charge
    # is measured from zero again.
    meter.begin_lesson(cap_usd=1.0)
    assert meter.would_exceed() is False  # fresh window, nothing in it yet
    meter.charge(model="gpt-4o", input_tokens=200_000, output_tokens=200_000)  # $1.0
    # $1.0 in this window is exactly at the cap (no 10% buffer breach yet).
    assert meter.would_exceed() is False


def test_end_lesson_is_idempotent_without_matching_begin() -> None:
    """end_lesson must be safe to call without a prior begin_lesson — supports
    try/finally idioms in the orchestrator.
    """
    meter = SpendMeter(budget_usd=10.0)
    # No exception:
    meter.end_lesson()
    meter.end_lesson()
    assert meter.would_exceed() is False
