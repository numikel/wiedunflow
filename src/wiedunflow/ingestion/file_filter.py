# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""File filter helpers for the ingestion stage (US-008).

This module wraps the hard-refuse secret blocklist check used by
:func:`wiedunflow.use_cases.ingestion._collect_files` so tests can exercise
the blocking logic in isolation without running the full pipeline.

The authoritative integration point is ``use_cases/ingestion.py``; this module
re-exports :func:`~wiedunflow.ingestion.secret_blocklist.is_hard_refused` and
provides :func:`should_include_file` as a single "gate" function that combines
the hard-refuse check with ``pathspec`` filtering.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pathspec

from wiedunflow.ingestion.secret_blocklist import is_hard_refused

logger = logging.getLogger(__name__)

__all__ = ["is_hard_refused", "should_include_file"]


def should_include_file(
    abs_path: Path,
    rel: Path,
    spec: pathspec.GitIgnoreSpec,
    *,
    allow_list: frozenset[str] = frozenset(),
) -> bool:
    """Return ``True`` iff *abs_path* should be included in the ingestion result.

    Applies gates in order:
    1. Hard-refuse blocklist (highest priority — cannot be overridden by gitignore/include).
    2. Pathspec filter (``.gitignore`` + user excludes/includes).

    Args:
        abs_path: Absolute path to the file (used only for logging).
        rel: Relative path from repo root (used for spec matching and name extraction).
        spec: Combined gitignore spec — files that match are excluded.
        allow_list: Exact file names that override the hard-refuse blocklist.

    Returns:
        ``True`` when the file passes all gates; ``False`` when any gate rejects it.
    """
    # Gate 1: hard-refuse secret blocklist — always wins over gitignore/include.
    if is_hard_refused(rel, allow_list=allow_list):
        logger.debug("file_hard_refused path=%s", rel.name)
        return False

    # Gate 2: pathspec filter (gitignore + excludes/includes).
    return not spec.match_file(rel.as_posix())
