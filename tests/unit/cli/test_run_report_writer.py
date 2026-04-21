# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for the atomic run-report writer (US-029, US-032 serialisation)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codeguide.cli.run_report_writer import RunReportWriter, write_run_report
from codeguide.entities.run_report import RunReport


def _mk_report(status: str = "ok", **extra: object) -> RunReport:
    started = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    base: dict[str, object] = {
        "status": status,
        "started_at": started,
        "finished_at": started + timedelta(seconds=10),
        "total_planned_lessons": 3,
        "skipped_lessons_count": 0,
        "retry_count": 0,
        "cache_hit_rate": 0.0,
        "provider": "fake",
    }
    base.update(extra)
    return RunReport(**base)  # type: ignore[arg-type]


def test_write_creates_codeguide_directory(tmp_path: Path) -> None:
    write_run_report(_mk_report(), tmp_path)
    assert (tmp_path / ".codeguide").is_dir()
    assert (tmp_path / ".codeguide" / "run-report.json").is_file()


def test_write_returns_final_path(tmp_path: Path) -> None:
    path = write_run_report(_mk_report(), tmp_path)
    assert path == tmp_path / ".codeguide" / "run-report.json"


def test_written_json_is_valid_and_matches_payload(tmp_path: Path) -> None:
    write_run_report(_mk_report(status="degraded", degraded_ratio=0.5), tmp_path)
    payload = json.loads((tmp_path / ".codeguide" / "run-report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "degraded"
    assert payload["schema_version"] == "1.0.0"
    assert payload["degraded_ratio"] == 0.5


def test_write_is_atomic_no_tmp_left_behind(tmp_path: Path) -> None:
    write_run_report(_mk_report(), tmp_path)
    tmp_files = list((tmp_path / ".codeguide").glob("*.tmp"))
    assert tmp_files == []


def test_failure_report_serialises_stack_trace(tmp_path: Path) -> None:
    report = _mk_report(
        status="failed",
        stack_trace="Traceback (most recent call last):\n  RuntimeError: boom",
        failed_at_lesson="lesson-004",
    )
    write_run_report(report, tmp_path)
    payload = json.loads((tmp_path / ".codeguide" / "run-report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["failed_at_lesson"] == "lesson-004"
    assert "RuntimeError: boom" in payload["stack_trace"]


def test_writer_class_wraps_function(tmp_path: Path) -> None:
    writer = RunReportWriter(tmp_path)
    path = writer.write(_mk_report())
    assert path.exists()
    assert path.name == "run-report.json"


def test_second_write_overwrites_first(tmp_path: Path) -> None:
    write_run_report(_mk_report(status="ok"), tmp_path)
    write_run_report(_mk_report(status="interrupted"), tmp_path)
    payload = json.loads((tmp_path / ".codeguide" / "run-report.json").read_text(encoding="utf-8"))
    assert payload["status"] == "interrupted"
