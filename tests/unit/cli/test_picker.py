# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for ``_subwizard_pick_repo`` UX flow (ADR-0013 picker §1)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wiedunflow.cli.menu import _subwizard_pick_repo
from tests.unit.cli._fake_menu_io import FakeMenuIO

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_git_repo(path: Path) -> Path:
    """Create a real git repo so .git/ exists and passes validation."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def _make_fake_git_repo(path: Path) -> Path:
    """Lightweight fake .git/ — no git binary needed for discovery tests."""
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    (path / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# 1. Recent runs — happy path
# ---------------------------------------------------------------------------


def test_subwizard_pick_repo_recent_happy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Select 'Recent runs' → pick a path → returns that Path."""
    repo = _make_git_repo(tmp_path / "myrepo")

    monkeypatch.setattr(
        "wiedunflow.cli.menu.load_recent_runs",
        lambda limit=10: [repo],
    )

    io = FakeMenuIO(
        responses=[
            "Recent runs",  # source selector
            str(repo),  # pick from recent list
        ]
    )

    result = _subwizard_pick_repo(io)

    assert result == repo


# ---------------------------------------------------------------------------
# 2. Discover — ignored dirs filtered out
# ---------------------------------------------------------------------------


def test_subwizard_pick_repo_discover_filters_ignored(tmp_path: Path) -> None:
    """Ignored dirs (node_modules, .venv, dist) must not appear in discover list."""
    _make_fake_git_repo(tmp_path / "myproject")
    _make_fake_git_repo(tmp_path / "node_modules")
    _make_fake_git_repo(tmp_path / ".venv")
    _make_fake_git_repo(tmp_path / "dist")

    # We expect only "myproject" to appear in the select call.
    selected_label: list[str] = []

    class _CapturingIO(FakeMenuIO):
        def select(
            self, message: str, choices: list[str], default: str | None = None
        ) -> str | None:  # type: ignore[override]
            if "Git repos" in message:
                selected_label.extend(choices)
                # Pick the real repo (first non-Back entry)
                for c in choices:
                    if "Back" not in c:
                        return c
            return super().select(message, choices, default)

    io = _CapturingIO(responses=["Discover in cwd"])

    result = _subwizard_pick_repo(io, cwd=tmp_path)

    # node_modules / .venv / dist must not appear in the choices shown
    for label in selected_label:
        assert "node_modules" not in label
        assert ".venv" not in label
        assert "dist" not in label

    assert result is not None
    assert result.name == "myproject"


# ---------------------------------------------------------------------------
# 3. Manual — invokes io.path
# ---------------------------------------------------------------------------


def test_subwizard_pick_repo_manual_invokes_path_prompt(tmp_path: Path) -> None:
    """Selecting 'Type path manually' must call io.path and return the result."""
    repo = _make_git_repo(tmp_path / "manualrepo")

    io = FakeMenuIO(
        responses=[
            "Type path manually",  # source selector
            str(repo),  # io.path response
        ]
    )

    result = _subwizard_pick_repo(io)

    assert result == repo
    method_names = [call[0] for call in io.calls]
    assert "path" in method_names


# ---------------------------------------------------------------------------
# 4. Back in sub-list → returns to source selector
# ---------------------------------------------------------------------------


def test_subwizard_pick_repo_back_returns_to_source_selector(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """'Back' in Recent-runs sub-list → returns to source selector; can pick Manual next."""
    repo = _make_git_repo(tmp_path / "repo")

    monkeypatch.setattr(
        "wiedunflow.cli.menu.load_recent_runs",
        lambda limit=10: [repo],
    )

    io = FakeMenuIO(
        responses=[
            "Recent runs",  # source selector, first iteration
            "Back",  # go back to source selector
            "Type path manually",  # source selector, second iteration
            str(repo),  # io.path
        ]
    )

    result = _subwizard_pick_repo(io)

    assert result == repo


# ---------------------------------------------------------------------------
# 5. Empty recent runs → echo message → continue loop (manual fallback)
# ---------------------------------------------------------------------------


def test_subwizard_pick_repo_empty_recent_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When recent runs are empty the picker continues the loop (no crash)."""
    repo = _make_git_repo(tmp_path / "repo")

    monkeypatch.setattr(
        "wiedunflow.cli.menu.load_recent_runs",
        lambda limit=10: [],
    )

    io = FakeMenuIO(
        responses=[
            "Recent runs",  # source selector — will find empty
            "Type path manually",  # source selector — second try
            str(repo),  # io.path
        ]
    )

    result = _subwizard_pick_repo(io)

    assert result == repo


# ---------------------------------------------------------------------------
# 6. Esc / None at top-level → returns None
# ---------------------------------------------------------------------------


def test_subwizard_pick_repo_esc_aborts(tmp_path: Path) -> None:
    """Esc (None) at the top-level source selector returns None."""
    io = FakeMenuIO(responses=[None])

    result = _subwizard_pick_repo(io)

    assert result is None
