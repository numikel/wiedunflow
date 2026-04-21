# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-058: run-report history rotation keeps the last 10 copies."""
from __future__ import annotations

import time
from pathlib import Path

from codeguide.cli.history_rotator import write_history_copy


def _write_current(repo: Path, payload: str) -> Path:
    current = repo / "run-report.json"
    current.write_text(payload, encoding="utf-8")
    return current


def test_history_first_copy_created(tmp_path: Path) -> None:
    current = _write_current(tmp_path, '{"status": "ok"}')
    history = tmp_path / "history"
    archived = write_history_copy(
        current_report=current, history_dir=history, keep_latest=10
    )
    assert archived.exists()
    assert archived.parent == history
    assert archived.read_text(encoding="utf-8") == '{"status": "ok"}'


def test_history_retains_exact_keep_latest_count(tmp_path: Path) -> None:
    current = _write_current(tmp_path, "x")
    history = tmp_path / "history"
    for i in range(15):
        current.write_text(f"payload-{i}", encoding="utf-8")
        write_history_copy(current_report=current, history_dir=history, keep_latest=5)
        # Stamps use whole-second precision — brief sleep avoids collision.
        time.sleep(0.05)
    files = list(history.glob("run-report-*.json"))
    assert len(files) == 5, f"Expected exactly 5 rotated files, got {len(files)}"
