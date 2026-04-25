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
    monkeypatch.setenv("CODEGUIDE_NO_CLEAR", "1")


@pytest.fixture(autouse=True)
def _isolate_user_config_path(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirect ``user_config_path()`` into a tmp dir for every CLI test.

    Without this, ``load_config()`` in tests like ``test_default_is_mid_when_not_specified``
    silently merges values from the developer's real ``~/.config/codeguide/config.yaml``,
    producing flaky results that depend on prior interactive runs.
    """
    target = tmp_path_factory.mktemp("user-config") / "config.yaml"
    monkeypatch.setattr("codeguide.cli.config.user_config_path", lambda: target)
    monkeypatch.setattr("codeguide.cli.menu.user_config_path", lambda: target)
    return target
