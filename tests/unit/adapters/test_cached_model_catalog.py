# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for ``CachedModelCatalog`` (ADR-0013 D#11, Step 4b).

Verifies the 24h TTL disk cache contract:
- Cold cache → fetches upstream and writes file.
- Fresh cache → reads file, does NOT call upstream.
- Stale cache (mtime older than TTL) → refetches.
- Corrupted JSON → refetches.
- ``refresh()`` always bypasses the cache.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest


class _StubCatalog:
    """Counts list_models() calls so tests can assert cache hits/misses."""

    def __init__(self, responses: list[list[str]]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def list_models(self) -> list[str]:
        self.call_count += 1
        if not self._responses:
            return ["upstream-default"]
        return self._responses.pop(0)


def _make_cache(upstream: _StubCatalog, tmp_path: Path, ttl_seconds: int = 86_400):
    from codeguide.adapters.cached_model_catalog import CachedModelCatalog

    return CachedModelCatalog(
        upstream,
        provider_name="test",
        ttl_seconds=ttl_seconds,
        cache_dir=tmp_path,
    )


def test_cold_cache_fetches_and_writes(tmp_path: Path) -> None:
    upstream = _StubCatalog([["a", "b", "c"]])
    cache = _make_cache(upstream, tmp_path)

    result = cache.list_models()

    assert result == ["a", "b", "c"]
    assert upstream.call_count == 1
    assert cache.cache_path.is_file()
    assert json.loads(cache.cache_path.read_text(encoding="utf-8")) == ["a", "b", "c"]


def test_fresh_cache_serves_without_upstream_call(tmp_path: Path) -> None:
    upstream = _StubCatalog([["fresh"], ["should-not-be-called"]])
    cache = _make_cache(upstream, tmp_path)

    cache.list_models()  # cold → 1 upstream call
    result = cache.list_models()  # warm → 0 upstream calls

    assert result == ["fresh"]
    assert upstream.call_count == 1


def test_stale_cache_refetches(tmp_path: Path) -> None:
    upstream = _StubCatalog([["old"], ["new"]])
    cache = _make_cache(upstream, tmp_path, ttl_seconds=1)

    cache.list_models()  # writes "old"

    # Backdate the cache file's mtime by 2 hours so it appears stale.
    past = time.time() - 7200
    os.utime(cache.cache_path, (past, past))

    result = cache.list_models()

    assert result == ["new"]
    assert upstream.call_count == 2


def test_corrupted_cache_refetches(tmp_path: Path) -> None:
    upstream = _StubCatalog([["recovered"]])
    cache = _make_cache(upstream, tmp_path)

    cache.cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache.cache_path.write_text("not valid json {", encoding="utf-8")

    result = cache.list_models()

    assert result == ["recovered"]
    assert upstream.call_count == 1


def test_cache_with_wrong_shape_refetches(tmp_path: Path) -> None:
    """A JSON file that parses but isn't ``list[str]`` triggers a refetch."""
    upstream = _StubCatalog([["fixed"]])
    cache = _make_cache(upstream, tmp_path)

    cache.cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache.cache_path.write_text(json.dumps({"unexpected": "object"}), encoding="utf-8")

    result = cache.list_models()

    assert result == ["fixed"]
    assert upstream.call_count == 1


def test_refresh_bypasses_fresh_cache(tmp_path: Path) -> None:
    upstream = _StubCatalog([["v1"], ["v2"]])
    cache = _make_cache(upstream, tmp_path)

    cache.list_models()  # cold → writes v1
    refreshed = cache.refresh()  # should refetch even though cache is fresh

    assert refreshed == ["v2"]
    assert upstream.call_count == 2

    # Confirm the cache file now holds v2 (so a subsequent list_models reads it).
    assert json.loads(cache.cache_path.read_text(encoding="utf-8")) == ["v2"]


def test_cache_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested"
    upstream = _StubCatalog([["x"]])
    from codeguide.adapters.cached_model_catalog import CachedModelCatalog

    cache = CachedModelCatalog(upstream, provider_name="test", cache_dir=nested)

    cache.list_models()

    assert (nested / "models-test.json").is_file()


def test_cache_path_uses_provider_name(tmp_path: Path) -> None:
    upstream = _StubCatalog([["x"]])
    from codeguide.adapters.cached_model_catalog import CachedModelCatalog

    cache = CachedModelCatalog(upstream, provider_name="myprovider", cache_dir=tmp_path)

    assert cache.cache_path == tmp_path / "models-myprovider.json"


def test_protocol_satisfied() -> None:
    """``CachedModelCatalog`` must structurally satisfy the ``ModelCatalog`` Protocol."""
    from codeguide.adapters.cached_model_catalog import CachedModelCatalog
    from codeguide.interfaces.model_catalog import ModelCatalog

    upstream = _StubCatalog([["x"]])
    cache: ModelCatalog = CachedModelCatalog(upstream, provider_name="t")
    assert isinstance(cache, ModelCatalog)


def test_concrete_adapters_satisfy_protocol() -> None:
    from codeguide.adapters.anthropic_model_catalog import AnthropicModelCatalog
    from codeguide.adapters.openai_model_catalog import OpenAIModelCatalog
    from codeguide.interfaces.model_catalog import ModelCatalog

    a: ModelCatalog = AnthropicModelCatalog(api_key="x")
    o: ModelCatalog = OpenAIModelCatalog(api_key="x")
    assert isinstance(a, ModelCatalog)
    assert isinstance(o, ModelCatalog)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive: kill env vars so concrete adapters cannot accidentally fetch."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
