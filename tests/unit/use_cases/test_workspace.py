# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from wiedunflow.use_cases.workspace import (
    _STALE_ALIVE_SECONDS,
    ALIVE_FILENAME,
    RunWorkspace,
    allocate_workspace,
    clean_old_runs,
    finalize_workspace,
    generate_run_id,
    touch_alive,
)

# ---------------------------------------------------------------------------
# generate_run_id
# ---------------------------------------------------------------------------


def test_generate_run_id_deterministic() -> None:
    id1 = generate_run_id("repo", "abc", "2026-05-01")
    id2 = generate_run_id("repo", "abc", "2026-05-01")
    assert id1 == id2


def test_generate_run_id_length() -> None:
    run_id = generate_run_id("/home/user/repo", "deadbeef", "2026-05-01T10:00:00Z")
    assert len(run_id) == 12


def test_generate_run_id_different_timestamps_differ() -> None:
    id1 = generate_run_id("repo", "sha1", "2026-05-01T09:00:00Z")
    id2 = generate_run_id("repo", "sha1", "2026-05-01T10:00:00Z")
    assert id1 != id2


def test_generate_run_id_different_repos_differ() -> None:
    id1 = generate_run_id("/repo/a", "sha", "2026-05-01")
    id2 = generate_run_id("/repo/b", "sha", "2026-05-01")
    assert id1 != id2


def test_generate_run_id_is_hex() -> None:
    run_id = generate_run_id("repo", "abc", "ts")
    assert all(c in "0123456789abcdef" for c in run_id)


# ---------------------------------------------------------------------------
# allocate_workspace
# ---------------------------------------------------------------------------


def test_allocate_workspace_creates_dirs(tmp_path: Path) -> None:
    allocate_workspace("abc123", base_dir=tmp_path)
    assert (tmp_path / "abc123").is_dir()


def test_allocate_workspace_returns_correct_run_id(tmp_path: Path) -> None:
    ws = allocate_workspace("myrun", base_dir=tmp_path)
    assert ws.run_id == "myrun"


def test_allocate_workspace_base_dir_matches(tmp_path: Path) -> None:
    ws = allocate_workspace("xyzrun", base_dir=tmp_path)
    assert ws.base_dir == tmp_path / "xyzrun"


def test_allocate_workspace_idempotent(tmp_path: Path) -> None:
    allocate_workspace("abc", base_dir=tmp_path)
    ws2 = allocate_workspace("abc", base_dir=tmp_path)
    assert ws2.base_dir.is_dir()


# ---------------------------------------------------------------------------
# RunWorkspace.lesson_dir / transcript_dir
# ---------------------------------------------------------------------------


def test_lesson_dir_creates_raw(tmp_path: Path) -> None:
    ws = allocate_workspace("run1", base_dir=tmp_path)
    d = ws.lesson_dir("lesson-001", "raw")
    assert d.is_dir()
    assert d == ws.base_dir / "raw" / "lesson-001"


def test_lesson_dir_creates_processing(tmp_path: Path) -> None:
    ws = allocate_workspace("run1", base_dir=tmp_path)
    d = ws.lesson_dir("lesson-002", "processing")
    assert d.is_dir()


def test_lesson_dir_creates_finished(tmp_path: Path) -> None:
    ws = allocate_workspace("run1", base_dir=tmp_path)
    d = ws.lesson_dir("lesson-003", "finished")
    assert d.is_dir()


def test_transcript_dir_creates_subdir(tmp_path: Path) -> None:
    ws = allocate_workspace("run1", base_dir=tmp_path)
    d = ws.transcript_dir("lesson-001")
    assert d.is_dir()
    assert d == ws.base_dir / "transcript" / "lesson-001"


# ---------------------------------------------------------------------------
# write_atomic / write_json_atomic / read_json
# ---------------------------------------------------------------------------


