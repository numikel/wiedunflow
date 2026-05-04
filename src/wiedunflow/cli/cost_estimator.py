# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Ex-ante cost estimator for the cost gate (US-012, US-070).

Heuristic per PRD AC US-012: ``(symbols * 500 * plan_price) + (lessons * 8000
* narrate_price)`` multiplied by safety factor ``1.3``. The exact token counts
are intentionally conservative — the gate exists to catch runaway costs, not
to predict them to the cent.

ADR-0020 (v0.9.5): ``MODEL_PRICES`` maps each known model id to an
``(input, output)`` tuple in USD per 1M tokens. Live cost accounting
(``SpendMeter``) applies the two rates separately to the actually-billed
input and output token counts. The preflight estimator below still wants a
single blended figure (we don't yet know the input/output split until the
LLM responds), so it composes ``0.6 * input + 0.4 * output`` — the typical
planning + narration workload split — via :func:`blended_from_prices`.

Sourced from the providers' published pricing pages on 2026-04-25 / 2026-04-26.
Update this map whenever a new model lands; falls back to the legacy
Haiku / Opus rates when an unknown id is queried (small over-estimate is
safer than a silent under-estimate at the cost gate).

LiteLLM dynamic catalog (`LiteLLMPricingCatalog`) was added in v0.5.0 and
overrides this static map for any model the community catalog ships.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wiedunflow.interfaces.pricing_catalog import PricingCatalog

# Blended weights used by :func:`blended_from_prices` when callers want a single
# rate for preflight estimates (input + output token counts not yet known).
_BLENDED_INPUT_WEIGHT = 0.60
_BLENDED_OUTPUT_WEIGHT = 0.40

# (input USD/MTok, output USD/MTok) per model id.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    # ─── Anthropic Claude 4.x ──────────────────────────────────────────────
    "claude-haiku-4-5": (0.80, 4.00),
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-6": (3.00, 12.00),
    "claude-sonnet-4-5-20250929": (3.00, 12.00),
    "claude-sonnet-4-20250514": (3.00, 12.00),
    "claude-opus-4-7": (15.00, 60.00),
    "claude-opus-4-6": (15.00, 60.00),
    "claude-opus-4-5-20251101": (15.00, 60.00),
    "claude-opus-4-1-20250805": (15.00, 60.00),
    "claude-opus-4-20250514": (15.00, 60.00),
    # ─── OpenAI GPT 4.x ────────────────────────────────────────────────────
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "gpt-4": (30.00, 60.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    # ─── OpenAI o-series reasoning ─────────────────────────────────────────
    "o1": (15.00, 60.00),
    "o1-pro": (150.00, 600.00),
    "o3": (2.00, 8.00),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
    # ─── OpenAI GPT 5.x (released 2026; pricing verified 2026-04-26) ────────
    "gpt-5": (3.00, 12.00),
    "gpt-5-mini": (0.40, 1.60),
    "gpt-5-nano": (0.10, 0.40),
    "gpt-5.4": (2.50, 15.00),  # default in v0.7.0+ per ADR-0015
    "gpt-5.4-mini": (0.75, 4.50),  # default per-symbol/describe tier
    "gpt-5.4-nano": (0.10, 0.40),
    "gpt-5.4-pro": (30.00, 180.00),
    "gpt-5-pro": (15.00, 60.00),
    "gpt-5.2": (3.00, 12.00),
    "gpt-5.2-pro": (15.00, 60.00),
    "gpt-5.1": (3.00, 12.00),
    # ─── Local / OSS endpoints ────────────────────────────────────────────
    "not-needed": (0.0, 0.0),
}


def blended_from_prices(prices: tuple[float, float]) -> float:
    """Return the conventional ``0.6 * input + 0.4 * output`` blended USD/MTok.

    Used for preflight estimates where the actual input/output token split
    is not yet known. Live spend tracking applies the two rates separately
    via :class:`SpendMeter`.
    """
    in_price, out_price = prices
    return _BLENDED_INPUT_WEIGHT * in_price + _BLENDED_OUTPUT_WEIGHT * out_price


