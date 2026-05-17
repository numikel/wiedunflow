# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Ex-ante cost estimator for the cost gate (US-012, US-070).

Models the v0.9.0+ multi-agent pipeline (ADR-0016): per-lesson Orchestrator ->
Researcher x N -> Writer -> Reviewer calls, plus a single Planning call for
Stage 4. Token ceilings are derived from the agent-card ``max_iterations`` and
budgeted output sizes; they are intentionally conservative.

ADR-0020 (v0.9.5): ``MODEL_PRICES`` maps each known model id to an
``(input, output)`` tuple in USD per 1M tokens. The preflight estimator applies
the two rates separately to per-role input and output token counts, matching
the live ``SpendMeter`` accounting. A safety factor of 1.3 is applied
per-role before summing to the grand total.

Sourced from the providers' published pricing pages on 2026-04-25 / 2026-04-26.
Update this map whenever a new model lands; falls back to a conservative
hard-coded ceiling when an unknown id is queried (small over-estimate is
safer than a silent under-estimate at the cost gate).

LiteLLM dynamic catalog (``LiteLLMPricingCatalog``) was added in v0.5.0 and
overrides this static map for any model the community catalog ships.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wiedunflow.interfaces.pricing_catalog import PricingCatalog

# ---------------------------------------------------------------------------
# Blended-rate helpers (kept for callers that want a single scalar, e.g. menu
# picker price display and StaticPricingCatalog bootstrap).
# ---------------------------------------------------------------------------

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
    "gpt-5.4": (2.50, 15.00),  # default orchestrator/writer per ADR-0015
    "gpt-5.4-mini": (0.75, 4.50),  # default researcher/reviewer tier
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


# ---------------------------------------------------------------------------
# Safety factor (applied per-role so per-role costs sum to the grand total).
# ---------------------------------------------------------------------------

_SAFETY_FACTOR = 1.3

# ---------------------------------------------------------------------------
# Per-role conservative token ceilings derived from agent cards
# (max_iterations x budgeted output x typical input growth).
# ---------------------------------------------------------------------------

_PLANNING_BASE_INPUT_TOKENS = 25_000
_PLANNING_PER_SYMBOL_INPUT_TOKENS = 100
_PLANNING_OUTPUT_TOKENS = 8_000

_ORCH_INPUT_PER_LESSON = 25_000
_ORCH_OUTPUT_PER_LESSON = 3_000

_RESEARCH_INPUT_PER_CALL = 60_000
_RESEARCH_OUTPUT_PER_CALL = 1_500
_RESEARCH_CALLS_PER_LESSON = 3  # avg from agent_card budgets.max_iterations=12; typical 2-4

_WRITER_INPUT_PER_CALL = 50_000
_WRITER_OUTPUT_PER_CALL = 3_000
_WRITER_CALLS_PER_LESSON = 1.5  # 1 + reviewer-retry rate

_REVIEWER_INPUT_PER_CALL = 30_000
_REVIEWER_OUTPUT_PER_CALL = 1_000
_REVIEWER_CALLS_PER_LESSON = 1.5

# Multi-agent runtime per lesson (sequential per-lesson invariant; 5-9 calls x per-call latency).
_RUNTIME_MIN_PER_LESSON_SEC = 90
_RUNTIME_MAX_PER_LESSON_SEC = 240

# Conservative hard-fallback prices when a model id is completely unknown.
_FALLBACK_INPUT_USD_PER_MTOK = 5.0
_FALLBACK_OUTPUT_USD_PER_MTOK = 25.0

# Default models matching agent_orchestrator._DEFAULT_MODELS (ADR-0015/0016).
_DEFAULT_PLAN_MODEL = "gpt-5.4"
_DEFAULT_ORCHESTRATOR_MODEL = "gpt-5.4"
_DEFAULT_RESEARCHER_MODEL = "gpt-5.4-mini"
_DEFAULT_WRITER_MODEL = "gpt-5.4"
_DEFAULT_REVIEWER_MODEL = "gpt-5.4-mini"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleCost:
    """Per-role token usage and cost for one pipeline role."""

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass(frozen=True)
class CostEstimate:
    """Estimated cost + runtime bundle for the multi-agent narration pipeline."""

    symbols: int
    lessons: int
    clusters: int
    planning: RoleCost
    orchestrator: RoleCost
    researcher: RoleCost
    writer: RoleCost
    reviewer: RoleCost
    total_tokens: int
    total_cost_usd: float
    runtime_min_minutes: int
    runtime_max_minutes: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_role_prices(
    model_id: str | None,
    default_model_id: str,
    pricing_catalog: PricingCatalog | None,
) -> tuple[str, float, float]:
    """Return ``(resolved_model_id, input_price_per_mtok, output_price_per_mtok)``.

    Resolution: pricing_catalog.prices_per_mtok() → MODEL_PRICES → conservative
    hard fallback (5.0 in, 25.0 out).
    """
    resolved = model_id if model_id else default_model_id
    if pricing_catalog is not None:
        prices = pricing_catalog.prices_per_mtok(resolved)
        if prices is not None:
            return resolved, prices[0], prices[1]
    direct = MODEL_PRICES.get(resolved)
    if direct is not None:
        return resolved, direct[0], direct[1]
    return resolved, _FALLBACK_INPUT_USD_PER_MTOK, _FALLBACK_OUTPUT_USD_PER_MTOK


