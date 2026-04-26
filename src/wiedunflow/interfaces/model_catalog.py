# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``ModelCatalog`` port — discover available chat-capable LLM models per provider.

ADR-0013 decision 11: model lists are fetched dynamically from the provider
API (``client.models.list()``) rather than hardcoded as Pydantic Literals.
Hardcoded fallbacks are used only when the API call fails (offline, missing
key, rate limit, 5xx). This keeps WiedunFlow current with new model releases
without requiring a WiedunFlow release.

Adapters live in ``wiedunflow.adapters.{anthropic,openai}_model_catalog``.
A ``CachedModelCatalog`` decorator (``wiedunflow.adapters.cached_model_catalog``)
wraps any concrete catalog with a 24-hour disk cache.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ModelCatalog(Protocol):
    """Port: enumerate chat-capable model IDs available to the configured provider.

    Implementations must:
    - Return chat-completion model IDs only — filter out audio, realtime,
      image, tts, whisper, embedding, moderation, transcribe, dall-e, sora.
    - Filter out provider-specific noise: OpenAI fine-tuned ``ft:*`` (private
      to the user, would leak into shared reports); Anthropic deprecated
      models surfaced by API but unsupported.
    - Sort the result newest-first by the provider's ``created`` timestamp
      so the menu shows the latest model at the top.
    - Return at least one entry — fall back to a hardcoded "latest known
      good" list if the API call fails. Never raise; the menu cannot
      gracefully recover from a model picker that crashes.
    """

    def list_models(self) -> list[str]:
        """Return chat-capable model IDs, newest first, never empty."""
        ...
