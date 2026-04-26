# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for ``wiedunflow.cli.picker_sources`` — discovery & cache helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from wiedunflow.cli.picker_sources import discover_git_repos, load_recent_runs

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_git_repo(path: Path) -> Path:
    """Create a minimal fake git repo at *path* (creates .git/HEAD)."""
    path.mkdir(parents=True, exist_ok=True)
    git_dir = path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# discover_git_repos
# ---------------------------------------------------------------------------


def test_discover_max_depth_one_finds_direct_only(tmp_path: Path) -> None:
    """Only depth-1 subdirectories with .git/ should be returned."""
    # Depth 1: should be found
    _make_git_repo(tmp_path / "a")
    # Depth 2: should NOT be found
    _make_git_repo(tmp_path / "a" / "b")

    result = discover_git_repos(tmp_path)

    names = {p.name for p in result}
    assert "a" in names
    assert "b" not in names


def test_discover_skips_hardcoded_ignored(tmp_path: Path) -> None:
    """node_modules, .venv etc. must never appear in results."""
    _make_git_repo(tmp_path / "node_modules")
    _make_git_repo(tmp_path / ".venv")

    result = discover_git_repos(tmp_path)

    assert result == []


def test_discover_honors_root_gitignore(tmp_path: Path) -> None:
    """Directories matched by cwd/.gitignore should be excluded."""
    (tmp_path / ".gitignore").write_text("vendor/\n", encoding="utf-8")
    _make_git_repo(tmp_path / "vendor")
    _make_git_repo(tmp_path / "myrepo")

    result = discover_git_repos(tmp_path)

    names = {p.name for p in result}
    assert "vendor" not in names
    assert "myrepo" in names


def test_discover_no_gitignore_silent_ok(tmp_path: Path) -> None:
    """When .gitignore is absent the function must not raise."""
    _make_git_repo(tmp_path / "repo1")

    result = discover_git_repos(tmp_path)

    assert len(result) == 1
    assert result[0].name == "repo1"


def test_discover_caps_at_20(tmp_path: Path) -> None:
    """Results must be capped at the default cap of 20."""
    for i in range(25):
        _make_git_repo(tmp_path / f"repo_{i:02d}")

    result = discover_git_repos(tmp_path)

    assert len(result) == 20


def test_discover_sorts_mtime_desc(tmp_path: Path) -> None:
    """Repos should be ordered by .git/HEAD mtime, newest first."""
    repo_a = _make_git_repo(tmp_path / "repo_a")
    repo_b = _make_git_repo(tmp_path / "repo_b")
    repo_c = _make_git_repo(tmp_path / "repo_c")

    # Set ascending mtimes: a=100, b=200, c=300 — expect c, b, a order.
    base = 1_700_000_000
    os.utime(repo_a / ".git" / "HEAD", (base + 100, base + 100))
    os.utime(repo_b / ".git" / "HEAD", (base + 200, base + 200))
    os.utime(repo_c / ".git" / "HEAD", (base + 300, base + 300))

    result = discover_git_repos(tmp_path)

    assert [p.name for p in result] == ["repo_c", "repo_b", "repo_a"]


# ---------------------------------------------------------------------------
# load_recent_runs
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_recent_runs_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``load_recent_runs`` to use a temp file."""
    fake_path = tmp_path / "recent-runs.json"
    monkeypatch.setattr(
        "wiedunflow.cli.picker_sources._recent_runs_path",
        lambda: fake_path,
    )
    return fake_path


def test_load_recent_runs_returns_paths(_mock_recent_runs_path: Path) -> None:
    """Happy path: entries with 'repo_path' key are returned as Path objects."""
    data = [
        {"repo_path": "/home/user/repo1", "status": "success"},
        {"repo_path": "/home/user/repo2", "status": "success"},
    ]
    _mock_recent_runs_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_recent_runs(limit=10)

    assert result == [Path("/home/user/repo1"), Path("/home/user/repo2")]


def test_load_recent_runs_missing_file_returns_empty(_mock_recent_runs_path: Path) -> None:
    """When the file doesn't exist, return an empty list."""
    # _mock_recent_runs_path is not written → file absent
    result = load_recent_runs()
    assert result == []


def test_load_recent_runs_malformed_json_returns_empty(_mock_recent_runs_path: Path) -> None:
    _mock_recent_runs_path.write_text("not-json!!", encoding="utf-8")
    assert load_recent_runs() == []


def test_load_recent_runs_respects_limit(_mock_recent_runs_path: Path) -> None:
    data = [{"repo_path": f"/repo/{i}"} for i in range(20)]
    _mock_recent_runs_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_recent_runs(limit=5)

    assert len(result) == 5


def test_load_recent_runs_deduplicates(_mock_recent_runs_path: Path) -> None:
    """Duplicate repo_path values should appear only once (first occurrence)."""
    data = [
        {"repo_path": "/repo/a"},
        {"repo_path": "/repo/b"},
        {"repo_path": "/repo/a"},  # duplicate
    ]
    _mock_recent_runs_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_recent_runs(limit=10)

    assert result == [Path("/repo/a"), Path("/repo/b")]


