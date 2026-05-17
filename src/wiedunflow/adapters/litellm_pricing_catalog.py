# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``LiteLLMPricingCatalog`` — fetch model pricing from LiteLLM's GitHub JSON.

The community-maintained ``model_prices_and_context_window.json`` lists
~3500 models with ``input_cost_per_token`` / ``output_cost_per_token``
fields. We expose the two figures separately (per-million-tokens) so live
spend tracking can apply each rate to the correct token class -- output
tokens are 3-5x more expensive at every supported provider.

Provider prefix handling:
LiteLLM frequently ships dual entries — a bare ``gpt-4.1`` and a fully
qualified ``openai/gpt-4.1``. We strip ``{provider}/`` prefixes when
matching, so the user's ``llm_model_plan = "gpt-4.1"`` finds either form.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)

# Cool-down between repeated fetch attempts within a single process after a
# previous failure. Without this, every model-price lookup re-hammers the
# upstream when the network is down. ChainedPricingCatalog already falls back
# to StaticPricingCatalog for the empty case, so the cool-down's only job is
# "should we try again at all". 60 s strikes the balance between fast recovery
# from a transient network blip and not pegging upstream during a long outage.
_RETRY_AFTER_S = 60.0


def _provider_strip(model_id: str) -> str:
    """Strip a leading ``provider/`` prefix (``openai/gpt-4.1`` → ``gpt-4.1``)."""
    if "/" not in model_id:
        return model_id
    return model_id.rsplit("/", 1)[-1]


def _entry_to_prices_per_mtok(entry: dict[str, Any]) -> tuple[float, float] | None:
    """Convert one LiteLLM JSON entry to ``(input, output)`` USD/MTok, or ``None``."""
    in_per_tok = entry.get("input_cost_per_token")
    out_per_tok = entry.get("output_cost_per_token")
    if not isinstance(in_per_tok, int | float) or not isinstance(out_per_tok, int | float):
        return None
    return float(in_per_tok) * 1_000_000.0, float(out_per_tok) * 1_000_000.0


# ---------------------------------------------------------------------------
# Integrity validation
# ---------------------------------------------------------------------------

# Sentinel models with prices we know to ground truth (mirroring
# StaticPricingCatalog). A compromised upstream that underprices these to
# bypass the cost cap is the primary threat we mitigate here. Constants
# live in code (NOT config) so a hostile config cannot weaken the guard.
_MIN_VALID_ENTRIES = 50
_GENERAL_PRICE_RANGE: tuple[float, float] = (0.0, 1000.0)  # USD per million tokens
_SENTINELS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    # model_id: ((input_min, input_max), (output_min, output_max)) USD/MTok
    "gpt-4o": ((0.5, 10.0), (2.0, 50.0)),
    "claude-opus-4-7": ((5.0, 50.0), (20.0, 200.0)),
}


def _validate_pricing_map(prices: dict[str, tuple[float, float]]) -> bool:
    """Return True if the parsed map looks plausible.

    Three layers of defense against a tampered upstream:
    - At least ``_MIN_VALID_ENTRIES`` entries (catches a near-empty payload).
    - Every entry's input/output price falls in ``_GENERAL_PRICE_RANGE``
      (catches absurd negative or huge values).
    - Sentinel models sit inside narrow per-model expected ranges (catches an
      underpricing attack that would bypass the cost cap).
    """
    if len(prices) < _MIN_VALID_ENTRIES:
        return False
    lo, hi = _GENERAL_PRICE_RANGE
    for inp, out in prices.values():
        if not (lo <= inp <= hi and lo <= out <= hi):
            return False
    for sentinel_id, ((in_lo, in_hi), (out_lo, out_hi)) in _SENTINELS.items():
        prices_for = prices.get(sentinel_id) or prices.get(_provider_strip(sentinel_id))
        if prices_for is None:
            continue  # upstream may have dropped a sentinel; not fatal alone
        in_actual, out_actual = prices_for
        if not (in_lo <= in_actual <= in_hi):
            return False
        if not (out_lo <= out_actual <= out_hi):
            return False
    return True


