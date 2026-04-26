# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``AnthropicModelCatalog`` — fetch chat-capable Claude models via the SDK.

ADR-0013 decision 11. ``anthropic.Anthropic().models.list()`` returns a
paginated list of ``ModelInfo`` objects with ``id`` and ``created_at``
fields. We sort newest-first and surface every entry — Anthropic's API
already filters deprecated models, so no further filtering is needed.

Hardcoded fallback (used only on offline/no-key/rate-limit/exception):
``["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"]`` — latest
known good as of 2026-04-25 (v0.4.0 release date). Update this list with
each major Anthropic release.
"""

from __future__ import annotations

import os

import anthropic
import structlog

logger = structlog.get_logger(__name__)

# Latest known-good Claude models per 2026-04-25; used only when the API
# call fails. Order matters — newest first, mirroring the live API sort.
_FALLBACK: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
)


class AnthropicModelCatalog:
    """``ModelCatalog`` impl backed by the official ``anthropic`` Python SDK."""

    def __init__(self, api_key: str | None = None, *, timeout_s: float = 3.0) -> None:
        """Initialize the catalog.

        Args:
            api_key: Optional explicit API key. Falls back to
                ``ANTHROPIC_API_KEY`` env var. If neither is available the
                catalog falls back to the hardcoded list on every call.
            timeout_s: HTTP timeout for the ``models.list()`` request. Short
                by default — the menu is interactive and a slow API call
                blocks the picker render.
        """
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._timeout_s = timeout_s

    def list_models(self) -> list[str]:
        """Return chat-capable Claude model IDs newest-first.

        Falls back to the hardcoded "latest known good" list if the API call
        fails for any reason. Never raises — the menu picker depends on this.
        """
        if not self._api_key:
            logger.debug("anthropic_catalog_fallback", reason="no_api_key")
            return list(_FALLBACK)

        try:
            client = anthropic.Anthropic(api_key=self._api_key, timeout=self._timeout_s)
            page = client.models.list()
        except Exception as exc:
            logger.warning(
                "anthropic_catalog_fetch_failed",
                error=type(exc).__name__,
                message=str(exc)[:200],
            )
            return list(_FALLBACK)

        # ModelInfo objects expose .id and .created_at (datetime-like). Newer first.
        items = list(getattr(page, "data", []) or [])
        if not items:
            logger.debug("anthropic_catalog_fallback", reason="empty_response")
            return list(_FALLBACK)

        items.sort(key=lambda m: getattr(m, "created_at", ""), reverse=True)
        ids = [m.id for m in items if getattr(m, "id", None)]
        return ids or list(_FALLBACK)
