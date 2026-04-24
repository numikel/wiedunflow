# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Ex-ante cost estimator for the cost gate (US-012, US-070).

Heuristic per PRD AC US-012: ``(symbols * 500 * haiku_price) + (lessons * 8000
* sonnet_price)`` multiplied by safety factor ``1.3``. The exact token counts
are intentionally conservative — the gate exists to catch runaway costs, not
to predict them to the cent.
"""

from __future__ import annotations

from dataclasses import dataclass

# Model cost per million tokens (USD). Source: ux-spec §CLI.cost-gate.
_HAIKU_USD_PER_MTOK = 0.80
_SONNET_USD_PER_MTOK = 3.00
_OPUS_USD_PER_MTOK = 15.00
_SAFETY_FACTOR = 1.3
_TOKENS_PER_SYMBOL_HAIKU = 500
_TOKENS_PER_LESSON_SONNET = 8000
_RUNTIME_MIN_PER_LESSON_SEC = 40
_RUNTIME_MAX_PER_LESSON_SEC = 110


@dataclass(frozen=True)
class CostEstimate:
    """Estimated cost + runtime bundle used by the cost gate."""

    symbols: int
    lessons: int
    clusters: int
    haiku_tokens: int
    haiku_cost_usd: float
    sonnet_tokens: int
    sonnet_cost_usd: float
    total_tokens: int
    total_cost_usd: float
    runtime_min_minutes: int
    runtime_max_minutes: int


def estimate(
    *,
    symbols: int,
    lessons: int,
    clusters: int,
    haiku_price_per_mtok: float = _HAIKU_USD_PER_MTOK,
    sonnet_price_per_mtok: float = _SONNET_USD_PER_MTOK,
) -> CostEstimate:
    """Return a conservative cost estimate for the planned tutorial.

    Args:
        symbols: Number of code symbols that will receive a Haiku description.
        lessons: Number of narration lessons (Sonnet).
        clusters: Number of feature clusters (affects runtime bound).
        haiku_price_per_mtok: Override for Haiku price (testing / alt providers).
        sonnet_price_per_mtok: Override for Sonnet price.

    Returns:
        ``CostEstimate`` with per-model token and cost breakdowns plus an
        expected runtime window in minutes.
    """
    haiku_tokens = symbols * _TOKENS_PER_SYMBOL_HAIKU
    sonnet_tokens = lessons * _TOKENS_PER_LESSON_SONNET

    haiku_cost = (haiku_tokens / 1_000_000.0) * haiku_price_per_mtok * _SAFETY_FACTOR
    sonnet_cost = (sonnet_tokens / 1_000_000.0) * sonnet_price_per_mtok * _SAFETY_FACTOR
    total_cost = haiku_cost + sonnet_cost
    total_tokens = haiku_tokens + sonnet_tokens

    runtime_min_sec = lessons * _RUNTIME_MIN_PER_LESSON_SEC
    runtime_max_sec = lessons * _RUNTIME_MAX_PER_LESSON_SEC

    return CostEstimate(
        symbols=symbols,
        lessons=lessons,
        clusters=clusters,
        haiku_tokens=haiku_tokens,
        haiku_cost_usd=round(haiku_cost, 2),
        sonnet_tokens=sonnet_tokens,
        sonnet_cost_usd=round(sonnet_cost, 2),
        total_tokens=total_tokens,
        total_cost_usd=round(total_cost, 2),
        runtime_min_minutes=max(1, runtime_min_sec // 60),
        runtime_max_minutes=max(2, runtime_max_sec // 60),
    )
