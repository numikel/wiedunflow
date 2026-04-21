# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Cache key construction — pure functions, zero I/O.

All keys are stable SHA-256 hex digests over null-delimited fields.
The model name is deliberately excluded from the cache key: a user who
switches from Opus to Sonnet must supply ``--regenerate-plan`` explicitly.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


def build_cache_key(repo_abs: Path, commit: str, lesson_id: str) -> str:
    """Return SHA-256 hex digest keyed by *repo_abs*, *commit*, and *lesson_id*.

    Args:
        repo_abs: Absolute path to the repository root.  Resolved before hashing
            so relative paths produce the same key as their absolute equivalents.
        commit: Full or short commit hash that identifies the current tree state.
        lesson_id: Stable identifier for a specific lesson (e.g. ``"lesson-003"``).

    Returns:
        64-character lowercase hex SHA-256 digest.
    """
    payload = f"{repo_abs.resolve()}\x00{commit}\x00{lesson_id}".encode()
    return sha256(payload).hexdigest()


def build_plan_key(repo_abs: Path, commit: str) -> str:
    """Return SHA-256 hex digest for the lesson-manifest (plan) cache slot.

    Uses the same namespace as :func:`build_cache_key` but with the sentinel
    ``__plan__`` as the lesson-id component so the key is clearly distinct from
    any real lesson entry.

    Args:
        repo_abs: Absolute path to the repository root.
        commit: Full or short commit hash.

    Returns:
        64-character lowercase hex SHA-256 digest.
    """
    payload = f"{repo_abs.resolve()}\x00{commit}\x00__plan__".encode()
    return sha256(payload).hexdigest()


def build_file_key(file_bytes: bytes) -> str:
    """Return SHA-256 hex digest of raw *file_bytes*.

    Used as the primary key for the ``file_cache`` table — one row per unique
    file content, enabling content-addressed reuse independent of file path.

    Args:
        file_bytes: Raw bytes of the source file.

    Returns:
        64-character lowercase hex SHA-256 digest.
    """
    return sha256(file_bytes).hexdigest()