def _parse_pricing_payload(payload: dict[str, Any]) -> dict[str, tuple[float, float]]:
    """Build ``{model_id: (input_per_mtok, output_per_mtok)}`` from parsed LiteLLM JSON.

    Both bare (``gpt-4.1``) and prefixed (``openai/gpt-4.1``) keys map to
    the same prices; bare wins on collision so the most common form
    matches first.
    """
    by_model: dict[str, tuple[float, float]] = {}
    for raw_key, raw_entry in payload.items():
        if not isinstance(raw_entry, dict):
            continue
        if raw_key == "sample_spec":  # LiteLLM ships an example schema entry
            continue
        # Skip non-chat / specialty modes the cost gate can't use anyway.
        mode = raw_entry.get("mode")
        if mode and mode not in {"chat", "responses", "completion"}:
            continue
        prices = _entry_to_prices_per_mtok(raw_entry)
        if prices is None:
            continue
        bare = _provider_strip(str(raw_key))
        by_model.setdefault(bare, prices)
        # Also index the original (prefixed) form for explicit hits.
        by_model[str(raw_key)] = prices
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
        self._cache: dict[str, tuple[float, float]] | None = None
        # Monotonic timestamp of the last failed fetch attempt, used to gate
        # retry attempts until ``_RETRY_AFTER_S`` has elapsed. ``None`` means
        # "no prior failure" (cold start or successful load).
        self._last_failure_monotonic: float | None = None

    def _ensure_loaded(self) -> dict[str, tuple[float, float]]:
        """Lazily fetch + parse the JSON. Empty on any failure (never raises)."""
        if self._cache is not None:
            return self._cache

        # Cool-down gate — if a recent attempt failed, skip the fetch and let
        # the caller fall back to StaticPricingCatalog. The ``_cache is None``
        # sentinel (set on failure paths below) ensures the next call after
        # cool-down expiry retries from scratch.
        if self._last_failure_monotonic is not None:
            elapsed = time.monotonic() - self._last_failure_monotonic
            if elapsed < _RETRY_AFTER_S:
                return {}

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
            self._last_failure_monotonic = time.monotonic()
            return {}

        if not isinstance(payload, dict):
            logger.warning("litellm_pricing_unexpected_shape", got=type(payload).__name__)
            self._last_failure_monotonic = time.monotonic()
            return {}

        parsed = _parse_pricing_payload(payload)
        if not _validate_pricing_map(parsed):
            logger.warning(
                "litellm_pricing_validation_failed",
                entry_count=len(parsed),
                msg=(
                    "Parsed pricing payload failed integrity checks "
                    "(too few entries, out-of-range prices, or sentinel mismatch). "
                    "Falling back to static pricing catalog."
                ),
            )
            self._last_failure_monotonic = time.monotonic()
            return {}
        self._cache = parsed
        self._last_failure_monotonic = None
        return self._cache

    def prices_per_mtok(self, model_id: str) -> tuple[float, float] | None:
        """Return ``(input, output)`` USD/MTok for ``model_id``, or ``None`` if unknown.

        Tries the literal id first, then the bare (provider-stripped) form
        so ``openai/gpt-4.1`` matches the same entry as ``gpt-4.1``.
        """
        prices = self._ensure_loaded()
        direct = prices.get(model_id)
        if direct is not None:
            return direct
        return prices.get(_provider_strip(model_id))

    def export_dump(self) -> dict[str, tuple[float, float]]:
        """Return the full parsed mapping (used by ``CachedPricingCatalog``)."""
        return dict(self._ensure_loaded())

    def hydrate(self, prices: dict[str, tuple[float, float]]) -> None:
        """Inject a pre-fetched price map (used by ``CachedPricingCatalog``)."""
        self._cache = dict(prices)
