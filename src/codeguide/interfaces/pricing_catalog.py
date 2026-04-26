# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``PricingCatalog`` port — look up the blended USD-per-million-tokens price
for a given model id.

ADR-0013 follow-up (v0.4.x). The cost gate and Estimate-cost menu item need
accurate per-model pricing to be useful for OpenAI / Anthropic / OSS configs.
Provider APIs (Anthropic, OpenAI) do **not** expose pricing in their
``models.list()`` responses, so the canonical source is LiteLLM's community
JSON catalog (``model_prices_and_context_window.json``) cached for 24h.

Adapters:
- ``StaticPricingCatalog`` — always-available hardcoded fallback (built from
  ``cost_estimator.MODEL_PRICES``); used when LiteLLM fetch fails (offline,
  rate limit, 5xx) and as the leaf of every chain.
- ``LiteLLMPricingCatalog`` — HTTPS fetch with 3-second timeout; never
  raises (returns empty mapping on failure).
- ``CachedPricingCatalog`` — 24h disk cache decorator (mirrors
  ``CachedModelCatalog``).
- ``ChainedPricingCatalog`` — falls back to the next catalog when the
  primary returns ``None`` for a model id.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PricingCatalog(Protocol):
    """Port: look up the blended USD price per 1M tokens for ``model_id``.

    Implementations must:
    - Return ``None`` for unknown model ids so the caller can chain fallbacks
      (a hardcoded conservative default beats a silent zero).
    - Never raise — pricing lookup happens on every estimate render and a
      crash here would block the menu picker. Network/parse errors are
      handled internally and surfaced as ``None`` per query.
    - Use a *blended* rate (typically ``0.6 * input + 0.4 * output``) so
      callers never have to know the input/output split for the workload.
    """

    def blended_price_per_mtok(self, model_id: str) -> float | None:
        """Return blended USD/MTok for ``model_id``, or ``None`` if unknown."""
        ...
