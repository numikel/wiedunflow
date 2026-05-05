# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for the --yes-execute-repo-code consent guard around --bootstrap-venv."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from wiedunflow.cli.main import _confirm_repo_code_exec


def test_non_tty_without_flag_aborts(tmp_path: Path) -> None:
    """In non-TTY contexts, missing --yes-execute-repo-code -> False (abort path)."""
    result = _confirm_repo_code_exec(
        tmp_path, yes_flag=False, is_tty=False, console=Console(stderr=True)
    )
    assert result is False


def test_non_tty_with_flag_proceeds(tmp_path: Path) -> None:
    """Non-TTY but explicit consent flag -> True (proceed)."""
    result = _confirm_repo_code_exec(
        tmp_path, yes_flag=True, is_tty=False, console=Console(stderr=True)
    )
    assert result is True


def test_tty_with_flag_skips_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """TTY + flag -> no interactive prompt, returns True."""
    confirm_called = MagicMock()
    monkeypatch.setattr("click.confirm", confirm_called)
    result = _confirm_repo_code_exec(
        tmp_path, yes_flag=True, is_tty=True, console=Console(stderr=True)
    )
    assert result is True
    confirm_called.assert_not_called()


def test_tty_without_flag_prompts_yes_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTY without flag -> prompt; user confirms -> True."""
    monkeypatch.setattr("click.confirm", lambda *a, **kw: True)
    result = _confirm_repo_code_exec(
        tmp_path, yes_flag=False, is_tty=True, console=Console(stderr=True)
    )
    assert result is True


def test_tty_without_flag_prompts_no_aborts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TTY without flag -> prompt; user declines -> False."""
    monkeypatch.setattr("click.confirm", lambda *a, **kw: False)
    result = _confirm_repo_code_exec(
        tmp_path, yes_flag=False, is_tty=True, console=Console(stderr=True)
    )
    assert result is False
