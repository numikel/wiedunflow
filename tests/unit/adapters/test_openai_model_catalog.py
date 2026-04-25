# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for ``OpenAIModelCatalog`` (ADR-0013 D#11 + D#12, Step 4b).

Critical filter contracts verified here:
- ``ft:*`` fine-tuned models must NEVER appear in results (privacy leak risk).
- Non-chat models (audio, realtime, image, tts, whisper, embedding,
  moderation, transcribe, dall-e, sora, codex, deep-research) must NEVER
  appear (would crash the planning/narration pipeline if selected).
- Hardcoded fallback uses ``gpt-4.1`` not ``gpt-4o`` (ADR-0013 D#12,
  see auto-memory ``project_openai_default_model``).
- Sort is newest-first by ``created`` Unix timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from codeguide.adapters.openai_model_catalog import (
    _FALLBACK,
    OpenAIModelCatalog,
    _is_chat_capable,
)


@dataclass
class _FakeModel:
    id: str
    created: int


class _FakePage:
    def __init__(self, data: list[_FakeModel]) -> None:
        self.data = data


class _FakeOpenAIClient:
    def __init__(self, page: _FakePage | Exception) -> None:
        self._page_or_exc = page

        class _Models:
            def __init__(self, parent: _FakeOpenAIClient) -> None:
                self._parent = parent

            def list(self) -> Any:
                if isinstance(self._parent._page_or_exc, Exception):
                    raise self._parent._page_or_exc
                return self._parent._page_or_exc

        self.models = _Models(self)


def _patch_openai(monkeypatch: pytest.MonkeyPatch, client: _FakeOpenAIClient) -> None:
    monkeypatch.setattr(
        "codeguide.adapters.openai_model_catalog.openai.OpenAI",
        lambda **_kwargs: client,
    )


# ---------------------------------------------------------------------------
# _is_chat_capable filter — exhaustive cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_id",
    [
        "gpt-4.1",
        "gpt-5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "o1",
        "o3",
        "o4-mini",
        "chatgpt-4o-latest",
    ],
)
def test_chat_capable_models_pass_filter(model_id: str) -> None:
    assert _is_chat_capable(model_id) is True


@pytest.mark.parametrize(
    "model_id",
    [
        "ft:gpt-4.1-mini-2025-04-14:personal:my-finetune:abc123",
        "ft:gpt-3.5-turbo:personal:something:xyz",
    ],
)
def test_fine_tuned_models_are_filtered(model_id: str) -> None:
    """ft:* must be filtered — these are user-private models, would leak in shared configs."""
    assert _is_chat_capable(model_id) is False


@pytest.mark.parametrize(
    "model_id",
    [
        "gpt-4o-audio-preview",
        "gpt-realtime",
        "gpt-image-2",
        "gpt-image-1",
        "tts-1-hd",
        "whisper-1",
        "text-embedding-3-large",
        "omni-moderation-latest",
        "gpt-4o-transcribe",
        "dall-e-3",
        "sora-2",
        "gpt-5.4-codex",
        "o4-mini-deep-research",
        "gpt-5-search-api",
    ],
)
def test_non_chat_models_are_filtered(model_id: str) -> None:
    """Specialty endpoints must be filtered — they would crash the pipeline."""
    assert _is_chat_capable(model_id) is False


@pytest.mark.parametrize(
    "model_id",
    [
        "davinci-002",
        "babbage-002",
        "gpt-3.5-turbo-instruct",
        "gpt-3.5-turbo-instruct-0914",
    ],
)
def test_legacy_completion_models_are_filtered(model_id: str) -> None:
    assert _is_chat_capable(model_id) is False


# ---------------------------------------------------------------------------
# OpenAIModelCatalog.list_models() integration with filter + sort + fallback
# ---------------------------------------------------------------------------


def test_returns_chat_models_sorted_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage(
        [
            _FakeModel(id="gpt-4.1", created=1744316542),
            _FakeModel(id="gpt-5", created=1754425777),
            _FakeModel(id="gpt-4.1-mini", created=1744318173),
            _FakeModel(id="gpt-5.4", created=1772654062),
        ]
    )
    _patch_openai(monkeypatch, _FakeOpenAIClient(page))

    catalog = OpenAIModelCatalog(api_key="sk-test")
    result = catalog.list_models()

    assert result == ["gpt-5.4", "gpt-5", "gpt-4.1-mini", "gpt-4.1"]


def test_filters_ft_and_non_chat_from_mixed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real-world mixed response: filter ft:*, audio, embedding; keep gpt-* and o*."""
    page = _FakePage(
        [
            _FakeModel(id="gpt-5.4", created=1772654062),
            _FakeModel(id="gpt-4o-audio-preview", created=1727460443),
            _FakeModel(id="ft:gpt-4.1-mini-2025-04-14:personal:abc:xyz", created=1748933979),
            _FakeModel(id="text-embedding-3-large", created=1705953180),
            _FakeModel(id="gpt-4.1", created=1744316542),
            _FakeModel(id="dall-e-3", created=1698785189),
            _FakeModel(id="o3", created=1744225308),
        ]
    )
    _patch_openai(monkeypatch, _FakeOpenAIClient(page))

    catalog = OpenAIModelCatalog(api_key="sk-test")
    result = catalog.list_models()

    assert result == ["gpt-5.4", "gpt-4.1", "o3"]
    # Belt-and-braces: no ft:* leaked into result.
    assert all(not model.startswith("ft:") for model in result)
    # No non-chat markers.
    assert all("audio" not in model and "embedding" not in model for model in result)


def test_falls_back_when_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    catalog = OpenAIModelCatalog(api_key=None, base_url=None)

    assert catalog.list_models() == list(_FALLBACK)


def test_falls_back_when_sdk_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_openai(monkeypatch, _FakeOpenAIClient(RuntimeError("boom")))

    catalog = OpenAIModelCatalog(api_key="sk-test")

    assert catalog.list_models() == list(_FALLBACK)


def test_falls_back_when_all_filtered(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage(
        [
            _FakeModel(id="ft:foo:bar", created=1),
            _FakeModel(id="dall-e-3", created=2),
            _FakeModel(id="whisper-1", created=3),
        ]
    )
    _patch_openai(monkeypatch, _FakeOpenAIClient(page))

    catalog = OpenAIModelCatalog(api_key="sk-test")

    assert catalog.list_models() == list(_FALLBACK)


def test_fallback_uses_gpt_4_1_not_gpt_4o() -> None:
    """ADR-0013 D#12: project preference is gpt-4.1, never gpt-4o, in defaults."""
    assert "gpt-4.1" in _FALLBACK
    assert "gpt-4.1-mini" in _FALLBACK
    assert "gpt-4o" not in _FALLBACK
    assert "gpt-4o-mini" not in _FALLBACK


def test_base_url_only_still_attempts_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom endpoints (Ollama, vLLM) often need no API key — base_url alone fetches."""
    page = _FakePage([_FakeModel(id="llama3", created=100)])
    _patch_openai(monkeypatch, _FakeOpenAIClient(page))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    catalog = OpenAIModelCatalog(api_key=None, base_url="http://localhost:11434/v1")

    assert catalog.list_models() == ["llama3"]
