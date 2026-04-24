# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michal Kaminski

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from codeguide.cli.editor_resolver import (
    EditorResolutionError,
    _validate_editor_cmd,
    open_in_editor,
    resolve_editor,
)

BACKTICK_PAYLOAD = "echo " + chr(96) + "pwned" + chr(96)
DOLLAR_PAREN_PAYLOAD = chr(36) + "(pwned)"


@pytest.mark.parametrize(
    "env_value,should_be_safe",
    [
        ("rm -rf /", False),
        ("vi; rm -rf /", False),
        ("vi | cat /etc/passwd", False),
        ("vi && evil-cmd", False),
        ("vi || evil-cmd", False),
        (BACKTICK_PAYLOAD, False),
        (DOLLAR_PAREN_PAYLOAD, False),
        ("vi >&2", False),
        ("", False),
        ("   ", False),
        ('vi "unclosed quote', False),
        ("code --wait", True),
        ("vi", True),
    ],
)
def test_validate_editor_cmd(
    env_value: str,
    should_be_safe: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_validate_editor_cmd should accept safe inputs and reject malicious ones."""
    safe_binaries = {"code", "vi", "nano", "emacs"}
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd in safe_binaries else None,
    )
    result = _validate_editor_cmd(env_value)
    if should_be_safe:
        assert result is not None
        assert isinstance(result, list)
        assert len(result) > 0
    else:
        assert result is None


def test_validate_editor_cmd_not_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """A syntactically valid command whose binary is not on PATH is rejected."""
    monkeypatch.setattr("codeguide.cli.editor_resolver.shutil.which", lambda _: None)
    assert _validate_editor_cmd("phantom-editor --wait") is None


def test_validate_editor_cmd_with_valid_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """Flags following a safe binary are preserved."""
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    result = _validate_editor_cmd("code --wait --new-window")
    assert result == ["code", "--wait", "--new-window"]


def test_resolver_falls_through_to_visual_when_editor_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When EDITOR is malicious, resolution must fall through to VISUAL."""
    monkeypatch.setenv("EDITOR", "vi; rm -rf /")
    monkeypatch.setenv("VISUAL", "nano")
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: "/usr/bin/nano" if cmd == "nano" else None,
    )
    assert resolve_editor() == ["nano"]


def test_resolver_falls_through_to_code_when_both_env_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both EDITOR and VISUAL are invalid, code --wait is the fallback."""
    monkeypatch.setenv("EDITOR", "vi | cat")
    monkeypatch.setenv("VISUAL", "nano " + chr(96) + "pwned" + chr(96))
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    assert resolve_editor() == ["code", "--wait"]


def test_resolver_returns_none_when_all_candidates_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When every candidate is rejected, resolve_editor returns None."""
    monkeypatch.setenv("EDITOR", "evil" + chr(36) + "(inject)")
    monkeypatch.setenv("VISUAL", "vi || bad")
    monkeypatch.setattr("codeguide.cli.editor_resolver.shutil.which", lambda _: None)
    monkeypatch.setattr("codeguide.cli.editor_resolver.Path.exists", lambda _: False)
    assert resolve_editor() is None


def test_resolver_valid_editor_env_takes_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid EDITOR must be preferred over VISUAL and code --wait."""
    monkeypatch.setenv("EDITOR", "emacs --no-init-file")
    monkeypatch.setenv("VISUAL", "nano")
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd in ("emacs", "nano", "code") else None,
    )
    result = resolve_editor()
    assert result is not None
    assert result[0] == "emacs"


def test_open_in_editor_uses_shell_false(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """subprocess.run must always be invoked with shell=False."""
    target = tmp_path / "plan.md"
    target.write_text("# plan")
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(
        "codeguide.cli.editor_resolver.shutil.which",
        lambda cmd: "/usr/bin/code" if cmd == "code" else None,
    )
    captured: dict[str, object] = {}

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        mock = MagicMock()
        mock.returncode = 0
        return mock

    monkeypatch.setattr("codeguide.cli.editor_resolver.subprocess.run", fake_run)
    rc = open_in_editor(target)
    assert rc == 0
    assert captured["kwargs"].get("shell") is False, "shell=False must be enforced"
    assert str(target) in captured["cmd"]


def test_open_in_editor_raises_when_no_editor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """EditorResolutionError is raised when no safe editor can be resolved."""
    target = tmp_path / "plan.md"
    target.write_text("# plan")
    monkeypatch.setenv("EDITOR", "vi" + chr(36) + "(bad)")
    monkeypatch.setenv("VISUAL", "nano && evil")
    monkeypatch.setattr("codeguide.cli.editor_resolver.shutil.which", lambda _: None)
    monkeypatch.setattr("codeguide.cli.editor_resolver.Path.exists", lambda _: False)
    with pytest.raises(EditorResolutionError):
        open_in_editor(target)


@pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="Windows-specific notepad absolute-path fallback",
)
def test_windows_notepad_absolute_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows, hardcoded notepad.exe is used when which() fails."""
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr("codeguide.cli.editor_resolver.shutil.which", lambda _: None)
    monkeypatch.setattr("codeguide.cli.editor_resolver.Path.exists", lambda _: True)
    result = resolve_editor()
    assert result is not None
    assert "notepad.exe" in result[0]


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Unix-specific /usr/bin/vi absolute-path fallback",
)
def test_unix_vi_absolute_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Unix, /usr/bin/vi is used as last resort when which() returns None."""
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr("codeguide.cli.editor_resolver.shutil.which", lambda _: None)
    monkeypatch.setattr("codeguide.cli.editor_resolver.Path.exists", lambda _: True)
    result = resolve_editor()
    assert result is not None
    assert "vi" in result[0]
