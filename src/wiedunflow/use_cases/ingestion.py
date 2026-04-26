# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Ingestion use case — Stage 1 of the CodeGuide pipeline.

Discovers Python source files in a repository, respecting ``.gitignore`` and
user-supplied exclude/include patterns, detects monorepo sub-trees, and
resolves git context (commit hash + branch).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pathspec

from codeguide.adapters.git_context import get_git_context
from codeguide.entities.ingestion_result import IngestionResult
from codeguide.ingestion.file_filter import should_include_file

logger = logging.getLogger(__name__)

# Directories that are always skipped regardless of .gitignore patterns.
_ALWAYS_SKIP_PARTS: frozenset[str] = frozenset({"__pycache__"})


def ingest(
    repo_path: Path,
    excludes: tuple[str, ...] = (),
    includes: tuple[str, ...] = (),
    root_override: Path | None = None,
    security_allow_secret_files: frozenset[str] = frozenset(),
) -> IngestionResult:
    """Stage 1: discover Python source files and resolve git context.

    Builds a combined pathspec from the repository's ``.gitignore`` (if present)
    plus any *excludes* supplied by the caller.  *includes* patterns are prepended
    with ``!`` to negate exclusions (gitignore ``!pattern`` semantics), allowing
    callers to un-ignore specific paths.

    Hidden directories (those whose name starts with ``"."``) and ``__pycache__``
    are always skipped, even if not listed in ``.gitignore``.

    Monorepo detection: if *repo_path* contains no ``pyproject.toml`` /
    ``setup.py`` at the root but one exists in exactly one sub-directory that
    has no parent ``pyproject.toml`` within *repo_path*, that sub-directory is
    set as ``detected_subtree``.  ``root_override`` takes precedence over
    monorepo detection and sets ``repo_root`` directly with
    ``detected_subtree = None``.

    Args:
        repo_path: Absolute path to the Git repository root.
        excludes: Additional gitignore-style patterns to exclude (additive over
            ``.gitignore``).
        includes: Patterns to un-ignore despite ``.gitignore`` or *excludes*
            (prepended with ``!`` before the spec).
        root_override: Explicit repo root override (monorepo subtree).  When
            set, ``repo_root`` is this path and ``detected_subtree`` is ``None``.
        security_allow_secret_files: Exact file names that override the
            hard-refuse secret blocklist (from
            ``CodeguideConfig.security_allow_secret_files``).

    Returns:
        A populated :class:`~codeguide.entities.ingestion_result.IngestionResult`.
    """
    repo_root = root_override if root_override is not None else repo_path

    spec = _build_spec(repo_root, excludes, includes)
    files, excluded_count = _collect_files(repo_root, spec, allow_list=security_allow_secret_files)

    commit_hash, branch = get_git_context(repo_root)

    detected_subtree: Path | None = None
    if root_override is None:
        detected_subtree = _detect_subtree(repo_path)

    has_readme = (
        (repo_root / "README.md").exists()
        or (repo_root / "README.rst").exists()
        or (repo_root / "README.txt").exists()
        or (repo_root / "README").exists()
    )

    return IngestionResult(
        files=tuple(sorted(files)),
        repo_root=repo_root,
        commit_hash=commit_hash,
        branch=branch,
        detected_subtree=detected_subtree,
        excluded_count=excluded_count,
        has_readme=has_readme,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_spec(
    repo_root: Path,
    excludes: tuple[str, ...],
    includes: tuple[str, ...],
) -> pathspec.GitIgnoreSpec:
    """Build a combined :class:`pathspec.GitIgnoreSpec` for the repository.

    Pattern precedence (last-match wins, as in git):
    1. ``.gitignore`` lines (if the file exists)
    2. *includes* as negation patterns (``!pattern``)
    3. *excludes* (plain patterns, most specific overrides)

    Args:
        repo_root: Repository root used to locate ``.gitignore``.
        excludes: Extra patterns to exclude.
        includes: Patterns to un-ignore (converted to ``!pattern`` form).

    Returns:
        A :class:`pathspec.GitIgnoreSpec` combining all pattern sources.
    """
    lines: list[str] = []

    gitignore = repo_root / ".gitignore"
    if gitignore.is_file():
        lines.extend(gitignore.read_text(encoding="utf-8", errors="replace").splitlines())

    # Negation patterns must come before the extra excludes so that excludes
    # can still override them if the caller passes both for the same path.
    for pattern in includes:
        negated = pattern if pattern.startswith("!") else f"!{pattern}"
        lines.append(negated)

    lines.extend(excludes)

    return pathspec.GitIgnoreSpec.from_lines(lines)


def _should_skip_path(path: Path) -> bool:
    """Return ``True`` if *path* contains a dotted directory or ``__pycache__``."""
    return any(part.startswith(".") or part in _ALWAYS_SKIP_PARTS for part in path.parts)


def _collect_files(
    repo_root: Path,
    spec: pathspec.GitIgnoreSpec,
    *,
    allow_list: frozenset[str] = frozenset(),
) -> tuple[list[Path], int]:
    """Walk *repo_root* and collect ``.py`` files that pass all filter gates.

    Gates applied in order:
    1. Always-skip (dotted directories, ``__pycache__``).
    2. Hard-refuse secret blocklist (``ingestion/file_filter.py``).
    3. Pathspec filter (``.gitignore`` + excludes/includes).

    Args:
        repo_root: Directory to walk.
        spec: Combined gitignore spec (files that *match* are excluded).
        allow_list: Exact file names exempted from the hard-refuse blocklist.

    Returns:
        Tuple of ``(kept_files, excluded_count)`` where *kept_files* is a list
        of absolute :class:`Path` objects and *excluded_count* is the number of
        files that were excluded by any gate.
    """
    kept: list[Path] = []
    excluded = 0

    for abs_path in repo_root.rglob("*"):
        if not abs_path.is_file():
            continue
        rel = abs_path.relative_to(repo_root)

        # Always-skip rules (dotted dirs, __pycache__) — checked on relative parts.
        if _should_skip_path(rel):
            excluded += 1
            continue

        # Combine hard-refuse + pathspec via should_include_file.
        if not should_include_file(abs_path, rel, spec, allow_list=allow_list):
            excluded += 1
            continue

        # Only collect Python source files.
        if abs_path.suffix != ".py":
            continue

        kept.append(abs_path)

    return kept, excluded


def _detect_subtree(repo_path: Path) -> Path | None:
    """Return the detected monorepo sub-tree root, or ``None``.

    A monorepo sub-tree is detected when:
    - *repo_path* itself has no ``pyproject.toml`` **or** ``setup.py``, AND
    - exactly one immediate sub-directory contains either file.

    The heuristic is intentionally conservative: it only looks one level deep
    to avoid false positives in repos with multiple independent packages.

    Args:
        repo_path: Repository root to inspect.

    Returns:
        Absolute :class:`Path` to the detected sub-tree, or ``None``.
    """
    root_markers = {"pyproject.toml", "setup.py"}

    # If the root itself has a marker, no subtree detection needed.
    if any((repo_path / m).exists() for m in root_markers):
        return None

    candidates: list[Path] = []
    try:
        for child in repo_path.iterdir():
            if not child.is_dir():
                continue
            if child.name.startswith("."):
                continue
            if any((child / m).exists() for m in root_markers):
                candidates.append(child)
    except PermissionError:
        return None

    if len(candidates) == 1:
        return candidates[0]

    return None
