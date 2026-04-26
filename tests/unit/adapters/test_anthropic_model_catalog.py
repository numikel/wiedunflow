# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for ``AnthropicModelCatalog`` (ADR-0013 D#11, Step 4b).

The catalog must:
- Sort SDK results newest-first by ``created_at``.
- Fall back to the hardcoded list when the API key is missing.
- Fall back when the SDK raises any exception (offline, 5xx, rate limit).
- Fall back when the SDK returns an empty page.
- Never raise — the menu picker depends on this guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from wiedunflow.adapters.anthropic_model_catalog import (
    _FALLBACK,
    AnthropicModelCatalog,
)


@dataclass
class _FakeModelInfo:
    id: str
    created_at: str


class _FakePage:
    def __init__(self, data: list[_FakeModelInfo]) -> None:
        self.data = data


class _FakeAnthropicClient:
    def __init__(self, page: _FakePage | Exception) -> None:
        self._page_or_exc = page

        class _Models:
            def __init__(self, parent: _FakeAnthropicClient) -> None:
                self._parent = parent

            def list(self) -> Any:
                if isinstance(self._parent._page_or_exc, Exception):
                    raise self._parent._page_or_exc
                return self._parent._page_or_exc

        self.models = _Models(self)


def _patch_anthropic(monkeypatch: pytest.MonkeyPatch, client: _FakeAnthropicClient) -> None:
    monkeypatch.setattr(
        "wiedunflow.adapters.anthropic_model_catalog.anthropic.Anthropic",
        lambda **_kwargs: client,
    )


def test_returns_models_sorted_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage(
        [
            _FakeModelInfo(id="claude-sonnet-4-6", created_at="2026-02-17T00:00:00Z"),
            _FakeModelInfo(id="claude-opus-4-7", created_at="2026-04-14T00:00:00Z"),
            _FakeModelInfo(id="claude-haiku-4-5", created_at="2025-10-15T00:00:00Z"),
        ]
    )
    _patch_anthropic(monkeypatch, _FakeAnthropicClient(page))

    catalog = AnthropicModelCatalog(api_key="sk-ant-test")
    result = catalog.list_models()

    assert result == ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"]


def test_falls_back_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    catalog = AnthropicModelCatalog(api_key=None)

    assert catalog.list_models() == list(_FALLBACK)


def test_falls_back_when_sdk_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_anthropic(monkeypatch, _FakeAnthropicClient(RuntimeError("rate limit 429")))

    catalog = AnthropicModelCatalog(api_key="sk-ant-test")

    # Must not raise — fallback list is returned.
    assert catalog.list_models() == list(_FALLBACK)


def test_falls_back_on_empty_page(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_anthropic(monkeypatch, _FakeAnthropicClient(_FakePage([])))

    catalog = AnthropicModelCatalog(api_key="sk-ant-test")

    assert catalog.list_models() == list(_FALLBACK)


def test_fallback_list_contains_only_chat_models() -> None:
    """Sanity: hardcoded fallback contains the 3 known good Claude models."""
    assert "claude-opus-4-7" in _FALLBACK
    assert "claude-sonnet-4-6" in _FALLBACK
    assert "claude-haiku-4-5" in _FALLBACK
    # No deprecated / non-chat models in fallback.
    assert all(model.startswith("claude-") for model in _FALLBACK)
