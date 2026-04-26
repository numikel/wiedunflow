# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Run-report history rotation (US-058).

Keeps the last 10 timestamped copies under ``<repo>/.wiedunflow/history/``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def write_history_copy(
    *,
    current_report: Path,
    history_dir: Path,
    keep_latest: int = 10,
) -> Path:
    """Copy the current run-report into the history folder and prune old entries.

    Args:
        current_report: Path to the freshly-written ``run-report.json``.
        history_dir: Directory that holds ``run-report-<ISO>.json`` copies.
        keep_latest: Number of most-recent files to retain (default 10).

    Returns:
        The new history path (``<history_dir>/run-report-<iso>.json``).
    """
    history_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    target = history_dir / f"run-report-{stamp}.json"
    target.write_bytes(current_report.read_bytes())

    existing = sorted(
        (p for p in history_dir.glob("run-report-*.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in existing[keep_latest:]:
        old.unlink(missing_ok=True)

    return target
