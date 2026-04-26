# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for ingestion/secret_blocklist.py — hard-refuse pattern matching (US-008)."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiedunflow.ingestion.secret_blocklist import HARD_REFUSE_PATTERNS, is_hard_refused

# ---------------------------------------------------------------------------
# Parametrized: files that MUST be refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        ".env",
        ".env.local",
        ".env.production",
        ".env.staging",
        "deploy.pem",
        "server.pem",
        "id_rsa",
        "id_ed25519",
        "myapp_rsa",
        "myapp_rsa.pub",
        "backup_rsa",
        "credentials.json",
        "credentials.yaml",
        "credentials.env",
        "host_ed25519",
    ],
)
def test_hard_refused_patterns_reject(filename: str) -> None:
    """Files matching HARD_REFUSE_PATTERNS must return True."""
    assert is_hard_refused(Path(filename)) is True, (
        f"{filename!r} should be hard-refused but is_hard_refused returned False"
    )


# ---------------------------------------------------------------------------
# Parametrized: benign files that must NOT be refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "hello.py",
        "README.md",
        "main.py",
        "config.py",
        "settings.py",
        "requirements.txt",
        "pyproject.toml",
        ".env.example",  # benign without allow_list — NOT matched: .env.* matches it... see below
    ],
)
def test_benign_files_not_refused(filename: str) -> None:
    """Benign filenames must not be hard-refused (empty allow_list)."""
    # Note: .env.example IS matched by .env.* pattern; tested separately.
    if filename == ".env.example":
        # .env.* matches .env.example — skip this case here; covered in allow_list tests.
        pytest.skip(".env.example is matched by .env.* — tested in allow_list section")
    assert is_hard_refused(Path(filename)) is False, f"{filename!r} should NOT be hard-refused"


@pytest.mark.parametrize(
    "filename",
    [
        "hello.py",
        "README.md",
        "main.py",
        "config.py",
        "settings.py",
        "requirements.txt",
        "pyproject.toml",
    ],
)
def test_benign_files_not_refused_parametrized(filename: str) -> None:
    """Non-secret filenames must pass the hard-refuse check."""
    assert is_hard_refused(Path(filename)) is False


# ---------------------------------------------------------------------------
# Allow-list: exact filename in allow_list overrides blocklist
# ---------------------------------------------------------------------------


def test_allow_list_exempts_dotenv_example() -> None:
    """.env.example in allow_list must NOT be refused."""
    assert is_hard_refused(Path(".env.example"), allow_list=frozenset({".env.example"})) is False


def test_allow_list_narrow_match_still_blocks() -> None:
    """.env.example with allow_list={'.env'} (different name) must still be refused."""
    assert is_hard_refused(Path(".env.example"), allow_list=frozenset({".env"})) is True


def test_allow_list_does_not_affect_other_patterns() -> None:
    """Allow-list for .env.example does not exempt id_rsa."""
    assert is_hard_refused(Path("id_rsa"), allow_list=frozenset({".env.example"})) is True


def test_allow_list_empty_default() -> None:
    """Default allow_list is frozenset() — no exemptions."""
    assert is_hard_refused(Path(".env")) is True


def test_allow_list_exact_match_only() -> None:
    """Allow-list uses exact name matching, not glob matching."""
    # ".env.*" in allow_list does NOT exempt .env.local (exact only, not pattern)
    assert is_hard_refused(Path(".env.local"), allow_list=frozenset({".env.*"})) is True


# ---------------------------------------------------------------------------
# HARD_REFUSE_PATTERNS tuple integrity
# ---------------------------------------------------------------------------


def test_hard_refuse_patterns_is_tuple() -> None:
    """HARD_REFUSE_PATTERNS must be a tuple (immutable)."""
    assert isinstance(HARD_REFUSE_PATTERNS, tuple)


def test_hard_refuse_patterns_has_expected_count() -> None:
    """HARD_REFUSE_PATTERNS must contain at least 9 entries."""
    assert len(HARD_REFUSE_PATTERNS) >= 9


# ---------------------------------------------------------------------------
# Path objects with subdirectory components — only name is checked
# ---------------------------------------------------------------------------


def test_path_with_directory_prefix() -> None:
    """Path subdirectory parts are ignored — only the file name is matched."""
    assert is_hard_refused(Path("some/nested/dir/.env")) is True


def test_path_with_directory_prefix_benign() -> None:
    """Benign file in nested dir is not refused."""
    assert is_hard_refused(Path("some/nested/dir/main.py")) is False
