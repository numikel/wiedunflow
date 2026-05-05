# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for adapters/yaml_consent_store.py — YamlConsentStore (US-007)."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from wiedunflow.adapters.yaml_consent_store import YamlConsentStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> YamlConsentStore:
    """Return a YamlConsentStore backed by a temp directory."""
    return YamlConsentStore(path=tmp_path / "consent.yaml")


@pytest.fixture()
def store_path(tmp_path: Path) -> Path:
    """Return the consent.yaml path used by the store fixture."""
    return tmp_path / "consent.yaml"


# ---------------------------------------------------------------------------
# 1. is_granted — missing file / empty store
# ---------------------------------------------------------------------------


def test_is_granted_returns_false_on_missing_file(store: YamlConsentStore) -> None:
    """is_granted must return False when the consent file does not exist."""
    assert store.is_granted("anthropic") is False


def test_is_granted_returns_false_for_unknown_provider(store: YamlConsentStore) -> None:
    """is_granted returns False for a provider that has never been granted."""
    store.grant("openai", datetime.now(UTC))
    assert store.is_granted("anthropic") is False


# ---------------------------------------------------------------------------
# 2. grant + is_granted persistence
# ---------------------------------------------------------------------------


def test_grant_persists_across_instances(tmp_path: Path) -> None:
    """grant() must persist so a new YamlConsentStore instance sees it."""
    path = tmp_path / "consent.yaml"
    store_a = YamlConsentStore(path=path)
    store_a.grant("anthropic", datetime.now(UTC))

    # Create a NEW instance pointing at the same file.
    store_b = YamlConsentStore(path=path)
    assert store_b.is_granted("anthropic") is True


def test_grant_records_timestamp(tmp_path: Path) -> None:
    """grant() must write granted_at as an ISO-8601 timestamp."""
    path = tmp_path / "consent.yaml"
    ts = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
    store = YamlConsentStore(path=path)
    store.grant("anthropic", ts)

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["anthropic"]["granted"] is True
    assert "2026-04-22" in data["anthropic"]["granted_at"]


def test_grant_multiple_providers(tmp_path: Path) -> None:
    """Multiple provider grants coexist in the same file."""
    path = tmp_path / "consent.yaml"
    store = YamlConsentStore(path=path)
    store.grant("anthropic", datetime.now(UTC))
    store.grant("openai", datetime.now(UTC))

    assert store.is_granted("anthropic") is True
    assert store.is_granted("openai") is True


# ---------------------------------------------------------------------------
# 3. revoke
# ---------------------------------------------------------------------------


def test_revoke_removes_provider(tmp_path: Path) -> None:
    """revoke() must remove the provider entry so is_granted returns False."""
    path = tmp_path / "consent.yaml"
    store = YamlConsentStore(path=path)
    store.grant("anthropic", datetime.now(UTC))
    assert store.is_granted("anthropic") is True

    store.revoke("anthropic")
    assert store.is_granted("anthropic") is False


def test_revoke_noop_for_absent_provider(store: YamlConsentStore) -> None:
    """revoke() on a never-granted provider must not raise."""
    store.revoke("unknown_provider")  # should not raise
    assert store.is_granted("unknown_provider") is False


def test_revoke_leaves_other_providers(tmp_path: Path) -> None:
    """revoke() must only remove the specified provider."""
    path = tmp_path / "consent.yaml"
    store = YamlConsentStore(path=path)
    store.grant("anthropic", datetime.now(UTC))
    store.grant("openai", datetime.now(UTC))

    store.revoke("anthropic")
    assert store.is_granted("anthropic") is False
    assert store.is_granted("openai") is True


# ---------------------------------------------------------------------------
# 4. File permissions (POSIX-only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="chmod semantics differ on Windows")
def test_yaml_file_permissions_0600_on_unix(tmp_path: Path) -> None:
    """consent.yaml must have 0o600 permissions after grant() on POSIX."""
    path = tmp_path / "consent.yaml"
    store = YamlConsentStore(path=path)
    store.grant("anthropic", datetime.now(UTC))

    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


@pytest.mark.skipif(sys.platform == "win32", reason="chmod semantics differ on Windows")
def test_yaml_file_permissions_0600_after_revoke(tmp_path: Path) -> None:
    """consent.yaml must still have 0o600 after revoke() on POSIX."""
    path = tmp_path / "consent.yaml"
    store = YamlConsentStore(path=path)
    store.grant("anthropic", datetime.now(UTC))
    store.revoke("anthropic")

    mode = os.stat(path).st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


# ---------------------------------------------------------------------------
# 5. Graceful handling of corrupt / empty file
# ---------------------------------------------------------------------------


def test_handles_empty_file_gracefully(tmp_path: Path) -> None:
    """An empty consent.yaml must not raise — is_granted returns False."""
    path = tmp_path / "consent.yaml"
    path.write_text("", encoding="utf-8")
    store = YamlConsentStore(path=path)
    assert store.is_granted("anthropic") is False


def test_handles_non_dict_file_gracefully(tmp_path: Path) -> None:
    """A non-dict YAML (e.g. plain string) must not raise."""
    path = tmp_path / "consent.yaml"
    path.write_text("just a string\n", encoding="utf-8")
    store = YamlConsentStore(path=path)
    assert store.is_granted("anthropic") is False


# ---------------------------------------------------------------------------
# 6. Parent directory creation
# ---------------------------------------------------------------------------


def test_creates_parent_directories(tmp_path: Path) -> None:
    """YamlConsentStore must create parent directories on grant()."""
    path = tmp_path / "deeply" / "nested" / "consent.yaml"
    store = YamlConsentStore(path=path)
    store.grant("anthropic", datetime.now(UTC))
    assert path.exists()


# ---------------------------------------------------------------------------
# 7. Windows-specific ACL warning
# ---------------------------------------------------------------------------


def test_windows_warning_emitted_once_per_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """On Windows, the visibility notice is printed once per process even
    across multiple grant() calls."""
    monkeypatch.setattr("sys.platform", "win32")
    store = YamlConsentStore(path=tmp_path / "consent.yaml")
    store.grant("openai", datetime.now())
    store.grant("anthropic", datetime.now())  # second grant on same instance
    captured = capsys.readouterr()
    assert captured.err.count("[wiedunflow] consent.yaml") == 1
    assert "Windows ACL" in captured.err
    assert (tmp_path / "consent.yaml").exists()


def test_no_windows_warning_on_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """POSIX path emits no Windows-specific stderr noise."""
    monkeypatch.setattr("sys.platform", "linux")
    store = YamlConsentStore(path=tmp_path / "consent.yaml")
    store.grant("openai", datetime.now())
    captured = capsys.readouterr()
    assert "[wiedunflow]" not in captured.err
