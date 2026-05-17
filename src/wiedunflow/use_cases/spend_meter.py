# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import Literal

import structlog

from wiedunflow.interfaces.pricing_catalog import PricingCatalog

logger = structlog.get_logger(__name__)

# Conservative fallbacks (USD per 1M tokens) used when no pricing catalog is
# wired or it returns ``None`` for a model. Output rate is 5x input -- matches
# the typical spread at every supported provider.
_FALLBACK_INPUT_PRICE_PER_MTOK = 5.0
_FALLBACK_OUTPUT_PRICE_PER_MTOK = 25.0

# Provider-specific cache pricing multipliers applied to the regular input
# rate. Sourced from each vendor's public pricing page; stable across the
# model line so a hardcoded constant here is acceptable. Holding these in
# the meter (not the pricing catalog) keeps ``PricingCatalog`` returning a
# 2-tuple — a separate cache schema would require BREAKING every adapter
# (Static / LiteLLM / Cached / Chained) for a feature only two of three
# advertised providers expose.
_ANTHROPIC_CACHE_WRITE_MULTIPLIER = 1.25  # 5-minute ephemeral write
_ANTHROPIC_CACHE_READ_MULTIPLIER = 0.1
# OpenAI exposes cache reads only (cache write is invisible / free); the
# 0.5x rate covers any model in the gpt-4/gpt-5/o1/o3 family per the official
# pricing reference.
_OPENAI_CACHED_MULTIPLIER = 0.5


Provider = Literal["anthropic", "openai", "auto"]


def _detect_provider(model: str) -> Literal["anthropic", "openai"]:
    """Map a model identifier to a supported provider via name prefix.

    Anthropic models start with ``claude-``; OpenAI uses ``gpt-`` (4.x / 5.x),
    ``o1``/``o3``/``o4`` (reasoning family), and ``ft:`` for fine-tunes. Any
    other prefix (OSS endpoint model names, test fixtures, custom deployments)
    falls back to the Anthropic-style accounting because that branch is
    bit-equivalent to the pre-cache pricing path when ``cache_*`` kwargs stay
    zero. Callers that need OpenAI-style cached-token accounting for an
    out-of-vocabulary model name must pass ``provider="openai"`` explicitly.
    """
    name = model.strip().lower()
    if name.startswith(("gpt-", "o1", "o3", "o4", "ft:")):
        return "openai"
    # Anthropic-style is the safe default: when no cache_* kwargs are provided
    # the formula reduces to the legacy ``input * ip + output * op`` shape, so
    # existing callers (test fixtures with names like "expensive", OSS models
    # behind base_url) keep their previous cost numbers.
    return "anthropic"


