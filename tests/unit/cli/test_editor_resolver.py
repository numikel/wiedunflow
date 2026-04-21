# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-016: editor resolver order — $EDITOR -> $VISUAL -> code --wait -> notepad/vi."""
from __future__ import annotations

import sys

import pytest

from codeguide.cli.editor_resolver import resolve_editor


def test_editor_env_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDITOR", "my-editor --flag")
    monkeypatch.setenv("VISUAL", "ignored")
    assert resolve_editor() == ["my-editor", "--flag"]


def test_visual_fallback_when_editor_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setenv("VISUAL", "nano")
    # Force "code" off PATH so we hit the OS fallback.
    monkeypatch.setattr("codeguide.cli.editor_resolver.shutil.which", lambda _: None)
    assert resolve_editor() == ["nano"]


def test_os_default_when_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr("codeguide.cli.editor_resolver.shutil.which", lambda _: None)
    if sys.platform.startswith("win"):
        assert resolve_editor() == ["notepad"]
    else:
        assert resolve_editor() == ["vi"]


def test_code_wait_picked_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    assert resolve_editor() == ["code", "--wait"]
