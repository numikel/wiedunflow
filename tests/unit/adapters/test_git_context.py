# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for the git_context adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codeguide.adapters.git_context import get_git_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path, *, branch: str = "main") -> None:
    """Initialise a throw-away git repo with a single empty commit."""
    subprocess.run(["git", "init", "-b", branch, str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    (path / "README.md").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_git_context_returns_hash_and_branch(tmp_path: Path) -> None:
    """A freshly-initialised repo yields a 40-char hex hash and branch name."""
    _init_git_repo(tmp_path, branch="main")
    commit_hash, branch = get_git_context(tmp_path)

    assert commit_hash != "unknown", "Expected a real commit hash, got 'unknown'"
    assert len(commit_hash) == 40, f"Expected 40-char hash, got {commit_hash!r}"
    assert all(c in "0123456789abcdef" for c in commit_hash)
    assert branch == "main"


def test_get_git_context_non_default_branch(tmp_path: Path) -> None:
    """Branch name reflects the branch passed at init time."""
    _init_git_repo(tmp_path, branch="feature-x")
    _, branch = get_git_context(tmp_path)
    assert branch == "feature-x"


def test_get_git_context_non_git_directory_returns_unknown(tmp_path: Path) -> None:
    """A plain directory (no .git) returns ('unknown', 'unknown')."""
    commit_hash, branch = get_git_context(tmp_path)
    assert commit_hash == "unknown"
    assert branch == "unknown"


def test_get_git_context_nonexistent_path_returns_unknown(tmp_path: Path) -> None:
    """A non-existent path returns ('unknown', 'unknown') gracefully."""
    missing = tmp_path / "does_not_exist"
    commit_hash, branch = get_git_context(missing)
    assert commit_hash == "unknown"
    assert branch == "unknown"


def test_get_git_context_returns_tuple_of_strings(tmp_path: Path) -> None:
    """Return type is always tuple[str, str] regardless of git availability."""
    result = get_git_context(tmp_path)
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert all(isinstance(v, str) for v in result)


@pytest.mark.parametrize("branch", ["main", "develop", "feat/sprint-2"])
def test_get_git_context_branch_names(tmp_path: Path, branch: str) -> None:
    """Various branch naming conventions are preserved correctly."""
    # git does not allow '/' in branch names created with -b; use checkout after init.
    base_branch = "main"
    _init_git_repo(tmp_path, branch=base_branch)

    if branch != base_branch:
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    _, returned_branch = get_git_context(tmp_path)
    assert returned_branch == branch
