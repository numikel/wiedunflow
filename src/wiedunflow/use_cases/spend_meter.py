# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import structlog

from wiedunflow.interfaces.pricing_catalog import PricingCatalog

logger = structlog.get_logger(__name__)

# Conservative fallbacks (USD per 1M tokens) used when no pricing catalog is
# wired or it returns ``None`` for a model. Output rate is 5x input -- matches
# the typical spread at every supported provider.
_FALLBACK_INPUT_PRICE_PER_MTOK = 5.0
_FALLBACK_OUTPUT_PRICE_PER_MTOK = 25.0


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

    def charge(self, *, model: str, input_tokens: int, output_tokens: int) -> None:
        """Record token usage and accumulate the per-token-class cost.

        Output tokens are 3-5x more expensive than input tokens at every
        supported provider; applying a single blended rate would
        systematically under-report generation-heavy workloads. The catalog
        returns ``(input, output)`` tuples so we charge each class at its
        actual rate.

        Args:
            model: Model ID used for the call (e.g. ``"gpt-5.4"``).
            input_tokens: Number of prompt tokens billed by the provider.
            output_tokens: Number of completion tokens billed by the provider.
        """
        input_price = _FALLBACK_INPUT_PRICE_PER_MTOK
        output_price = _FALLBACK_OUTPUT_PRICE_PER_MTOK
        if self._pricing is not None:
            prices = self._pricing.prices_per_mtok(model)
            if prices is not None:
                input_price, output_price = prices

        cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000.0
        self._total_cost_usd += cost
        self._calls += 1
        logger.debug(
            "spend_meter_charge",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
