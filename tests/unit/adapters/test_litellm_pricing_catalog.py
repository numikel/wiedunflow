# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for ``LiteLLMPricingCatalog`` (ADR-0013 follow-up — pricing port)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from codeguide.adapters.litellm_pricing_catalog import (
    LiteLLMPricingCatalog,
    _entry_to_blended_price,
    _parse_pricing_payload,
    _provider_strip,
)
from codeguide.interfaces.pricing_catalog import PricingCatalog

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def test_provider_strip_removes_prefix() -> None:
    assert _provider_strip("openai/gpt-4.1") == "gpt-4.1"
    assert _provider_strip("anthropic/claude-opus-4-7") == "claude-opus-4-7"
    assert _provider_strip("gpt-4.1") == "gpt-4.1"  # bare ID untouched


def test_blended_price_60_40_split() -> None:
    """0.6 * input + 0.4 * output, then * 1_000_000."""
    entry = {"input_cost_per_token": 0.000002, "output_cost_per_token": 0.000008}
    # 0.6 * 2 + 0.4 * 8 = 1.2 + 3.2 = 4.4 USD/MTok
    assert _entry_to_blended_price(entry) == pytest.approx(4.4, rel=1e-9)


def test_blended_price_returns_none_when_fields_missing() -> None:
    assert _entry_to_blended_price({"input_cost_per_token": 0.000002}) is None
    assert _entry_to_blended_price({"output_cost_per_token": 0.000008}) is None
    assert (
        _entry_to_blended_price({"input_cost_per_token": "x", "output_cost_per_token": 1}) is None
    )


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def test_parse_pricing_payload_indexes_bare_and_prefixed() -> None:
    payload: dict[str, Any] = {
        "openai/gpt-4.1": {
            "input_cost_per_token": 0.000002,
            "output_cost_per_token": 0.000008,
            "mode": "chat",
        },
        "claude-opus-4-7": {
            "input_cost_per_token": 0.000015,
            "output_cost_per_token": 0.00006,
            "mode": "chat",
        },
    }
    parsed = _parse_pricing_payload(payload)
    assert parsed["openai/gpt-4.1"] == pytest.approx(4.4)
    assert parsed["gpt-4.1"] == pytest.approx(4.4)  # bare form indexed too
    assert parsed["claude-opus-4-7"] == pytest.approx(33.0)


def test_parse_skips_sample_spec_and_non_chat_modes() -> None:
    payload: dict[str, Any] = {
        "sample_spec": {"input_cost_per_token": 1, "output_cost_per_token": 1},
        "tts-1": {
            "input_cost_per_token": 0.000015,
            "output_cost_per_token": 0,
            "mode": "audio_speech",
        },
        "gpt-4.1": {
            "input_cost_per_token": 0.000002,
            "output_cost_per_token": 0.000008,
            "mode": "chat",
        },
    }
    parsed = _parse_pricing_payload(payload)
    assert "sample_spec" not in parsed
    assert "tts-1" not in parsed
    assert "gpt-4.1" in parsed


def test_parse_skips_entries_with_invalid_costs() -> None:
    payload: dict[str, Any] = {
        "broken": {"input_cost_per_token": "free", "output_cost_per_token": None},
        "gpt-4.1": {
            "input_cost_per_token": 0.000002,
            "output_cost_per_token": 0.000008,
        },
    }
    parsed = _parse_pricing_payload(payload)
    assert "broken" not in parsed
    assert "gpt-4.1" in parsed


# ---------------------------------------------------------------------------
# LiteLLMPricingCatalog (HTTP)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    monkeypatch.setattr(
        "codeguide.adapters.litellm_pricing_catalog.httpx.get",
        lambda *_a, **_k: _FakeResponse(payload),
    )


def test_returns_blended_price_after_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(
        monkeypatch,
        {
            "gpt-4.1": {
                "input_cost_per_token": 0.000002,
                "output_cost_per_token": 0.000008,
                "mode": "chat",
            }
        },
    )
    cat = LiteLLMPricingCatalog()
    assert cat.blended_price_per_mtok("gpt-4.1") == pytest.approx(4.4)


