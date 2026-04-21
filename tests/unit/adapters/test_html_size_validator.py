# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-050: output HTML size budget — 8 MB target, 20 MB hard warn."""
from __future__ import annotations

from pathlib import Path

from codeguide.adapters.html_size_validator import validate_size


def _write_sized_file(path: Path, size_bytes: int) -> None:
    with path.open("wb") as fh:
        fh.write(b"x" * size_bytes)


def test_under_eight_mb_is_ok(tmp_path: Path) -> None:
    target = tmp_path / "tiny.html"
    _write_sized_file(target, 1 * 1024 * 1024)
    report = validate_size(target)
    assert report.verdict == "ok"
    assert "within budget" in report.message


def test_above_eight_mb_soft_warn(tmp_path: Path) -> None:
    target = tmp_path / "big.html"
    _write_sized_file(target, 9 * 1024 * 1024)
    report = validate_size(target)
    assert report.verdict == "over_soft_budget"
    assert "8 MB" in report.message


def test_above_twenty_mb_hard_warn(tmp_path: Path) -> None:
    target = tmp_path / "huge.html"
    _write_sized_file(target, 21 * 1024 * 1024)
    report = validate_size(target)
    assert report.verdict == "over_hard_budget"
    assert "20 MB" in report.message


def test_size_report_exposes_mb_property(tmp_path: Path) -> None:
    target = tmp_path / "small.html"
    _write_sized_file(target, 512 * 1024)
    report = validate_size(target)
    assert abs(report.size_mb - 0.5) < 0.01
