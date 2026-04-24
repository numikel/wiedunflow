# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-016: editor resolver order — $EDITOR -> $VISUAL -> code --wait -> notepad/vi."""

from __future__ import annotations

import pytest

from codeguide.cli.editor_resolver import resolve_editor


def test_editor_env_takes_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDITOR", "my-editor --flag")
    monkeypatch.setenv("VISUAL", "ignored")
    # Simulate my-editor found on PATH.
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("my-editor", "ignored") else None,
    )
    assert resolve_editor() == ["my-editor", "--flag"]


def test_visual_fallback_when_editor_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setenv("VISUAL", "nano")
    # "nano" is on PATH; "code" is not.
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: "/usr/bin/nano" if cmd == "nano" else None,
    )
    assert resolve_editor() == ["nano"]


def test_os_default_when_nothing_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    # Force every which() call to None so we hit the absolute-path fallbacks.
    monkeypatch.setattr("codeguide.cli.editor_resolver.shutil.which", lambda _: None)
    # Also prevent Path.exists() from randomly succeeding on the test host.
    monkeypatch.setattr("codeguide.cli.editor_resolver.Path.exists", lambda _: False)
    result = resolve_editor()
    assert result is None  # No safe editor available in stripped PATH.


def test_code_wait_picked_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    assert resolve_editor() == ["code", "--wait"]