def test_load_recent_runs_non_list_json_returns_empty(_mock_recent_runs_path: Path) -> None:
    """JSON that is valid but not a list → empty result."""
    _mock_recent_runs_path.write_text(json.dumps({"key": "value"}), encoding="utf-8")
    assert load_recent_runs() == []


def test_load_recent_runs_skips_non_dict_entries(_mock_recent_runs_path: Path) -> None:
    """Non-dict items inside the list are silently skipped."""
    data: list[object] = ["not-a-dict", {"repo_path": "/repo/ok"}, 42]
    _mock_recent_runs_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_recent_runs(limit=10)

    assert result == [Path("/repo/ok")]


def test_load_recent_runs_skips_empty_repo_path(_mock_recent_runs_path: Path) -> None:
    """Entries with empty or missing repo_path are silently skipped."""
    data = [
        {"repo_path": ""},
        {"repo_path": "/repo/valid"},
        {"status": "success"},  # no repo_path key at all
    ]
    _mock_recent_runs_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_recent_runs(limit=10)

    assert result == [Path("/repo/valid")]


def test_load_recent_runs_legacy_repo_key(_mock_recent_runs_path: Path) -> None:
    """Entries using legacy 'repo' key (instead of 'repo_path') are accepted."""
    data = [{"repo": "/legacy/path"}]
    _mock_recent_runs_path.write_text(json.dumps(data), encoding="utf-8")

    result = load_recent_runs(limit=10)

    assert result == [Path("/legacy/path")]


# ---------------------------------------------------------------------------
# discover_git_repos — additional edge-case coverage
# ---------------------------------------------------------------------------


def test_discover_skips_non_git_directories(tmp_path: Path) -> None:
    """Plain directories without .git/ are excluded."""
    plain = tmp_path / "notarepo"
    plain.mkdir()

    result = discover_git_repos(tmp_path)

    assert result == []


def test_discover_gitignore_name_without_slash(tmp_path: Path) -> None:
    """Patterns without trailing slash (e.g. 'vendor') also filter directories."""
    (tmp_path / ".gitignore").write_text("vendor\n", encoding="utf-8")
    _make_git_repo(tmp_path / "vendor")
    _make_git_repo(tmp_path / "keep")

    result = discover_git_repos(tmp_path)

    names = {p.name for p in result}
    assert "vendor" not in names
    assert "keep" in names


def test_discover_oserror_on_iterdir_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """OSError from cwd.iterdir() must return empty list, not propagate."""
    import wiedunflow.cli.picker_sources as ps

    original_iterdir = Path.iterdir

    def _bad_iterdir(self: Path) -> object:
        if self == tmp_path:
            raise OSError("permission denied")
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _bad_iterdir)

    result = ps.discover_git_repos(tmp_path)

    assert result == []


def test_discover_oserror_on_gitignore_read_treated_as_no_spec(tmp_path: Path) -> None:
    """OSError reading .gitignore → treated as no spec (no crash, file skipped)."""
    # Create a .gitignore that exists but can't be read
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("vendor/\n", encoding="utf-8")
    _make_git_repo(tmp_path / "vendor")  # would be filtered if gitignore was readable
    _make_git_repo(tmp_path / "myrepo")

    import unittest.mock

    import wiedunflow.cli.picker_sources as ps

    # Patch read_text to raise OSError specifically for the gitignore file
    original_read_text = Path.read_text

    def _raising_read(self: Path, *args: object, **kwargs: object) -> str:
        if self == gitignore:
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    with unittest.mock.patch.object(Path, "read_text", _raising_read):
        result = ps.discover_git_repos(tmp_path)

    # Without gitignore spec, vendor is included
    names = {p.name for p in result}
    assert "myrepo" in names
    # vendor not in _IGNORED_DIRS, so it would appear when gitignore is unreadable
    assert "vendor" in names


def test_discover_head_mtime_oserror_falls_back_to_zero(tmp_path: Path) -> None:
    """OSError on .git/HEAD mtime falls back to 0 (repo still appears in results)."""
    repo = _make_git_repo(tmp_path / "broken-head")
    # Remove HEAD so stat() raises OSError → mtime = 0.0
    (repo / ".git" / "HEAD").unlink()

    result = discover_git_repos(tmp_path)

    # Repo still appears despite missing HEAD (mtime 0 = oldest).
    assert any(p.name == "broken-head" for p in result)


def test_recent_runs_path_uses_platformdirs() -> None:
    """_recent_runs_path() must return a Path under the wiedun-flow cache dir."""
    from wiedunflow.cli.picker_sources import _recent_runs_path

    path = _recent_runs_path()

    assert path.name == "recent-runs.json"
    assert "wiedun-flow" in str(path)