def _role_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    in_price: float,
    out_price: float,
) -> RoleCost:
    """Compute a :class:`RoleCost` with per-token-class pricing and safety factor."""
    raw_cost = (input_tokens / 1_000_000.0) * in_price + (output_tokens / 1_000_000.0) * out_price
    return RoleCost(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=round(raw_cost * _SAFETY_FACTOR, 4),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def estimate(
    *,
    symbols: int,
    lessons: int,
    clusters: int,
    plan_model: str | None = None,
    orchestrator_model: str | None = None,
    researcher_model: str | None = None,
    writer_model: str | None = None,
    reviewer_model: str | None = None,
    pricing_catalog: PricingCatalog | None = None,
) -> CostEstimate:
    """Return a conservative cost estimate for the planned multi-agent tutorial.

    Models the v0.9.0+ per-lesson pipeline: one Planning call (Stage 4) plus
    Orchestrator + Researcher x N + Writer + Reviewer per lesson (Stage 5/6).
    Token ceilings are derived from the published agent-card budgets;
    ``_SAFETY_FACTOR`` (1.3) is applied per-role before summation.

    Args:
        symbols: Number of code symbols in the repository (drives planning token
            volume).
        lessons: Number of lessons in the plan manifest (drives per-lesson call
            volume).
        clusters: Number of feature clusters (stored for display only).
        plan_model: Stage-4 planning model id (defaults to ``"gpt-5.4"``).
        orchestrator_model: Per-lesson orchestrator model (defaults to
            ``"gpt-5.4"``).
        researcher_model: Per-lesson researcher model (defaults to
            ``"gpt-5.4-mini"``).
        writer_model: Per-lesson writer model (defaults to ``"gpt-5.4"``).
        reviewer_model: Per-lesson reviewer model (defaults to
            ``"gpt-5.4-mini"``).
        pricing_catalog: Optional live catalog (LiteLLM chained with static
            fallback). When provided, its rates override ``MODEL_PRICES``.

    Returns:
        :class:`CostEstimate` with per-role token/cost breakdowns plus an
        expected runtime window in minutes.
    """
    # Resolve per-role prices.
    plan_m, plan_in, plan_out = _resolve_role_prices(
        plan_model, _DEFAULT_PLAN_MODEL, pricing_catalog
    )
    orch_m, orch_in, orch_out = _resolve_role_prices(
        orchestrator_model, _DEFAULT_ORCHESTRATOR_MODEL, pricing_catalog
    )
    res_m, res_in, res_out = _resolve_role_prices(
        researcher_model, _DEFAULT_RESEARCHER_MODEL, pricing_catalog
    )
    wri_m, wri_in, wri_out = _resolve_role_prices(
        writer_model, _DEFAULT_WRITER_MODEL, pricing_catalog
    )
    rev_m, rev_in, rev_out = _resolve_role_prices(
        reviewer_model, _DEFAULT_REVIEWER_MODEL, pricing_catalog
    )

    # Planning — single call; token volume scales with symbol count.
    plan_input = _PLANNING_BASE_INPUT_TOKENS + symbols * _PLANNING_PER_SYMBOL_INPUT_TOKENS
    plan_output = _PLANNING_OUTPUT_TOKENS
    planning = _role_cost(plan_m, plan_input, plan_output, plan_in, plan_out)

    # Orchestrator — one call per lesson.
    orch_input = lessons * _ORCH_INPUT_PER_LESSON
    orch_output = lessons * _ORCH_OUTPUT_PER_LESSON
    orchestrator = _role_cost(orch_m, orch_input, orch_output, orch_in, orch_out)

    # Researcher — _RESEARCH_CALLS_PER_LESSON calls per lesson.
    res_calls = math.ceil(lessons * _RESEARCH_CALLS_PER_LESSON)
    res_input = res_calls * _RESEARCH_INPUT_PER_CALL
    res_output = res_calls * _RESEARCH_OUTPUT_PER_CALL
    researcher = _role_cost(res_m, res_input, res_output, res_in, res_out)

    # Writer — _WRITER_CALLS_PER_LESSON calls per lesson (includes retry rate).
    wri_calls = math.ceil(lessons * _WRITER_CALLS_PER_LESSON)
    wri_input = wri_calls * _WRITER_INPUT_PER_CALL
    wri_output = wri_calls * _WRITER_OUTPUT_PER_CALL
    writer = _role_cost(wri_m, wri_input, wri_output, wri_in, wri_out)

    # Reviewer — _REVIEWER_CALLS_PER_LESSON calls per lesson.
    rev_calls = math.ceil(lessons * _REVIEWER_CALLS_PER_LESSON)
    rev_input = rev_calls * _REVIEWER_INPUT_PER_CALL
    rev_output = rev_calls * _REVIEWER_OUTPUT_PER_CALL
    reviewer = _role_cost(rev_m, rev_input, rev_output, rev_in, rev_out)

    total_tokens = (
        (plan_input + plan_output)
        + (orch_input + orch_output)
        + (res_input + res_output)
        + (wri_input + wri_output)
        + (rev_input + rev_output)
    )
    total_cost = round(
        planning.cost_usd
        + orchestrator.cost_usd
        + researcher.cost_usd
        + writer.cost_usd
        + reviewer.cost_usd,
        2,
    )

    runtime_min_sec = lessons * _RUNTIME_MIN_PER_LESSON_SEC
    runtime_max_sec = lessons * _RUNTIME_MAX_PER_LESSON_SEC

    return CostEstimate(
        symbols=symbols,
        lessons=lessons,
        clusters=clusters,
        planning=planning,
        orchestrator=orchestrator,
        researcher=researcher,
        writer=writer,
        reviewer=reviewer,
        total_tokens=total_tokens,
        total_cost_usd=total_cost,
        runtime_min_minutes=max(1, runtime_min_sec // 60),
        runtime_max_minutes=max(2, runtime_max_sec // 60),
    )
