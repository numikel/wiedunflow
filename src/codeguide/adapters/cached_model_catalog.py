# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``CachedModelCatalog`` — 24h disk-cached decorator over any ``ModelCatalog``.

ADR-0013 decision 11. The model picker is rendered every time the user
opens the Generate sub-wizard; hitting the provider API on every render
adds 200-1500ms latency and consumes API quota. This decorator caches the
result for 24 hours in ``~/.cache/codeguide/models-<provider>.json``.

Cache invalidation:
- TTL — 24 hours from file mtime.
- Manual — ``rm ~/.cache/codeguide/models-*.json``.
- "Refresh now" menu option — Step 5 wires this to ``CachedModelCatalog.refresh()``.

The cache is intentionally naive (single JSON file per provider, no schema
versioning, no atomic write) because the worst-case failure mode is "fetch
fresh from API" which is identical to the cold-start path.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import platformdirs
import structlog

from codeguide.interfaces.model_catalog import ModelCatalog

logger = structlog.get_logger(__name__)

DEFAULT_TTL_SECONDS: int = 24 * 60 * 60  # 24 hours


def _cache_dir() -> Path:
    """Return the platform-appropriate cache directory for CodeGuide model lists."""
    return Path(platformdirs.user_cache_dir("codeguide"))


class CachedModelCatalog:
    """Decorator: serves cached model list when fresh, refetches when stale."""

    def __init__(
        self,
        upstream: ModelCatalog,
        *,
        provider_name: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        cache_dir: Path | None = None,
    ) -> None:
        """Wrap an upstream ``ModelCatalog`` with disk caching.

        Args:
            upstream: The concrete catalog to wrap (e.g. ``AnthropicModelCatalog``).
            provider_name: Short stable identifier used as the cache filename
                stem (e.g. ``"anthropic"``, ``"openai"``).
            ttl_seconds: Cache freshness window. Default 24h.
            cache_dir: Optional override for the cache directory (tests).
        """
        self._upstream = upstream
        self._provider_name = provider_name
        self._ttl_seconds = ttl_seconds
        self._cache_dir = cache_dir or _cache_dir()

    @property
    def cache_path(self) -> Path:
        return self._cache_dir / f"models-{self._provider_name}.json"

    def _is_fresh(self, path: Path) -> bool:
        if not path.is_file():
            return False
        age_s = time.time() - path.stat().st_mtime
        return age_s < self._ttl_seconds

    def _read_cache(self, path: Path) -> list[str] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "model_cache_read_failed",
                provider=self._provider_name,
                error=type(exc).__name__,
            )
            return None
        if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
            return None
        return list(data)

    def _write_cache(self, path: Path, models: list[str]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(models), encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "model_cache_write_failed",
                provider=self._provider_name,
                error=type(exc).__name__,
            )

    def list_models(self) -> list[str]:
        """Return cached model list when fresh, otherwise refetch and cache."""
        path = self.cache_path
        if self._is_fresh(path):
            cached = self._read_cache(path)
            if cached:
                return cached

        fresh = self._upstream.list_models()
        self._write_cache(path, fresh)
        return fresh

    def refresh(self) -> list[str]:
        """Force a fresh fetch ignoring the cache (wired to "Refresh now" menu)."""
        fresh = self._upstream.list_models()
        self._write_cache(self.cache_path, fresh)
        return fresh
