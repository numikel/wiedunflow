# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Shared pytest fixtures for ``tests/unit/cli/``.

Disables the menu's ANSI clear-screen escape so ``capsys`` assertions can
match plain text without VT control characters polluting the captured stdout.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _disable_menu_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    """Suppress ``_clear_screen`` + ``_redraw_chrome`` ANSI escapes in every CLI test."""
    monkeypatch.setenv("WIEDUNFLOW_NO_CLEAR", "1")


@pytest.fixture(autouse=True)
def _disable_litellm_pricing_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the menu's default pricing chain from hitting the LiteLLM HTTP API.

    Every menu code path that estimates cost lazily builds a
    ``ChainedPricingCatalog`` whose primary is a ``LiteLLMPricingCatalog``.
    Without this fixture each test would either wait 3s for an HTTP timeout
    (offline CI runners) or pull half a megabyte of JSON. We pin the
    upstream's internal ``_cache`` to an empty dict so the chain falls
    through to ``StaticPricingCatalog`` instantly.
    """
    monkeypatch.setattr(
        "wiedunflow.adapters.litellm_pricing_catalog.LiteLLMPricingCatalog._ensure_loaded",
        lambda self: {},
    )


@pytest.fixture(autouse=True)
def _isolate_user_config_path(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirect ``user_config_path()`` into a tmp dir for every CLI test.

    Without this, ``load_config()`` in tests like ``test_default_is_mid_when_not_specified``
    silently merges values from the developer's real ``~/.config/wiedunflow/config.yaml``,
    producing flaky results that depend on prior interactive runs.
    """
    target = tmp_path_factory.mktemp("user-config") / "config.yaml"
    monkeypatch.setattr("wiedunflow.cli.config.user_config_path", lambda: target)
    monkeypatch.setattr("wiedunflow.cli.menu.user_config_path", lambda: target)
    return target
