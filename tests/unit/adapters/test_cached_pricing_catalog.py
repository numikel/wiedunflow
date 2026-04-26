# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for ``CachedPricingCatalog`` + ``ChainedPricingCatalog`` (ADR-0013 follow-up)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from codeguide.adapters.cached_pricing_catalog import (
    CachedPricingCatalog,
    ChainedPricingCatalog,
)
from codeguide.adapters.static_pricing_catalog import StaticPricingCatalog
from codeguide.interfaces.pricing_catalog import PricingCatalog


class _StubUpstream:
    """Counts export_dump / hydrate calls so cache hits/misses are observable."""

    def __init__(self, prices: dict[str, float]) -> None:
        self._prices = dict(prices)
        self.dump_calls = 0
        self.hydrate_calls = 0

    def export_dump(self) -> dict[str, float]:
        self.dump_calls += 1
        return dict(self._prices)

    def hydrate(self, prices: dict[str, float]) -> None:
        self.hydrate_calls += 1
        self._prices = dict(prices)

    def blended_price_per_mtok(self, model_id: str) -> float | None:
        return self._prices.get(model_id)


def _make_cache(
    upstream: _StubUpstream, tmp_path: Path, ttl_seconds: int = 86_400
) -> CachedPricingCatalog:
    return CachedPricingCatalog(
        upstream,
        provider_name="test",
        ttl_seconds=ttl_seconds,
        cache_dir=tmp_path,
    )


# ---------------------------------------------------------------------------
# CachedPricingCatalog
# ---------------------------------------------------------------------------


def test_cold_cache_dumps_upstream_and_writes_file(tmp_path: Path) -> None:
    upstream = _StubUpstream({"gpt-4.1": 4.4})
    cache = _make_cache(upstream, tmp_path)

    assert cache.blended_price_per_mtok("gpt-4.1") == 4.4
    assert upstream.dump_calls == 1
    assert cache.cache_path.is_file()
    assert json.loads(cache.cache_path.read_text(encoding="utf-8")) == {"gpt-4.1": 4.4}


def test_fresh_cache_hydrates_upstream_without_dump(tmp_path: Path) -> None:
    upstream = _StubUpstream({"gpt-4.1": 4.4})
    cache_file = tmp_path / "pricing-test.json"
    cache_file.write_text(json.dumps({"gpt-4.1": 9.9}), encoding="utf-8")

    cache = _make_cache(upstream, tmp_path)

    # Hits cache → upstream is hydrated with the on-disk values, NOT re-fetched.
    assert cache.blended_price_per_mtok("gpt-4.1") == 9.9
    assert upstream.dump_calls == 0
    assert upstream.hydrate_calls == 1


def test_stale_cache_refetches(tmp_path: Path) -> None:
    upstream = _StubUpstream({"gpt-4.1": 4.4})
    cache_file = tmp_path / "pricing-test.json"
    cache_file.write_text(json.dumps({"gpt-4.1": 1.0}), encoding="utf-8")

    # Backdate the cache 2h beyond a 1s TTL.
    past = time.time() - 7200
    os.utime(cache_file, (past, past))

    cache = _make_cache(upstream, tmp_path, ttl_seconds=1)

    assert cache.blended_price_per_mtok("gpt-4.1") == 4.4
    assert upstream.dump_calls == 1


def test_corrupt_cache_refetches(tmp_path: Path) -> None:
    upstream = _StubUpstream({"gpt-4.1": 4.4})
    cache_file = tmp_path / "pricing-test.json"
    cache_file.write_text("not valid json {", encoding="utf-8")

    cache = _make_cache(upstream, tmp_path)

    assert cache.blended_price_per_mtok("gpt-4.1") == 4.4
    assert upstream.dump_calls == 1


def test_refresh_busts_disk_and_in_memory(tmp_path: Path) -> None:
    upstream = _StubUpstream({"gpt-4.1": 4.4})
    cache = _make_cache(upstream, tmp_path)

    cache.blended_price_per_mtok("gpt-4.1")  # warm up
    assert upstream.dump_calls == 1

    cache.refresh()

    # refresh() should drop the disk file + force a fresh dump on next query.
    cache.blended_price_per_mtok("gpt-4.1")
    assert upstream.dump_calls == 2


def test_satisfies_pricing_catalog_protocol(tmp_path: Path) -> None:
    upstream = _StubUpstream({})
    cache: PricingCatalog = _make_cache(upstream, tmp_path)
    assert isinstance(cache, PricingCatalog)


# ---------------------------------------------------------------------------
# ChainedPricingCatalog
# ---------------------------------------------------------------------------


def test_chain_returns_first_non_none() -> None:
    primary = StaticPricingCatalog(prices={"gpt-4.1": 4.4})
    secondary = StaticPricingCatalog(prices={"gpt-4.1": 99.0, "claude-opus-4-7": 33.0})
    chain = ChainedPricingCatalog([primary, secondary])

    assert chain.blended_price_per_mtok("gpt-4.1") == 4.4  # primary wins
    assert chain.blended_price_per_mtok("claude-opus-4-7") == 33.0  # falls through


def test_chain_returns_none_when_all_unknown() -> None:
    chain = ChainedPricingCatalog(
        [StaticPricingCatalog(prices={}), StaticPricingCatalog(prices={})]
    )
    assert chain.blended_price_per_mtok("nope") is None


def test_chain_satisfies_pricing_catalog_protocol() -> None:
    chain: PricingCatalog = ChainedPricingCatalog([StaticPricingCatalog()])
    assert isinstance(chain, PricingCatalog)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive — keep these tests offline even if a regression slips."""
    monkeypatch.setattr(
        "codeguide.adapters.litellm_pricing_catalog.httpx.get",
        lambda *_a, **_k: pytest.fail("unexpected httpx.get in cached pricing test"),
    )
