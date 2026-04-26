# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``LiteLLMPricingCatalog`` — fetch model pricing from LiteLLM's GitHub JSON.

The community-maintained ``model_prices_and_context_window.json`` lists
~3500 models with ``input_cost_per_token`` / ``output_cost_per_token``
fields. We blend at 60% input + 40% output (typical planning + narration
workload split) and convert from per-token to per-million-tokens.

Provider prefix handling:
LiteLLM frequently ships dual entries — a bare ``gpt-4.1`` and a fully
qualified ``openai/gpt-4.1``. We strip ``{provider}/`` prefixes when
matching, so the user's ``llm_model_plan = "gpt-4.1"`` finds either form.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)

# Blended weight: 60% input + 40% output. Empirical split for the planning
# (high input, low output) and narration (moderate both) stages combined.
_INPUT_WEIGHT = 0.60
_OUTPUT_WEIGHT = 0.40


def _provider_strip(model_id: str) -> str:
    """Strip a leading ``provider/`` prefix (``openai/gpt-4.1`` → ``gpt-4.1``)."""
    if "/" not in model_id:
        return model_id
    return model_id.rsplit("/", 1)[-1]


def _entry_to_blended_price(entry: dict[str, Any]) -> float | None:
    """Convert one LiteLLM JSON entry to blended USD/MTok, or None on bad data."""
    in_per_tok = entry.get("input_cost_per_token")
    out_per_tok = entry.get("output_cost_per_token")
    if not isinstance(in_per_tok, int | float) or not isinstance(out_per_tok, int | float):
        return None
    blended_per_tok = (_INPUT_WEIGHT * float(in_per_tok)) + (_OUTPUT_WEIGHT * float(out_per_tok))
    return blended_per_tok * 1_000_000.0


def _parse_pricing_payload(payload: dict[str, Any]) -> dict[str, float]:
    """Build ``{model_id: blended_usd_per_mtok}`` from a parsed LiteLLM JSON.

    Both bare (``gpt-4.1``) and prefixed (``openai/gpt-4.1``) keys map to
    the same blended price; bare wins on collision so the most common form
    matches first.
    """
    by_model: dict[str, float] = {}
    for raw_key, raw_entry in payload.items():
        if not isinstance(raw_entry, dict):
            continue
        if raw_key == "sample_spec":  # LiteLLM ships an example schema entry
            continue
        # Skip non-chat / specialty modes the cost gate can't use anyway.
        mode = raw_entry.get("mode")
        if mode and mode not in {"chat", "responses", "completion"}:
            continue
        price = _entry_to_blended_price(raw_entry)
        if price is None:
            continue
        bare = _provider_strip(str(raw_key))
        by_model.setdefault(bare, price)
        # Also index the original (prefixed) form for explicit hits.
        by_model[str(raw_key)] = price
    return by_model


class LiteLLMPricingCatalog:
    """``PricingCatalog`` impl that pulls live pricing from LiteLLM's JSON catalog."""

    def __init__(
        self,
        *,
        url: str = LITELLM_PRICING_URL,
        timeout_s: float = 3.0,
    ) -> None:
        self._url = url
        self._timeout_s = timeout_s
        self._cache: dict[str, float] | None = None

    def _ensure_loaded(self) -> dict[str, float]:
        """Lazily fetch + parse the JSON. Empty on any failure (never raises)."""
        if self._cache is not None:
            return self._cache

        try:
            response = httpx.get(self._url, timeout=self._timeout_s)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning(
                "litellm_pricing_fetch_failed",
                error=type(exc).__name__,
                message=str(exc)[:200],
            )
            self._cache = {}
            return self._cache

        if not isinstance(payload, dict):
            logger.warning("litellm_pricing_unexpected_shape", got=type(payload).__name__)
            self._cache = {}
            return self._cache

        self._cache = _parse_pricing_payload(payload)
        return self._cache

    def blended_price_per_mtok(self, model_id: str) -> float | None:
        """Return blended USD/MTok for ``model_id``, or ``None`` if unknown.

        Tries the literal id first, then the bare (provider-stripped) form
        so ``openai/gpt-4.1`` matches the same entry as ``gpt-4.1``.
        """
        prices = self._ensure_loaded()
        direct = prices.get(model_id)
        if direct is not None:
            return direct
        return prices.get(_provider_strip(model_id))

    def export_dump(self) -> dict[str, float]:
        """Return the full parsed mapping (used by ``CachedPricingCatalog``)."""
        return dict(self._ensure_loaded())

    def hydrate(self, prices: dict[str, float]) -> None:
        """Inject a pre-fetched price map (used by ``CachedPricingCatalog``)."""
        self._cache = dict(prices)
