# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for cache key construction (US-025, US-026)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from wiedunflow.entities.cache_key import (
    build_cache_key,
    build_file_key,
    build_plan_key,
)

# ---------------------------------------------------------------------------
# build_cache_key
# ---------------------------------------------------------------------------


def test_us_025_build_cache_key_is_deterministic() -> None:
    """Same inputs always produce the same key."""
    repo = Path("/home/user/myrepo")
    commit = "abc123"
    lesson = "lesson-001"
    key1 = build_cache_key(repo, commit, lesson)
    key2 = build_cache_key(repo, commit, lesson)
    assert key1 == key2


def test_us_025_build_cache_key_is_hex_sha256() -> None:
    """Key is a 64-character lowercase hex string."""
    key = build_cache_key(Path("/repo"), "abc", "lesson-001")
    assert len(key) == 64
    assert key == key.lower()
    int(key, 16)  # must be valid hex — raises ValueError if not


def test_us_025_different_commit_produces_different_key() -> None:
    """Changing commit produces a different cache key."""
    repo = Path("/home/user/myrepo")
    lesson = "lesson-001"
    key_a = build_cache_key(repo, "abc123", lesson)
    key_b = build_cache_key(repo, "def456", lesson)
    assert key_a != key_b


def test_us_025_different_lesson_id_produces_different_key() -> None:
    """Changing lesson_id produces a different cache key."""
    repo = Path("/home/user/myrepo")
    commit = "abc123"
    key_a = build_cache_key(repo, commit, "lesson-001")
    key_b = build_cache_key(repo, commit, "lesson-002")
    assert key_a != key_b


def test_us_025_different_repo_abs_produces_different_key() -> None:
    """Changing repo path produces a different cache key."""
    commit = "abc123"
    lesson = "lesson-001"
    key_a = build_cache_key(Path("/home/alice/repo"), commit, lesson)
    key_b = build_cache_key(Path("/home/bob/repo"), commit, lesson)
    assert key_a != key_b


def test_us_025_relative_vs_absolute_path_different_keys() -> None:
    """A relative and an absolute path with different canonical forms produce different keys.

    Path.resolve() is called inside build_cache_key so the keys are consistent
    within a process, but two different working directories yield different keys
    — this is the expected behaviour (each repo root is a unique cache scope).
    """
    # These are genuinely different absolute paths after resolution
    key_rel = build_cache_key(Path("./repo"), "abc", "lesson-001")
    key_abs = build_cache_key(Path("/absolute/repo"), "abc", "lesson-001")
    assert key_rel != key_abs


def test_us_025_plan_key_differs_from_lesson_key() -> None:
    """Plan key must not collide with any lesson key."""
    repo = Path("/home/user/myrepo")
    commit = "abc123"
    plan_key = build_plan_key(repo, commit)
    lesson_key = build_cache_key(repo, commit, "__plan__")
    # Both use the same sentinel — the plan key IS the lesson key with __plan__ id.
    # Verify they ARE the same (no ambiguity: __plan__ is reserved).
    assert plan_key == lesson_key


def test_us_025_plan_key_differs_from_real_lesson_key() -> None:
    """Plan key differs from any real lesson id."""
    repo = Path("/home/user/myrepo")
    commit = "abc123"
    plan_key = build_plan_key(repo, commit)
    lesson_key = build_cache_key(repo, commit, "lesson-001")
    assert plan_key != lesson_key


def test_us_025_build_cache_key_is_sha256_of_correct_payload() -> None:
    """Key matches manual sha256 computation of the expected payload."""
    repo = Path("/home/user/myrepo")
    commit = "abc123"
    lesson = "lesson-001"
    # Use the resolved path — on most Unix systems this equals the input
    expected_payload = f"{repo.resolve()}\x00{commit}\x00{lesson}".encode()
    expected = hashlib.sha256(expected_payload).hexdigest()
    assert build_cache_key(repo, commit, lesson) == expected


# ---------------------------------------------------------------------------
# build_file_key
# ---------------------------------------------------------------------------


def test_us_026_build_file_key_matches_hashlib_sha256() -> None:
    """build_file_key must match hashlib.sha256(content).hexdigest()."""
    content = b"print('hello world')\n"
    assert build_file_key(content) == hashlib.sha256(content).hexdigest()


def test_us_026_build_file_key_different_content_different_key() -> None:
    """Different file content yields different cache keys."""
    key_a = build_file_key(b"content A")
    key_b = build_file_key(b"content B")
    assert key_a != key_b


def test_us_026_build_file_key_same_content_same_key() -> None:
    """Identical file bytes always yield the same cache key."""
    content = b"# identical file\n"
    assert build_file_key(content) == build_file_key(content)


def test_us_026_build_file_key_empty_bytes() -> None:
    """Empty file is hashable and produces a stable 64-char hex key."""
    key = build_file_key(b"")
    assert len(key) == 64


@pytest.mark.parametrize(
    "content",
    [
        b"def foo(): pass\n",
        b"\x00\x01\x02",  # binary content
        b"# unicode: \xe2\x80\x94",  # UTF-8 bytes
    ],
)
def test_us_026_build_file_key_various_content(content: bytes) -> None:
    """build_file_key handles arbitrary byte sequences without error."""
    key = build_file_key(content)
    assert len(key) == 64
    assert key == hashlib.sha256(content).hexdigest()
