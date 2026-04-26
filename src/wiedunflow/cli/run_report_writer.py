# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Atomic writer for ``.codeguide/run-report.json``.

The write is atomic (tmp-file + ``Path.replace``) so a crashing process never
leaves a half-written report that a subsequent ``--resume`` could mistake for
a valid state.
"""

from __future__ import annotations

import json
from pathlib import Path

from wiedunflow.entities.run_report import RunReport

__all__ = ["RunReportWriter", "write_run_report"]

_REPORT_DIR_NAME = ".codeguide"
_REPORT_FILE_NAME = "run-report.json"


def write_run_report(report: RunReport, repo_path: Path) -> Path:
    """Write a ``RunReport`` to ``<repo_path>/.codeguide/run-report.json`` atomically.

    Args:
        report: Validated ``RunReport`` instance.
        repo_path: Repository root; the report is written under
            ``<repo_path>/.codeguide/``.

    Returns:
        Absolute path to the persisted report file.
    """
    report_dir = repo_path / _REPORT_DIR_NAME
    report_dir.mkdir(parents=True, exist_ok=True)
    final_path = report_dir / _REPORT_FILE_NAME
    tmp_path = final_path.with_suffix(".json.tmp")

    payload = report.model_dump(mode="json")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(final_path)
    return final_path


class RunReportWriter:
    """Thin OO façade around :func:`write_run_report` for dependency injection."""

    def __init__(self, repo_path: Path) -> None:
        self._repo_path = repo_path

    def write(self, report: RunReport) -> Path:
        return write_run_report(report, self._repo_path)
