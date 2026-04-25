# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for §3 dynamic list manager and ``_subwizard_filters`` (Step 6).

The list-manager state machine is the trickiest UX in the wizard — selects
drive add/edit/remove/done with retry on validation failure and discard
confirm on mid-flow Esc. Each branch must be deterministic with FakeMenuIO.
"""

from __future__ import annotations

import pytest

from codeguide.cli.menu import (
    _LIST_ADD,
    _LIST_DONE,
    _LIST_EDIT,
    _LIST_REMOVE,
    _list_manager,
    _subwizard_filters,
    _validate_pattern,
)
from tests.unit.cli._fake_menu_io import FakeMenuIO

# ---------------------------------------------------------------------------
# _validate_pattern
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "tests/**",
        "*.pyc",
        "src/foo/*.py",
        "docs/generated/**/*",
        "Makefile",
    ],
)
def test_validate_pattern_accepts_valid(raw: str) -> None:
    assert _validate_pattern(raw) is None


@pytest.mark.parametrize(
    "raw,marker",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("../escape", "parent directories"),
        ("..", "parent directories"),
        ("foo/../bar", "parent directories"),
        ("with\x00null", "null byte"),
    ],
)
def test_validate_pattern_rejects_invalid(raw: str, marker: str) -> None:
    error = _validate_pattern(raw)
    assert error is not None
    assert marker in error


# ---------------------------------------------------------------------------
# _list_manager — Add / Edit / Remove / Done
# ---------------------------------------------------------------------------


def test_list_manager_done_with_empty_initial() -> None:
    io = FakeMenuIO(responses=[_LIST_DONE])

    assert _list_manager(io, "Exclude patterns", []) == []


def test_list_manager_add_then_done() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_ADD,
            "tests/**",
            _LIST_DONE,
        ]
    )

    result = _list_manager(io, "Exclude patterns", [])

    assert result == ["tests/**"]


def test_list_manager_add_two_then_done() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_ADD,
            "tests/**",
            _LIST_ADD,
            "*.pyc",
            _LIST_DONE,
        ]
    )

    result = _list_manager(io, "Exclude patterns", [])

    assert result == ["tests/**", "*.pyc"]


def test_list_manager_add_invalid_pattern_retries() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_ADD,
            "../escape",  # rejected
            "*.pyc",  # accepted
            _LIST_DONE,
        ]
    )

    result = _list_manager(io, "Exclude patterns", [])

    assert result == ["*.pyc"]


def test_list_manager_edit_replaces_in_place() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_EDIT,
            "old/**",  # picked
            "new/**",  # new value
            _LIST_DONE,
        ]
    )

    result = _list_manager(io, "Exclude patterns", ["old/**", "*.pyc"])

    assert result == ["new/**", "*.pyc"]


def test_list_manager_remove_with_confirm() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_REMOVE,
            "*.pyc",  # picked
            True,  # confirm yes
            _LIST_DONE,
        ]
    )

    result = _list_manager(io, "Exclude patterns", ["tests/**", "*.pyc"])

    assert result == ["tests/**"]


def test_list_manager_remove_confirm_no_keeps_item() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_REMOVE,
            "*.pyc",
            False,  # confirm no
            _LIST_DONE,
        ]
    )

    result = _list_manager(io, "Exclude patterns", ["*.pyc"])

    assert result == ["*.pyc"]


def test_list_manager_esc_with_no_changes_aborts() -> None:
    """Esc on the action picker with pristine list returns None silently."""
    io = FakeMenuIO(responses=[None])

    assert _list_manager(io, "Exclude patterns", ["a"]) is None


def test_list_manager_esc_with_changes_prompts_discard_yes() -> None:
    """Esc with pending edits + Yes discards. Returns None."""
    io = FakeMenuIO(
        responses=[
            _LIST_ADD,
            "new",
            None,  # Esc on action picker
            True,  # discard? yes
        ]
    )

    assert _list_manager(io, "Exclude patterns", ["original"]) is None


def test_list_manager_esc_with_changes_discard_no_continues() -> None:
    """Esc + No → keeps in-progress edits, loop continues."""
    io = FakeMenuIO(
        responses=[
            _LIST_ADD,
            "new",
            None,  # Esc
            False,  # discard? no → continue
            _LIST_DONE,
        ]
    )

    result = _list_manager(io, "Exclude patterns", ["original"])

    assert result == ["original", "new"]


def test_list_manager_add_abort_returns_none() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_ADD,
            None,  # Esc on text prompt
        ]
    )

    assert _list_manager(io, "Exclude patterns", []) is None


def test_list_manager_edit_abort_on_pick_returns_none() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_EDIT,
            None,  # Esc on item picker
        ]
    )

    assert _list_manager(io, "Exclude patterns", ["a", "b"]) is None


def test_list_manager_edit_abort_on_text_returns_none() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_EDIT,
            "a",  # picked
            None,  # Esc on edit text
        ]
    )

    assert _list_manager(io, "Exclude patterns", ["a"]) is None


def test_list_manager_remove_abort_on_pick_returns_none() -> None:
    io = FakeMenuIO(
        responses=[
            _LIST_REMOVE,
            None,
        ]
    )

    assert _list_manager(io, "Exclude patterns", ["a"]) is None


# ---------------------------------------------------------------------------
# _subwizard_filters
# ---------------------------------------------------------------------------


def test_subwizard_filters_skip_returns_saved_defaults() -> None:
    """Customize? No → return saved values unchanged."""
    io = FakeMenuIO(responses=[False])

    result = _subwizard_filters(
        io,
        saved_excludes=["tests/**"],
        saved_includes=[],
    )

    assert result == {"exclude_patterns": ["tests/**"], "include_patterns": []}


def test_subwizard_filters_skip_with_no_saved_returns_empty() -> None:
    io = FakeMenuIO(responses=[False])

    result = _subwizard_filters(io)

    assert result == {"exclude_patterns": [], "include_patterns": []}


def test_subwizard_filters_full_flow() -> None:
    """Customize? Yes → exclude list manager → include list manager → returns both."""
    io = FakeMenuIO(
        responses=[
            True,  # customize? yes
            # exclude list
            _LIST_ADD,
            "tests/**",
            _LIST_DONE,
            # include list
            _LIST_ADD,
            "src/**/*.py",
            _LIST_DONE,
        ]
    )

    result = _subwizard_filters(io)

    assert result == {
        "exclude_patterns": ["tests/**"],
        "include_patterns": ["src/**/*.py"],
    }


def test_subwizard_filters_abort_on_customize_prompt() -> None:
    io = FakeMenuIO(responses=[None])

    assert _subwizard_filters(io) is None


def test_subwizard_filters_abort_on_exclude_list() -> None:
    io = FakeMenuIO(
        responses=[
            True,  # customize? yes
            None,  # Esc on exclude list (no changes → silent abort)
        ]
    )

    assert _subwizard_filters(io) is None


def test_subwizard_filters_abort_on_include_list() -> None:
    io = FakeMenuIO(
        responses=[
            True,
            _LIST_DONE,  # exclude empty → done
            None,  # Esc on include list
        ]
    )

    assert _subwizard_filters(io) is None
