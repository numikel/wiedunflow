# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Git context adapter — resolves HEAD commit hash and branch name."""

from __future__ import annotations

import subprocess
from pathlib import Path


def get_git_context(repo_root: Path) -> tuple[str, str]:
    """Return ``(commit_hash, branch)`` for the given repository root.

    Runs ``git rev-parse HEAD`` and ``git rev-parse --abbrev-ref HEAD`` via
    subprocess.  Falls back to ``("unknown", "unknown")`` on any error
    (non-git directory, git not found, detached HEAD, etc.).

    Args:
        repo_root: Absolute path to the root of the git repository.

    Returns:
        A 2-tuple of ``(commit_hash, branch)``.  Either element is the
        string ``"unknown"`` when the corresponding git command fails.
    """
    commit_hash = _run_git(repo_root, ["rev-parse", "HEAD"])
    branch = _run_git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
    return commit_hash, branch


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_UNKNOWN = "unknown"


def _run_git(repo_root: Path, args: list[str]) -> str:
    """Run a git subcommand and return its stripped stdout, or ``'unknown'``."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, NotADirectoryError, subprocess.TimeoutExpired):
        return _UNKNOWN

    if result.returncode != 0:
        return _UNKNOWN

    value = result.stdout.strip()
    return value if value else _UNKNOWN