_HAIKU_USD_PER_MTOK = blended_from_prices(MODEL_PRICES["claude-haiku-4-5"])
_SONNET_USD_PER_MTOK = blended_from_prices(MODEL_PRICES["claude-sonnet-4-6"])
_OPUS_USD_PER_MTOK = blended_from_prices(MODEL_PRICES["claude-opus-4-7"])
_SAFETY_FACTOR = 1.3
_TOKENS_PER_SYMBOL_HAIKU = 500
_TOKENS_PER_LESSON_SONNET = 8000
_RUNTIME_MIN_PER_LESSON_SEC = 40
_RUNTIME_MAX_PER_LESSON_SEC = 110


def lookup_model_price(
    model_id: str | None,
    *,
    fallback: float,
    pricing_catalog: PricingCatalog | None = None,
) -> float:
    """Return the blended USD/MTok price for ``model_id``, or ``fallback``.

    Resolution order:
    1. ``pricing_catalog.prices_per_mtok(model_id)`` (typically a
       chain of ``CachedPricingCatalog(LiteLLM)`` → ``StaticPricingCatalog``)
       blended via :func:`blended_from_prices`.
    2. ``MODEL_PRICES`` direct hit (legacy path; preserves backwards compat
       when callers don't inject a catalog) blended likewise.
    3. ``fallback`` — the caller's safe over-estimate for the tier.
    """
    if not model_id:
        return fallback
    if pricing_catalog is not None:
        prices = pricing_catalog.prices_per_mtok(model_id)
        if prices is not None:
            return blended_from_prices(prices)
    direct = MODEL_PRICES.get(model_id)
    if direct is not None:
        return blended_from_prices(direct)
    return fallback


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
    plan_model: str | None = None,
    narrate_model: str | None = None,
    pricing_catalog: PricingCatalog | None = None,
) -> CostEstimate:
    """Return a conservative cost estimate for the planned tutorial.

    Args:
        symbols: Number of code symbols that will receive a planning-tier
            description (light model — Haiku / GPT-4.1-mini / etc.).
        lessons: Number of narration lessons (heavy model — Opus / GPT-4.1 / etc.).
        clusters: Number of feature clusters (affects runtime bound).
        haiku_price_per_mtok: Explicit override for the planning-tier price.
            Ignored when ``plan_model`` resolves in ``MODEL_PRICES``.
        sonnet_price_per_mtok: Explicit override for the narration-tier price.
            Ignored when ``narrate_model`` resolves in ``MODEL_PRICES``.
        plan_model: Configured planning model id (e.g. ``"gpt-4.1-mini"``,
            ``"claude-haiku-4-5"``). When set and known, its blended price
            from ``MODEL_PRICES`` overrides ``haiku_price_per_mtok``.
        narrate_model: Configured narration model id; overrides
            ``sonnet_price_per_mtok`` when known.

    Returns:
        ``CostEstimate`` with per-model token and cost breakdowns plus an
        expected runtime window in minutes.
    """
    plan_price = lookup_model_price(
        plan_model, fallback=haiku_price_per_mtok, pricing_catalog=pricing_catalog
    )
    narrate_price = lookup_model_price(
        narrate_model, fallback=sonnet_price_per_mtok, pricing_catalog=pricing_catalog
    )

    haiku_tokens = symbols * _TOKENS_PER_SYMBOL_HAIKU
    sonnet_tokens = lessons * _TOKENS_PER_LESSON_SONNET

    haiku_cost = (haiku_tokens / 1_000_000.0) * plan_price * _SAFETY_FACTOR
    sonnet_cost = (sonnet_tokens / 1_000_000.0) * narrate_price * _SAFETY_FACTOR
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