def test_write_atomic_creates_file(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    dest = ws.base_dir / "test.txt"
    ws.write_atomic(dest, "hello")
    assert dest.read_text(encoding="utf-8") == "hello"


def test_write_atomic_overwrites_existing(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    dest = ws.base_dir / "overwrite.txt"
    ws.write_atomic(dest, "first")
    ws.write_atomic(dest, "second")
    assert dest.read_text(encoding="utf-8") == "second"


def test_write_atomic_creates_parent_dirs(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    dest = ws.base_dir / "deep" / "nested" / "file.txt"
    ws.write_atomic(dest, "content")
    assert dest.read_text(encoding="utf-8") == "content"


def test_write_atomic_no_tmp_file_left(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    dest = ws.base_dir / "clean.txt"
    ws.write_atomic(dest, "data")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    assert not tmp.exists()


def test_write_json_atomic_valid_json(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    dest = ws.base_dir / "data.json"
    ws.write_json_atomic(dest, {"key": "value", "num": 42})
    import json

    parsed = json.loads(dest.read_text(encoding="utf-8"))
    assert parsed == {"key": "value", "num": 42}


def test_read_json_round_trip(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    dest = ws.base_dir / "round.json"
    data = {"lesson_id": "lesson-001", "words": 250}
    ws.write_json_atomic(dest, data)
    result = ws.read_json(dest)
    assert result == data


# ---------------------------------------------------------------------------
# is_finished / list_finished_lessons
# ---------------------------------------------------------------------------


def test_is_finished_false_before_write(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    assert not ws.is_finished("lesson-001")


def test_is_finished_true_after_write(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    dest = ws.lesson_dir("lesson-001", "finished") / "lesson.json"
    ws.write_json_atomic(dest, {"id": "lesson-001"})
    assert ws.is_finished("lesson-001")


def test_is_finished_requires_lesson_json(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    # Writing audit.json alone is not sufficient.
    d = ws.lesson_dir("lesson-001", "finished")
    ws.write_json_atomic(d / "audit.json", {})
    assert not ws.is_finished("lesson-001")


def test_list_finished_lessons_empty_before_any_write(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    assert ws.list_finished_lessons() == []


def test_list_finished_lessons(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    for lid in ["lesson-001", "lesson-002"]:
        d = ws.lesson_dir(lid, "finished")
        ws.write_json_atomic(d / "lesson.json", {})
    assert ws.list_finished_lessons() == ["lesson-001", "lesson-002"]


def test_list_finished_lessons_sorted(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    for lid in ["lesson-010", "lesson-002", "lesson-001"]:
        d = ws.lesson_dir(lid, "finished")
        ws.write_json_atomic(d / "lesson.json", {})
    assert ws.list_finished_lessons() == ["lesson-001", "lesson-002", "lesson-010"]


# ---------------------------------------------------------------------------
# Well-known path properties
# ---------------------------------------------------------------------------


def test_manifest_path(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    assert ws.manifest_path == ws.base_dir / "manifest.json"


def test_orchestrator_state_path(tmp_path: Path) -> None:
    ws = allocate_workspace("abc", base_dir=tmp_path)
    assert ws.orchestrator_state_path == ws.base_dir / "orchestrator-state.json"


# ---------------------------------------------------------------------------
# clean_old_runs
# ---------------------------------------------------------------------------


def test_clean_old_runs_returns_zero_when_base_missing(tmp_path: Path) -> None:
    missing = tmp_path / "no_such_dir"
    removed = clean_old_runs(base_dir=missing, max_age_days=7)
    assert removed == 0


def test_clean_old_runs_removes_stale(tmp_path: Path) -> None:
    run_dir = tmp_path / "old_run"
    run_dir.mkdir()
    # Force mtime to 8 days ago.
    old_mtime = time.time() - 8 * 86400
    os.utime(run_dir, (old_mtime, old_mtime))
    removed = clean_old_runs(base_dir=tmp_path, max_age_days=7)
    assert removed == 1
    assert not run_dir.exists()


def test_clean_old_runs_keeps_fresh(tmp_path: Path) -> None:
    run_dir = tmp_path / "fresh_run"
    run_dir.mkdir()
    # mtime defaults to now — should not be removed.
    removed = clean_old_runs(base_dir=tmp_path, max_age_days=7)
    assert removed == 0
    assert run_dir.exists()


def test_clean_old_runs_mixed(tmp_path: Path) -> None:
    old = tmp_path / "old"
    fresh = tmp_path / "fresh"
    old.mkdir()
    fresh.mkdir()
    old_mtime = time.time() - 10 * 86400
    os.utime(old, (old_mtime, old_mtime))
    removed = clean_old_runs(base_dir=tmp_path, max_age_days=7)
    assert removed == 1
    assert not old.exists()
    assert fresh.exists()


def test_clean_old_runs_returns_count(tmp_path: Path) -> None:
    for name in ["stale1", "stale2"]:
        d = tmp_path / name
        d.mkdir()
        old_mtime = time.time() - 20 * 86400
        os.utime(d, (old_mtime, old_mtime))
    removed = clean_old_runs(base_dir=tmp_path, max_age_days=7)
    assert removed == 2


# ---------------------------------------------------------------------------
# POSIX permission enforcement
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")
@pytest.mark.parametrize(
    "subdir_factory",
    [
        pytest.param(lambda ws: ws.base_dir, id="base_dir"),
        pytest.param(lambda ws: ws.lesson_dir("L1", "raw"), id="raw"),
        pytest.param(lambda ws: ws.lesson_dir("L1", "processing"), id="processing"),
        pytest.param(lambda ws: ws.lesson_dir("L1", "finished"), id="finished"),
        pytest.param(lambda ws: ws.transcript_dir("L1"), id="transcript"),
    ],
)
def test_workspace_dirs_are_user_only(
    tmp_path: Path, subdir_factory: Callable[[RunWorkspace], Path]
) -> None:
    """Workspace dirs must be 0o700 on POSIX (source excerpts + LLM transcripts)."""
    ws = allocate_workspace("test-run", base_dir=tmp_path)
    target = subdir_factory(ws)
    mode = os.stat(target).st_mode & 0o777
    assert mode == 0o700, f"Expected 0o700 for {target}, got {oct(mode)}"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission semantics")
def test_write_atomic_parent_dir_is_user_only(tmp_path: Path) -> None:
    """write_atomic must set 0o700 on any parent dir it creates."""
    ws = allocate_workspace("test-run", base_dir=tmp_path)
    nested = ws.base_dir / "deep" / "nested" / "file.txt"
    ws.write_atomic(nested, "content")
    mode = os.stat(nested.parent).st_mode & 0o777
    assert mode == 0o700, f"Expected 0o700 for {nested.parent}, got {oct(mode)}"


# ---------------------------------------------------------------------------
# .alive sentinel — concurrent-run safety for clean_old_runs
# ---------------------------------------------------------------------------


def test_allocate_workspace_creates_alive_sentinel(tmp_path: Path) -> None:
    """Every new workspace drops a ``.alive`` empty file at its root."""
    ws = allocate_workspace("run-id-x", base_dir=tmp_path)
    alive = ws.base_dir / ALIVE_FILENAME
    assert alive.exists()
    assert alive.is_file()
    assert alive.stat().st_size == 0


def test_allocate_workspace_refreshes_existing_sentinel(tmp_path: Path) -> None:
    """Re-allocating (resume) bumps the sentinel mtime so cleanup keeps it."""
    ws = allocate_workspace("run-id-x", base_dir=tmp_path)
    alive = ws.base_dir / ALIVE_FILENAME
    old_mtime = time.time() - 10 * 60  # 10 min ago
    os.utime(alive, (old_mtime, old_mtime))
    assert alive.stat().st_mtime == pytest.approx(old_mtime, abs=2.0)

    # Re-allocate same run id — mtime must be refreshed to ~now.
    allocate_workspace("run-id-x", base_dir=tmp_path)
    refreshed_mtime = alive.stat().st_mtime
    assert refreshed_mtime > old_mtime + 60


def test_touch_alive_refreshes_mtime(tmp_path: Path) -> None:
    """touch_alive bumps the sentinel mtime so the run stays "alive" for cleanup."""
    ws = allocate_workspace("run-id-x", base_dir=tmp_path)
    alive = ws.base_dir / ALIVE_FILENAME
    old_mtime = time.time() - 5 * 60
    os.utime(alive, (old_mtime, old_mtime))

    touch_alive(ws)
    assert alive.stat().st_mtime > old_mtime + 30


def test_touch_alive_recreates_missing_sentinel(tmp_path: Path) -> None:
    """If the sentinel was manually deleted, touch_alive re-creates it."""
    ws = allocate_workspace("run-id-x", base_dir=tmp_path)
    alive = ws.base_dir / ALIVE_FILENAME
    alive.unlink()
    assert not alive.exists()

    touch_alive(ws)
    assert alive.exists()


def test_finalize_workspace_removes_sentinel(tmp_path: Path) -> None:
    """finalize_workspace deletes the ``.alive`` marker on successful completion."""
    ws = allocate_workspace("run-id-x", base_dir=tmp_path)
    alive = ws.base_dir / ALIVE_FILENAME
    assert alive.exists()

    finalize_workspace(ws)
    assert not alive.exists()


def test_finalize_workspace_idempotent(tmp_path: Path) -> None:
    """finalize_workspace must be safe to call multiple times (and without prior allocate)."""
    ws = allocate_workspace("run-id-x", base_dir=tmp_path)
    finalize_workspace(ws)
    # Second call must not raise even though the sentinel is gone.
    finalize_workspace(ws)
    assert not (ws.base_dir / ALIVE_FILENAME).exists()


def test_clean_old_runs_skips_dir_with_fresh_alive_sentinel(tmp_path: Path) -> None:
    """Active run (.alive mtime within window) survives a cleanup pass.

    Even though the run dir's own mtime is older than the cutoff, the
    in-progress sentinel keeps it out of harm's way — the F-082 concurrent-run
    race fix.
    """
    ws = allocate_workspace("active-run", base_dir=tmp_path)
    # Make the *directory* look stale, but keep the sentinel fresh.
    old_mtime = time.time() - 8 * 86400
    os.utime(ws.base_dir, (old_mtime, old_mtime))
    # Sentinel mtime = "just now" (fresh).
    os.utime(ws.base_dir / ALIVE_FILENAME, None)

    removed = clean_old_runs(base_dir=tmp_path, max_age_days=7)
    assert removed == 0
    assert ws.base_dir.exists()


def test_clean_old_runs_removes_dir_with_stale_alive_sentinel(tmp_path: Path) -> None:
    """A .alive sentinel older than _STALE_ALIVE_SECONDS is treated as crashed.

    Recovery semantics: after the staleness window the dir is reclaimable
    even though the sentinel is still on disk — covers the case where the
    process died without calling finalize_workspace.
    """
    ws = allocate_workspace("crashed-run", base_dir=tmp_path)
    old_dir_mtime = time.time() - 8 * 86400
    os.utime(ws.base_dir, (old_dir_mtime, old_dir_mtime))
    # Sentinel is also old (process crashed long ago).
    stale_alive_mtime = time.time() - (_STALE_ALIVE_SECONDS + 60)
    os.utime(ws.base_dir / ALIVE_FILENAME, (stale_alive_mtime, stale_alive_mtime))

    removed = clean_old_runs(base_dir=tmp_path, max_age_days=7)
    assert removed == 1
    assert not ws.base_dir.exists()


def test_clean_old_runs_legacy_compat_no_sentinel(tmp_path: Path) -> None:
    """Pre-v0.12.1 run dirs (no .alive file) still go through the mtime check."""
    run_dir = tmp_path / "legacy-run"
    run_dir.mkdir()
    # Pretend it's an old workspace from before the sentinel was introduced.
    old_mtime = time.time() - 8 * 86400
    os.utime(run_dir, (old_mtime, old_mtime))
    assert not (run_dir / ALIVE_FILENAME).exists()

    removed = clean_old_runs(base_dir=tmp_path, max_age_days=7)
    assert removed == 1
    assert not run_dir.exists()
