# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Exhaustive tests for ``_should_launch_menu()`` (ADR-0013 Step 2).

The menu must launch only when ``wiedunflow`` is invoked with no arguments in
an interactive TTY without the ``WIEDUNFLOW_NO_MENU`` override. Every other
case — subcommand, --version/--help, non-TTY, env override — must keep the
legacy click group flow.

This guard is the single load-bearing detection between the new TUI and the
existing CLI contract (Sprint 7 eval workflow runs subprocess.run with explicit
``generate`` argv, so the argv check fires before any TTY logic — doubly safe).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from wiedunflow.cli.menu import _should_launch_menu


@pytest.fixture
def patched_argv_and_tty(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Helper context: patches sys.argv, sys.stdin/stdout.isatty, and env."""
    # Defaults — overridden per test case via monkeypatch.
    monkeypatch.setattr("sys.argv", ["wiedunflow"])
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.delenv("WIEDUNFLOW_NO_MENU", raising=False)
    yield monkeypatch


def test_no_args_plus_tty_launches_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """The canonical menu-launch case: bare ``wiedunflow`` in an interactive shell."""
    assert _should_launch_menu() is True


def test_generate_subcommand_skips_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """``wiedunflow generate ./repo`` must fall through to the click group."""
    patched_argv_and_tty.setattr("sys.argv", ["wiedunflow", "generate", "./repo"])
    assert _should_launch_menu() is False


def test_init_subcommand_skips_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """``wiedunflow init`` must keep the existing click-prompt wizard."""
    patched_argv_and_tty.setattr("sys.argv", ["wiedunflow", "init"])
    assert _should_launch_menu() is False


def test_version_flag_skips_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """``wiedunflow --version`` must print the version and exit, not enter menu."""
    patched_argv_and_tty.setattr("sys.argv", ["wiedunflow", "--version"])
    assert _should_launch_menu() is False


def test_help_flag_skips_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """``wiedunflow --help`` must show click help, not the menu."""
    patched_argv_and_tty.setattr("sys.argv", ["wiedunflow", "--help"])
    assert _should_launch_menu() is False


def test_short_help_flag_skips_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """``wiedunflow -h`` must show click help, not the menu."""
    patched_argv_and_tty.setattr("sys.argv", ["wiedunflow", "-h"])
    assert _should_launch_menu() is False


def test_legacy_repo_arg_skips_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """``wiedunflow ./repo`` (Sprint 6 backward-compat) must route through click group."""
    patched_argv_and_tty.setattr("sys.argv", ["wiedunflow", "./my-project"])
    assert _should_launch_menu() is False


def test_non_tty_stdin_skips_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """Piped stdin (``echo "" | wiedunflow``) must not launch menu — would block forever."""
    patched_argv_and_tty.setattr("sys.stdin.isatty", lambda: False)
    assert _should_launch_menu() is False


def test_non_tty_stdout_skips_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """Piped stdout (``wiedunflow > log.txt``) must not launch menu — output is non-interactive."""
    patched_argv_and_tty.setattr("sys.stdout.isatty", lambda: False)
    assert _should_launch_menu() is False


def test_env_override_skips_menu(patched_argv_and_tty: pytest.MonkeyPatch) -> None:
    """``WIEDUNFLOW_NO_MENU=1`` is the emergency escape hatch."""
    patched_argv_and_tty.setenv("WIEDUNFLOW_NO_MENU", "1")
    assert _should_launch_menu() is False


def test_env_override_any_truthy_value_skips_menu(
    patched_argv_and_tty: pytest.MonkeyPatch,
) -> None:
    """Any non-empty ``WIEDUNFLOW_NO_MENU`` value disables the menu."""
    patched_argv_and_tty.setenv("WIEDUNFLOW_NO_MENU", "true")
    assert _should_launch_menu() is False


def test_env_override_empty_string_does_not_skip(
    patched_argv_and_tty: pytest.MonkeyPatch,
) -> None:
    """Empty ``WIEDUNFLOW_NO_MENU=""`` is treated as unset (os.environ.get returns "")."""
    patched_argv_and_tty.setenv("WIEDUNFLOW_NO_MENU", "")
    assert _should_launch_menu() is True
