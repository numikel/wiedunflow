# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for ``main_menu_loop`` and dispatch (ADR-0013 Step 3).

The loop is exercised through ``FakeMenuIO`` — no real prompt_toolkit
application starts, so tests run synchronously and deterministically.
"""

from __future__ import annotations

from typing import Any

import pytest

from codeguide.cli.menu import (
    MENU_EXIT,
    MENU_GENERATE,
    MENU_HELP,
    MENU_RESUME,
    MENU_SHOW_CONFIG,
    MenuIO,
    main_menu_loop,
)
from tests.unit.cli._fake_menu_io import FakeMenuIO


def _suppress_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence the ASCII banner so test output stays clean."""
    monkeypatch.setattr("codeguide.cli.menu.print_banner", lambda: None)


def test_exit_choice_terminates_loop_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    """Picking ``Exit`` from the menu returns from main_menu_loop in one iteration."""
    _suppress_banner(monkeypatch)
    io = FakeMenuIO(responses=[MENU_EXIT])

    main_menu_loop(io)

    assert len(io.calls) == 1
    assert io.calls[0][0] == "select"
    assert io.calls[0][2] == MENU_EXIT


def test_help_then_exit_runs_two_iterations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Help dispatches to its helper (which prompts an Enter pause), then loop redraws and Exit terminates."""
    _suppress_banner(monkeypatch)
    # Help renders a panel + ``_wait_for_return_to_menu`` (one io.text prompt)
    # before returning to the loop, so we need to supply that "press Enter" too.
    io = FakeMenuIO(responses=[MENU_HELP, "", MENU_EXIT])

    main_menu_loop(io)

    methods = [call[0] for call in io.calls]
    assert methods == ["select", "text", "select"]
    responses = [call[2] for call in io.calls]
    assert responses == [MENU_HELP, "", MENU_EXIT]


def test_esc_then_confirm_yes_exits_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Esc/Ctrl+C from the menu (None response) + confirm Yes terminates loop."""
    _suppress_banner(monkeypatch)
    io = FakeMenuIO(responses=[None, True])

    main_menu_loop(io)

    methods = [call[0] for call in io.calls]
    assert methods == ["select", "confirm"]


def test_esc_then_confirm_no_continues_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Esc + confirm No keeps the user in the menu — next iteration runs."""
    _suppress_banner(monkeypatch)
    io = FakeMenuIO(responses=[None, False, MENU_EXIT])

    main_menu_loop(io)

    methods = [call[0] for call in io.calls]
    assert methods == ["select", "confirm", "select"]


def test_esc_then_confirm_aborted_treated_as_no(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm prompt also returning None (double-Esc) keeps the loop alive."""
    _suppress_banner(monkeypatch)
    io = FakeMenuIO(responses=[None, None, MENU_EXIT])

    main_menu_loop(io)

    methods = [call[0] for call in io.calls]
    assert methods == ["select", "confirm", "select"]


@pytest.mark.parametrize(
    "choice",
    [MENU_GENERATE, MENU_SHOW_CONFIG, MENU_RESUME, MENU_HELP],
)
def test_each_menu_choice_dispatches_then_returns(
    choice: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every dispatch helper must return cleanly so the loop survives.

    Real sub-wizards (Steps 5-8) consume `MenuIO` responses themselves; the
    dispatch test is interested only in routing, so each helper is patched
    to a no-op and we assert the loop redraws the menu after the helper
    returns.
    """
    _suppress_banner(monkeypatch)
    for helper in (
        "_run_generate_from_menu",
        "_run_config_from_menu",
        "_run_estimate_from_menu",
        "_run_recent_from_menu",
        "_run_help_from_menu",
    ):
        monkeypatch.setattr(f"codeguide.cli.menu.{helper}", lambda *a, **k: None)
    io = FakeMenuIO(responses=[choice, MENU_EXIT])

    main_menu_loop(io)

    methods = [call[0] for call in io.calls]
    assert methods == ["select", "select"]


def test_menu_io_protocol_satisfied_by_fake() -> None:
    """``FakeMenuIO`` must structurally satisfy the ``MenuIO`` Protocol."""
    io: MenuIO = FakeMenuIO(responses=[])
    # If this typechecks at runtime via Protocol.runtime_checkable it confirms structural fit.
    assert isinstance(io, MenuIO)


def test_menu_io_protocol_satisfied_by_questionary_impl() -> None:
    """``QuestionaryMenuIO`` must satisfy the Protocol — production guarantee."""
    from codeguide.cli.menu import QuestionaryMenuIO

    io: MenuIO = QuestionaryMenuIO()
    assert isinstance(io, MenuIO)


def test_fake_menu_io_raises_when_responses_exhausted() -> None:
    """Loop bug detection: if the menu over-requests, FakeMenuIO surfaces it."""
    io = FakeMenuIO(responses=[])
    with pytest.raises(IndexError, match="ran out of responses"):
        io.select("any", choices=["a"])


def _typecheck_unused(io: MenuIO) -> Any:  # pragma: no cover — typing helper
    """Helper to placate ``ruff`` about unused MenuIO import."""
    return io
