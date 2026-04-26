# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Repo discovery helpers for the Generate sub-wizard §1 picker.

Pure logic — no ``questionary``, no ``rich``. Import-safe from tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pathspec
import platformdirs

# Directories that are never considered git repositories regardless of their
# contents. The list covers standard package-manager artefacts, virtual envs,
# build outputs, and common IDE / tool caches.
_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        "target",
        ".tox",
        ".idea",
        ".vscode",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)


def _load_gitignore_spec(cwd: Path) -> pathspec.PathSpec | None:
    """Parse ``cwd/.gitignore`` with gitwildmatch semantics.

    Returns ``None`` when the file is absent or unreadable — callers treat
    ``None`` as "no patterns, accept everything".
    """
    gitignore = cwd / ".gitignore"
    if not gitignore.is_file():
        return None
    try:
        lines = gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    return pathspec.PathSpec.from_lines("gitignore", lines)


def discover_git_repos(
    cwd: Path,
    *,
    max_depth: int = 1,
    cap: int = 20,
) -> list[Path]:
    """Return direct sub-directories of *cwd* that contain a ``.git`` folder.

    The search is intentionally shallow (``max_depth=1``) to keep the UI
    response instant even on large file-system trees.

    Filtering (applied in this order):
    1. Skip entries whose name is in ``_IGNORED_DIRS``.
    2. Skip entries matched by ``cwd/.gitignore`` (pathspec gitwildmatch).
    3. Keep only entries that have a ``.git`` subdirectory.

    Results are sorted by the mtime of ``<repo>/.git/HEAD`` (newest first)
    and capped at *cap* entries so the picker list stays manageable.

    Args:
        cwd: Root directory to scan.
        max_depth: Reserved for future use; only depth-1 is implemented.
        cap: Maximum number of results to return.

    Returns:
        List of ``Path`` objects (absolute, pointing at the repo root).
    """
    spec = _load_gitignore_spec(cwd)
    candidates: list[Path] = []

    try:
        entries = list(cwd.iterdir())
    except OSError:
        return []

    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name in _IGNORED_DIRS:
            continue
        # Check .gitignore — pathspec matches relative names/paths.
        if spec is not None and spec.match_file(entry.name):
            continue
        # Also try with trailing slash for directory patterns (e.g. "vendor/")
        if spec is not None and spec.match_file(entry.name + "/"):
            continue
        git_dir = entry / ".git"
        if not git_dir.exists():
            continue
        candidates.append(entry)

    # Sort by .git/HEAD mtime, newest first; fall back to 0 on OSError.
    def _head_mtime(p: Path) -> float:
        try:
            return (p / ".git" / "HEAD").stat().st_mtime
        except OSError:
            return 0.0

    candidates.sort(key=_head_mtime, reverse=True)
    return candidates[:cap]


def _recent_runs_path() -> Path:
    """Return the path to the shared recent-runs JSON file."""
    return Path(platformdirs.user_cache_dir("wiedunflow")) / "recent-runs.json"


def load_recent_runs(*, limit: int = 10) -> list[Path]:
    """Return the last *limit* repo paths from the recent-runs history.

    Reads ``~/.cache/wiedunflow/recent-runs.json`` (written by
    ``menu._append_to_recent_runs``).  Each entry may use key ``"repo_path"``
    or, for legacy compatibility, ``"repo"``.

    Returns an empty list on any read/parse error or when no history exists.

    Args:
        limit: Maximum number of paths to return.

    Returns:
        Ordered list of ``Path`` objects (newest first), deduplicated,
        stripped to *limit*.
    """
    path = _recent_runs_path()
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []

    seen: set[str] = set()
    result: list[Path] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        repo_str = entry.get("repo_path") or entry.get("repo") or ""
        if not repo_str or not isinstance(repo_str, str):
            continue
        if repo_str in seen:
            continue
        seen.add(repo_str)
        result.append(Path(repo_str))
        if len(result) >= limit:
            break

    return result


__all__ = [
    "_IGNORED_DIRS",
    "discover_git_repos",
    "load_recent_runs",
]
