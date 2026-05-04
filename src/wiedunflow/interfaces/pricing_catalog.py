# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``PricingCatalog`` port — look up the input/output USD-per-million-tokens
prices for a given model id.

ADR-0020 (v0.9.5+). Output tokens are 3-5x more expensive than input tokens
at every supported provider, so a single blended rate systematically
under-reports actual spend by ~30-60% on generation-heavy workloads. The
catalog now returns the input/output split as a tuple; callers that need a
classic blended figure (e.g. preflight estimates) compute it themselves.

ADR-0014 (v0.5.x) introduced the catalog infrastructure. This refines its
resolution model — the chain layout (LiteLLM → cache → static fallback) is
unchanged.

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
    """Port: look up (input, output) USD per 1M tokens for ``model_id``.

    Implementations must:
    - Return ``None`` for unknown model ids so the caller can chain fallbacks
      (a hardcoded conservative default beats a silent zero).
    - Never raise — pricing lookup happens on every estimate render and a
      crash here would block the menu picker. Network/parse errors are
      handled internally and surfaced as ``None`` per query.
    - Return a 2-tuple ``(input_per_mtok, output_per_mtok)`` so the cumulative
      meter can apply the correct rate to each token class. Callers that
      need a single blended figure (preflight estimate) compute it via
      ``0.6 * input + 0.4 * output``.
    """

    def prices_per_mtok(self, model_id: str) -> tuple[float, float] | None:
        """Return ``(input_per_mtok, output_per_mtok)`` USD for ``model_id``, or ``None``."""
        ...
