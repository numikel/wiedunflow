# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_DEFAULT_BASE = Path.home() / ".wiedunflow" / "runs"

# Cleanup skips an in-progress run whose ``.alive`` sentinel was touched within
# this window. After the threshold, a stale sentinel (process crashed without
# calling ``finalize_workspace``) is treated as removable so cleanup can reclaim
# the dir. 30 min covers the longest realistic single-lesson Stage 5/6 latency
# while still allowing same-day GC of crashed runs.
_STALE_ALIVE_SECONDS = 30 * 60

# Empty marker file written into each run dir by ``allocate_workspace`` and
# refreshed via ``touch_alive`` during Stage 5/6. ``clean_old_runs`` consults
# the file's mtime to decide whether the run is still active.
ALIVE_FILENAME = ".alive"


def generate_run_id(repo_abs: str, commit_sha: str, started_at: str) -> str:
    """Generate a stable, collision-safe run identifier.

    The ID is derived as ``sha256(repo_abs|commit_sha|started_at)[:12]``.
    Concurrent runs with the same repo+commit but different ``started_at``
    timestamps are therefore guaranteed to produce distinct IDs.

    Args:
        repo_abs: Absolute filesystem path of the repo root.
        commit_sha: Full or short git commit SHA at the time of the run.
        started_at: ISO-8601 timestamp string (e.g. ``"2026-05-01T10:00:00Z"``).

    Returns:
        12-character lowercase hex string.
    """
    raw = f"{repo_abs}|{commit_sha}|{started_at}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class RunWorkspace:
    """Filesystem workspace for a single WiedunFlow agent run.

    Directory layout::

        <base_dir>/
          manifest.json
          orchestrator-state.json
          transcript/<lesson_id>/   # JSONL transcript files
          raw/<lesson_id>/          # raw tool outputs
          processing/<lesson_id>/   # in-flight artefacts (*.md with YAML FM)
          finished/<lesson_id>/     # atomic checkpoints (os.replace from processing/)
            lesson.json
            audit.json

    All writes go through :meth:`write_atomic` / :meth:`write_json_atomic` to
    guarantee NTFS- and ext4-safe atomicity.
    """

    run_id: str
    base_dir: Path

    # ------------------------------------------------------------------
    # Directory helpers
    # ------------------------------------------------------------------

    def lesson_dir(
        self,
        lesson_id: str,
        stage: Literal["raw", "processing", "finished"],
    ) -> Path:
        """Return (and create) the per-lesson stage directory.

        Args:
            lesson_id: Lesson identifier (e.g. ``"lesson-001"``).
            stage: One of ``"raw"``, ``"processing"``, or ``"finished"``.

        Returns:
            The directory path (guaranteed to exist after the call).
        """
        d = self.base_dir / stage / lesson_id
        d.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            os.chmod(d, 0o700)
        return d

    def transcript_dir(self, lesson_id: str) -> Path:
        """Return (and create) the JSONL transcript directory for a lesson.

        Args:
            lesson_id: Lesson identifier.

        Returns:
            The directory path (guaranteed to exist after the call).
        """
        d = self.base_dir / "transcript" / lesson_id
        d.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            os.chmod(d, 0o700)
        return d

    # ------------------------------------------------------------------
    # Atomic I/O
    # ------------------------------------------------------------------

    def write_atomic(self, dest: Path, content: str) -> None:
        """Write *content* to *dest* atomically via a sibling ``.tmp`` file.

        Uses ``os.replace`` which is atomic on POSIX and on NTFS (same
        volume). The parent directory is created if it does not exist.

        Args:
            dest: Target file path.
            content: UTF-8 string to write.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform != "win32":
            os.chmod(dest.parent, 0o700)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, dest)
        logger.debug("write_atomic %s", dest)

    def write_json_atomic(self, dest: Path, data: object) -> None:
        """Serialize *data* to indented JSON and write atomically to *dest*.

        Args:
            dest: Target file path.
            data: JSON-serialisable object.
        """
        self.write_atomic(dest, json.dumps(data, indent=2, ensure_ascii=False))

    def read_json(self, path: Path) -> object:
        """Read and deserialize a JSON file.

        Args:
            path: Path to the JSON file.

        Returns:
            Parsed Python object.

        Raises:
            FileNotFoundError: If *path* does not exist.
            json.JSONDecodeError: If the file contains invalid JSON.
        """
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Checkpoint helpers
    # ------------------------------------------------------------------

    def is_finished(self, lesson_id: str) -> bool:
        """Return ``True`` iff ``finished/<lesson_id>/lesson.json`` exists.

        Args:
            lesson_id: Lesson identifier to check.
        """
        return (self.base_dir / "finished" / lesson_id / "lesson.json").exists()

    def list_finished_lessons(self) -> list[str]:
        """Return sorted list of lesson IDs that have a finished checkpoint.

        Returns:
            Sorted list of lesson-id strings (directory names under
            ``finished/``), or an empty list if the ``finished/`` directory
            does not exist.
        """
        finished = self.base_dir / "finished"
        if not finished.exists():
            return []
        return sorted(d.name for d in finished.iterdir() if d.is_dir())

    # ------------------------------------------------------------------
    # Well-known file paths
    # ------------------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        """Path to ``manifest.json`` at the workspace root."""
        return self.base_dir / "manifest.json"

    @property
    def orchestrator_state_path(self) -> Path:
        """Path to ``orchestrator-state.json`` at the workspace root."""
        return self.base_dir / "orchestrator-state.json"


def allocate_workspace(run_id: str, *, base_dir: Path | None = None) -> RunWorkspace:
    """Create (or reopen) the run workspace directory for *run_id*.

    On allocation, drops an empty ``.alive`` sentinel into the dir so any
    concurrent ``clean_old_runs`` pass can detect an active run and skip it.
    The sentinel must be refreshed via :func:`touch_alive` during long-running
    Stage 5/6 work; :func:`finalize_workspace` removes it on success.

    Args:
        run_id: Unique run identifier (see :func:`generate_run_id`).
        base_dir: Override the default ``~/.wiedunflow/runs/`` base.

    Returns:
        A :class:`RunWorkspace` whose ``base_dir`` is guaranteed to exist.
    """
    root = (base_dir or _DEFAULT_BASE) / run_id
    root.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        # Restrict to user (umask-independent); workspace holds source excerpts + LLM transcripts.
        os.chmod(root, 0o700)
    alive = root / ALIVE_FILENAME
    # Create-or-refresh the sentinel; an existing one (resume scenario) gets a
    # fresh mtime so cleanup sees this dir as currently active.
    if not alive.exists():
        alive.touch()
    else:
        os.utime(alive, None)
    logger.debug("allocate_workspace run_id=%s base_dir=%s", run_id, root)
    return RunWorkspace(run_id=run_id, base_dir=root)


def touch_alive(workspace: RunWorkspace) -> None:
    """Refresh the ``.alive`` sentinel mtime for *workspace*.

    Called periodically during Stage 5/6 (e.g. on every ``SpendMeter.charge``)
    so a concurrent cleanup pass treats this run as in-progress and skips it.
    Missing-sentinel is silently tolerated (e.g. a manual file delete) — the
    next call re-creates it. Crashed runs naturally age past the staleness
    threshold and become reclaimable.
    """
    alive = workspace.base_dir / ALIVE_FILENAME
    try:
        if alive.exists():
            os.utime(alive, None)
        else:
            alive.touch()
    except OSError as exc:
        logger.debug("touch_alive failed run_id=%s exc=%r", workspace.run_id, exc)


def finalize_workspace(workspace: RunWorkspace) -> None:
    """Remove the ``.alive`` sentinel after a successful run.

    Idempotent; missing sentinel is not an error. Calling this in the success
    branch signals cleanup that the dir is safe to GC at its normal age.
    A crash leaves the sentinel in place; the 30-minute staleness window then
    reclaims it on the next cleanup pass.
    """
    alive = workspace.base_dir / ALIVE_FILENAME
    try:
        alive.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("finalize_workspace failed run_id=%s exc=%r", workspace.run_id, exc)


def clean_old_runs(*, base_dir: Path | None = None, max_age_days: int = 7) -> int:
    """Delete run directories older than *max_age_days*.

    Uses the directory's ``mtime`` as a proxy for age. Stale directories are
    removed with ``shutil.rmtree`` (errors silently ignored so a locked file
    on Windows does not abort the whole cleanup pass).

    Concurrency safety: a directory whose ``.alive`` sentinel was touched
    within the last :data:`_STALE_ALIVE_SECONDS` is treated as in-progress and
    skipped, even if its directory mtime predates the cutoff. This lets two
    ``wiedunflow generate`` processes coexist without one's cleanup wiping the
    other's workspace mid-run. Dirs lacking a sentinel are handled by the
    legacy mtime-only path (backward compat for pre-v0.12.1 workspaces).

    Args:
        base_dir: Override the default ``~/.wiedunflow/runs/`` base.
        max_age_days: Directories older than this many days are removed.

    Returns:
        Count of directories removed.
    """
    root = base_dir or _DEFAULT_BASE
    if not root.exists():
        return 0
    cutoff = time.time() - max_age_days * 86400
    alive_cutoff = time.time() - _STALE_ALIVE_SECONDS
    removed = 0
    for run_dir in root.iterdir():
        if not run_dir.is_dir():
            continue
        alive = run_dir / ALIVE_FILENAME
        if alive.exists():
            try:
                alive_mtime = alive.stat().st_mtime
            except OSError:
                alive_mtime = 0.0
            if alive_mtime > alive_cutoff:
                # In-progress; skip even if the dir mtime looks stale.
                continue
        if run_dir.stat().st_mtime < cutoff:
            shutil.rmtree(run_dir, ignore_errors=True)
            removed += 1
            logger.debug("clean_old_runs removed %s", run_dir)
    return removed
