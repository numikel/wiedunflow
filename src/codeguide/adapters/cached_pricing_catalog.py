# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``CachedPricingCatalog`` + ``ChainedPricingCatalog`` decorators.

Mirror ``CachedModelCatalog`` for the pricing surface (24h disk TTL at
``~/.cache/codeguide/pricing-<provider>.json``) plus a chain helper that
falls back to a secondary catalog when the primary returns ``None``.

Typical wiring used by the menu / cost gate::

    primary = CachedPricingCatalog(LiteLLMPricingCatalog(), provider_name="litellm")
    chain = ChainedPricingCatalog([primary, StaticPricingCatalog()])
"""

from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path

import platformdirs
import structlog

from codeguide.interfaces.pricing_catalog import PricingCatalog

logger = structlog.get_logger(__name__)

DEFAULT_TTL_SECONDS: int = 24 * 60 * 60  # 24 hours


def _cache_dir() -> Path:
    """Return the platform-appropriate cache directory for CodeGuide pricing files."""
    return Path(platformdirs.user_cache_dir("codeguide"))


class CachedPricingCatalog:
    """Decorator: serves a cached price map when fresh, refetches when stale.

    The wrapped catalog must expose ``export_dump() -> dict[str, float]`` and
    ``hydrate(prices)`` (LiteLLM adapter does). Other adapters that don't
    support bulk dump can still be wrapped — fall back to per-id pass-through.
    """

    def __init__(
        self,
        upstream: PricingCatalog,
        *,
        provider_name: str = "litellm",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        cache_dir: Path | None = None,
    ) -> None:
        self._upstream = upstream
        self._provider_name = provider_name
        self._ttl_seconds = ttl_seconds
        self._cache_dir = cache_dir or _cache_dir()
        self._loaded = False

    @property
    def cache_path(self) -> Path:
        return self._cache_dir / f"pricing-{self._provider_name}.json"

    def _is_fresh(self, path: Path) -> bool:
        if not path.is_file():
            return False
        age_s = time.time() - path.stat().st_mtime
        return age_s < self._ttl_seconds

    def _read_cache(self, path: Path) -> dict[str, float] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "pricing_cache_read_failed",
                provider=self._provider_name,
                error=type(exc).__name__,
            )
            return None
        if not isinstance(data, dict):
            return None
        out: dict[str, float] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, int | float):
                out[k] = float(v)
        return out

    def _write_cache(self, path: Path, prices: dict[str, float]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(prices), encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "pricing_cache_write_failed",
                provider=self._provider_name,
                error=type(exc).__name__,
            )

    def _load_into_upstream(self) -> None:
        """Bring the upstream's internal cache up to date (from disk or refetch)."""
        if self._loaded:
            return
        path = self.cache_path
        if self._is_fresh(path):
            cached = self._read_cache(path)
            if cached:
                hydrate = getattr(self._upstream, "hydrate", None)
                if callable(hydrate):
                    hydrate(cached)
                self._loaded = True
                return

        export = getattr(self._upstream, "export_dump", None)
        if callable(export):
            fresh = dict(export())
            self._write_cache(path, fresh)
        self._loaded = True

    def blended_price_per_mtok(self, model_id: str) -> float | None:
        self._load_into_upstream()
        return self._upstream.blended_price_per_mtok(model_id)

    def refresh(self) -> None:
        """Force the upstream to re-fetch and rewrite the cache."""
        # Bust the in-memory + on-disk caches.
        with contextlib.suppress(OSError):
            self.cache_path.unlink(missing_ok=True)
        self._loaded = False
        # Force re-hydrate from a fresh upstream fetch (drop any in-memory cache).
        if hasattr(self._upstream, "hydrate"):
            self._upstream.hydrate({})
        self._load_into_upstream()


class ChainedPricingCatalog:
    """Query catalogs in order; first non-``None`` answer wins.

    Typical chain: ``[CachedPricingCatalog(LiteLLM), StaticPricingCatalog()]``
    so live prices win, hardcoded fallback fills the gaps.
    """

    def __init__(self, catalogs: list[PricingCatalog]) -> None:
        self._catalogs = list(catalogs)

    def blended_price_per_mtok(self, model_id: str) -> float | None:
        for cat in self._catalogs:
            price = cat.blended_price_per_mtok(model_id)
            if price is not None:
                return price
        return None