def test_provider_prefix_falls_back_to_bare(monkeypatch: pytest.MonkeyPatch) -> None:
    """User ships ``openai/gpt-4.1``; LiteLLM JSON only has ``gpt-4.1`` → still match."""
    _patch_httpx(
        monkeypatch,
        {
            "gpt-4.1": {
                "input_cost_per_token": 0.000002,
                "output_cost_per_token": 0.000008,
                "mode": "chat",
            }
        },
    )
    cat = LiteLLMPricingCatalog()
    assert cat.blended_price_per_mtok("openai/gpt-4.1") == pytest.approx(4.4)


def test_unknown_model_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, {})
    cat = LiteLLMPricingCatalog()
    assert cat.blended_price_per_mtok("nope") is None


def test_http_error_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*_a: Any, **_k: Any) -> None:
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("codeguide.adapters.litellm_pricing_catalog.httpx.get", _raise)
    cat = LiteLLMPricingCatalog()
    assert cat.blended_price_per_mtok("gpt-4.1") is None


def test_unexpected_payload_shape_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(monkeypatch, ["not", "a", "dict"])
    cat = LiteLLMPricingCatalog()
    assert cat.blended_price_per_mtok("gpt-4.1") is None


def test_export_dump_matches_blended_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx(
        monkeypatch,
        {
            "gpt-4.1": {
                "input_cost_per_token": 0.000002,
                "output_cost_per_token": 0.000008,
                "mode": "chat",
            }
        },
    )
    cat = LiteLLMPricingCatalog()
    dump = cat.export_dump()
    assert dump["gpt-4.1"] == pytest.approx(4.4)


def test_hydrate_bypasses_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """``hydrate`` lets a cache decorator inject pre-fetched data without HTTP."""

    def _should_not_be_called(*_a: Any, **_k: Any) -> None:
        pytest.fail("httpx.get was invoked despite hydrate()")

    monkeypatch.setattr(
        "codeguide.adapters.litellm_pricing_catalog.httpx.get", _should_not_be_called
    )
    cat = LiteLLMPricingCatalog()
    cat.hydrate({"my-llama": 0.10})
    assert cat.blended_price_per_mtok("my-llama") == 0.10


def test_satisfies_pricing_catalog_protocol() -> None:
    cat: PricingCatalog = LiteLLMPricingCatalog()
    assert isinstance(cat, PricingCatalog)


# ---------------------------------------------------------------------------
# Fixture-based tests (litellm_pricing_sample.json)
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_payload() -> dict[str, Any]:
    """Load the checked-in representative subset of the LiteLLM pricing JSON."""
    data = json.loads((_FIXTURES_DIR / "litellm_pricing_sample.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data  # type: ignore[return-value]


def test_fixture_sample_skips_non_chat_and_sample_spec(
    sample_payload: dict[str, Any],
) -> None:
    """``_parse_pricing_payload`` applied to the fixture skips ``sample_spec`` and
    non-chat entries (``whisper-1`` uses mode ``audio_transcription``)."""
    parsed = _parse_pricing_payload(sample_payload)
    assert "sample_spec" not in parsed
    assert "whisper-1" not in parsed
    # Chat / responses-mode models must be present.
    assert "claude-opus-4-7" in parsed
    assert "gpt-4.1" in parsed
    assert "o1" in parsed  # mode=responses is allowed


def test_fixture_prefixed_and_bare_gpt41(sample_payload: dict[str, Any]) -> None:
    """The fixture contains both ``gpt-4.1`` and ``openai/gpt-4.1`` — bare wins on
    collision so the two entries share the same blended price."""
    parsed = _parse_pricing_payload(sample_payload)
    assert parsed["gpt-4.1"] == pytest.approx(parsed["openai/gpt-4.1"])


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


def test_build_pricing_chain_wires_litellm_then_static() -> None:
    """``_build_pricing_chain()`` returns a chain of [Cached(LiteLLM), Static]."""
    from codeguide.adapters.cached_pricing_catalog import (
        CachedPricingCatalog,
        ChainedPricingCatalog,
    )
    from codeguide.adapters.static_pricing_catalog import StaticPricingCatalog
    from codeguide.cli.main import _build_pricing_chain

    chain = _build_pricing_chain()

    assert isinstance(chain, ChainedPricingCatalog)
    assert len(chain._catalogs) == 2
    assert isinstance(chain._catalogs[0], CachedPricingCatalog)
    assert isinstance(chain._catalogs[1], StaticPricingCatalog)