class SpendMeter:
    """Tracks cumulative LLM cost per agent run with abort on budget excess.

    Triple-backstop: SpendMeter is the second backstop (pre-flight estimate is
    first, per-lesson hard cap in run_agent is third).

    Args:
        budget_usd: Maximum allowed spend in USD.
        abort_factor: Abort when ``actual_cost > budget_usd * abort_factor``
            (default 1.1 — permits a 10% buffer above budget before hard abort).
        pricing: Optional ``PricingCatalog`` for model-specific
            ``(input, output)`` rates. When ``None`` or the catalog returns
            ``None`` for a model, the conservative fallbacks
            ``_FALLBACK_INPUT_PRICE_PER_MTOK`` /
            ``_FALLBACK_OUTPUT_PRICE_PER_MTOK`` are used.
    """

    def __init__(
        self,
        *,
        budget_usd: float,
        abort_factor: float = 1.1,
        pricing: PricingCatalog | None = None,
    ) -> None:
        if budget_usd <= 0:
            raise ValueError(f"budget_usd must be positive, got {budget_usd}")
        if abort_factor <= 0:
            raise ValueError(f"abort_factor must be positive, got {abort_factor}")
        self._budget_usd = budget_usd
        self._abort_factor = abort_factor
        self._pricing = pricing
        self._total_cost_usd: float = 0.0
        self._calls: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def charge(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        provider: Provider = "auto",
    ) -> None:
        """Record token usage and accumulate the per-token-class cost.

        Output tokens are 3-5x more expensive than input tokens at every
        supported provider; applying a single blended rate would
        systematically under-report generation-heavy workloads. The catalog
        returns ``(input, output)`` tuples so we charge each class at its
        actual rate.

        Cache pricing is provider-specific and applied as a multiplier on top
        of the base input rate (Anthropic write x 1.25, Anthropic read x 0.1,
        OpenAI cached x 0.5). For OpenAI the ``cache_read_input_tokens`` value
        is the SDK's ``prompt_tokens_details.cached_tokens`` — these tokens
        are *already counted* in ``input_tokens`` (per OpenAI's accounting),
        so the meter subtracts them before applying the regular input rate.
        For Anthropic the three input tiers (regular, cache_write, cache_read)
        are disjoint, so each is billed independently.

        Args:
            model: Model ID used for the call (e.g. ``"gpt-5.4"``).
            input_tokens: Number of prompt tokens billed by the provider.
                For Anthropic this is the *non-cache* input. For OpenAI this is
                the SDK's ``prompt_tokens`` and includes any cached prefix.
            output_tokens: Number of completion tokens billed by the provider.
            cache_creation_input_tokens: Anthropic only — tokens written into
                the ephemeral prompt cache during this call.
            cache_read_input_tokens: Tokens served from cache.
            provider: ``"anthropic"`` / ``"openai"`` to skip detection, or
                ``"auto"`` (default) to infer from the model prefix.
        """
        input_price = _FALLBACK_INPUT_PRICE_PER_MTOK
        output_price = _FALLBACK_OUTPUT_PRICE_PER_MTOK
        if self._pricing is not None:
            prices = self._pricing.prices_per_mtok(model)
            if prices is not None:
                input_price, output_price = prices

        resolved_provider = provider if provider != "auto" else _detect_provider(model)

        if resolved_provider == "anthropic":
            # Anthropic tiers are disjoint per the Messages API contract.
            cache_write_cost = (
                cache_creation_input_tokens * input_price * _ANTHROPIC_CACHE_WRITE_MULTIPLIER
            )
            cache_read_cost = (
                cache_read_input_tokens * input_price * _ANTHROPIC_CACHE_READ_MULTIPLIER
            )
            regular_input_cost = input_tokens * input_price
        else:  # openai
            # cached_tokens are already included in input_tokens — subtract
            # them so the regular tier is not double-counted.
            non_cached = max(0, input_tokens - cache_read_input_tokens)
            cache_write_cost = 0.0  # OpenAI's cache write is free / invisible.
            cache_read_cost = cache_read_input_tokens * input_price * _OPENAI_CACHED_MULTIPLIER
            regular_input_cost = non_cached * input_price

        cost = (
            regular_input_cost + cache_write_cost + cache_read_cost + output_tokens * output_price
        ) / 1_000_000.0
        self._total_cost_usd += cost
        self._calls += 1
        logger.debug(
            "spend_meter_charge",
            model=model,
            provider=resolved_provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
            cost_usd=round(cost, 6),
            total_usd=round(self._total_cost_usd, 6),
        )

    def would_exceed(self) -> bool:
        """Return ``True`` when ``actual_cost > budget_usd * abort_factor`` (10% buffer above budget)."""
        return self._total_cost_usd > self._budget_usd * self._abort_factor

    def assert_within_budget(self) -> None:
        """Raise ``RuntimeError`` when :meth:`would_exceed` is ``True``.

        Raises:
            RuntimeError: Budget exceeded — caller should abort the run.
        """
        if self.would_exceed():
            raise RuntimeError(
                f"SpendMeter: budget exceeded — "
                f"actual ${self._total_cost_usd:.4f} > "
                f"budget ${self._budget_usd:.4f} x abort_factor {self._abort_factor}"
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def total_cost_usd(self) -> float:
        """Cumulative cost in USD across all :meth:`charge` calls."""
        return self._total_cost_usd

    @property
    def total_cost_cents(self) -> int:
        """Cumulative cost in whole cents — convenient for SQLite storage.

        Uses banker's rounding so sub-cent fractions don't silently truncate
        to zero (``$0.0095`` → ``1``, not ``0``).
        """
        return round(self._total_cost_usd * 100)

    @property
    def budget_usd(self) -> float:
        """The configured budget in USD."""
        return self._budget_usd

    @property
    def abort_factor(self) -> float:
        """The configured abort factor (abort when cost exceeds budget x factor; default 1.1 = 10% buffer)."""
        return self._abort_factor

    @property
    def calls(self) -> int:
        """Number of :meth:`charge` calls recorded so far."""
        return self._calls
