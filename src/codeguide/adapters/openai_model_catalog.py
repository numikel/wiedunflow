# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``OpenAIModelCatalog`` — fetch chat-capable OpenAI models via the SDK.

ADR-0013 decisions 11 & 12. ``openai.OpenAI().models.list()`` returns a
paginated list that includes everything OpenAI exposes: chat, audio,
realtime, image, tts, whisper, embedding, moderation, transcribe, fine-tuned
``ft:*`` models, etc. We must filter aggressively because:

- ``ft:*`` are user-private fine-tuned models — they would leak into shared
  config files and the model picker UI.
- non-chat models (whisper, dall-e, tts, embedding, moderation) are not
  valid for the planning/narration pipeline and would crash if selected.

Hardcoded fallback (used only on offline/no-key/rate-limit/exception):
``["gpt-5.4", "gpt-5.4-mini", "gpt-4.1", "gpt-4.1-mini"]`` — latest known
good per 2026-04-25 (v0.4.0). Note: ``gpt-4o`` is intentionally excluded —
project preference is ``gpt-4.1`` (ADR-0013 decision 12, see auto-memory
``project_openai_default_model``).
"""

from __future__ import annotations

import os

import openai
import structlog

logger = structlog.get_logger(__name__)

# Latest known-good OpenAI text-generation models per 2026-04-25.
# Note: gpt-4o is deliberately omitted in favor of gpt-4.1 (ADR-0013 D#12).
_FALLBACK: tuple[str, ...] = (
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
)

# Substrings that flag non-chat / specialty models the menu must not surface.
# Tuned for OpenAI's 2026 catalog (audio, realtime, image, tts, whisper,
# embedding, moderation, transcribe, dall-e, sora, codex). Match anywhere in
# the model id (case-insensitive) — covers gpt-4o-audio-preview, gpt-realtime,
# o4-mini-deep-research, etc.
_NON_CHAT_MARKERS: tuple[str, ...] = (
    "audio",
    "realtime",
    "image",
    "tts",
    "whisper",
    "embedding",
    "moderation",
    "transcribe",
    "dall-e",
    "sora",
    "codex",
    "search",
    "deep-research",
)


def _is_chat_capable(model_id: str) -> bool:
    """Return True for IDs that are valid for chat completions / responses APIs.

    Filters out:
    - ``ft:*`` fine-tuned (user-private)
    - Specialty endpoints (audio, realtime, image, tts, whisper, embedding,
      moderation, transcribe, dall-e, sora, codex, search, deep-research)
    - Legacy completion-only models (``davinci-002``, ``babbage-002``,
      ``gpt-3.5-turbo-instruct*``)
    """
    lowered = model_id.lower()
    if lowered.startswith("ft:"):
        return False
    if any(marker in lowered for marker in _NON_CHAT_MARKERS):
        return False
    if lowered.startswith(("davinci", "babbage")):
        return False
    return "instruct" not in lowered


class OpenAIModelCatalog:
    """``ModelCatalog`` impl backed by the official ``openai`` Python SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        timeout_s: float = 3.0,
    ) -> None:
        """Initialize the catalog.

        Args:
            api_key: Optional explicit API key. Falls back to
                ``OPENAI_API_KEY`` env var. If neither is available the
                catalog returns the hardcoded fallback on every call.
            base_url: Optional override for OpenAI-compatible endpoints
                (Ollama, LM Studio, vLLM). When set, the catalog hits the
                custom endpoint's ``/models`` route.
            timeout_s: HTTP timeout in seconds. The menu is interactive —
                slow API calls block the picker.
        """
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url
        self._timeout_s = timeout_s

    def list_models(self) -> list[str]:
        """Return chat-capable OpenAI model IDs newest-first.

        Filters out fine-tuned (``ft:*``) and non-chat models. Falls back
        to the hardcoded list when the API call fails. Never raises.
        """
        if not self._api_key and not self._base_url:
            logger.debug("openai_catalog_fallback", reason="no_api_key_or_base_url")
            return list(_FALLBACK)

        try:
            client = openai.OpenAI(
                api_key=self._api_key or "not-needed",
                base_url=self._base_url,
                timeout=self._timeout_s,
            )
            page = client.models.list()
        except Exception as exc:
            logger.warning(
                "openai_catalog_fetch_failed",
                error=type(exc).__name__,
                message=str(exc)[:200],
            )
            return list(_FALLBACK)

        items = list(getattr(page, "data", []) or [])
        if not items:
            logger.debug("openai_catalog_fallback", reason="empty_response")
            return list(_FALLBACK)

        # Filter out ft:*, audio/realtime/image/tts/whisper/embedding/moderation/...
        chat_models = [m for m in items if _is_chat_capable(getattr(m, "id", ""))]
        if not chat_models:
            logger.debug("openai_catalog_fallback", reason="all_filtered")
            return list(_FALLBACK)

        # Sort newest-first by `.created` (Unix timestamp).
        chat_models.sort(key=lambda m: getattr(m, "created", 0), reverse=True)
        return [m.id for m in chat_models if getattr(m, "id", None)]
