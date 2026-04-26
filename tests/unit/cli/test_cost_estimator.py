# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-012: ex-ante cost estimator heuristic."""

from __future__ import annotations

from wiedunflow.cli.cost_estimator import estimate


def test_estimate_applies_safety_factor() -> None:
    """Formula: (symbols * 500 * plan_price + lessons * 8000 * narrate_price) * 1.3.

    Pinned with explicit prices so the assertion is independent of any future
    changes to the default ``MODEL_PRICES`` blended rates.
    """
    result = estimate(
        symbols=100,
        lessons=10,
        clusters=2,
        haiku_price_per_mtok=0.80,
        sonnet_price_per_mtok=3.00,
    )
    # plan: 100 * 500 = 50_000 tokens -> 50_000/1e6 * 0.80 * 1.3 = 0.052
    assert result.haiku_tokens == 50_000
    assert abs(result.haiku_cost_usd - 0.05) < 0.01
    # narrate: 10 * 8000 = 80_000 tokens -> 80_000/1e6 * 3.00 * 1.3 = 0.312
    assert result.sonnet_tokens == 80_000
    assert abs(result.sonnet_cost_usd - 0.31) < 0.02


def test_estimate_runtime_window_scales_with_lessons() -> None:
    result = estimate(symbols=50, lessons=12, clusters=3)
    assert result.runtime_min_minutes < result.runtime_max_minutes
    assert result.runtime_min_minutes >= 1


def test_estimate_zero_symbols_still_valid() -> None:
    result = estimate(symbols=0, lessons=3, clusters=1)
    assert result.haiku_tokens == 0
    assert result.total_tokens == 24_000
    assert result.runtime_min_minutes >= 1
