# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-062: aggregate_notice.py unit tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.aggregate_notice import aggregate

# ---------------------------------------------------------------------------
# aggregate() — write mode
# ---------------------------------------------------------------------------


def test_header_contains_copyright(tmp_path: Path) -> None:
    """Aggregated NOTICE must contain the project copyright header."""
    output = tmp_path / "NOTICE"
    with patch("scripts.aggregate_notice._find_apache_deps", return_value=[]):
        rc = aggregate(output, check=False)
    assert rc == 0
    content = output.read_text(encoding="utf-8")
    assert "Copyright 2026 Michał Kamiński" in content


def test_header_contains_project_name(tmp_path: Path) -> None:
    """NOTICE must open with the project name 'WiedunFlow'."""
    output = tmp_path / "NOTICE"
    with patch("scripts.aggregate_notice._find_apache_deps", return_value=[]):
        aggregate(output, check=False)
    assert output.read_text(encoding="utf-8").startswith("WiedunFlow\n")


def test_notice_content_included_when_present(tmp_path: Path) -> None:
    """When a dep has a NOTICE file, its content is included."""
    output = tmp_path / "NOTICE"
    fake_deps = [("my-lib", "Apache-2.0")]
    fake_notice = "Copyright 2020 My Library Authors\nAll rights reserved.\n"

    with (
        patch("scripts.aggregate_notice._find_apache_deps", return_value=fake_deps),
        patch(
            "scripts.aggregate_notice._get_notice_content",
            return_value=fake_notice,
        ),
    ):
        rc = aggregate(output, check=False)

    assert rc == 0
    content = output.read_text(encoding="utf-8")
    assert "## my-lib" in content
    assert fake_notice in content


def test_missing_notice_not_fatal(tmp_path: Path) -> None:
    """A dep without a NOTICE file should be noted but must not cause a failure."""
    output = tmp_path / "NOTICE"
    fake_deps = [("no-notice-lib", "Apache-2.0")]

    with (
        patch("scripts.aggregate_notice._find_apache_deps", return_value=fake_deps),
        patch("scripts.aggregate_notice._get_notice_content", return_value=None),
    ):
        rc = aggregate(output, check=False)

    assert rc == 0
    content = output.read_text(encoding="utf-8")
    assert "no-notice-lib" in content
    assert "no NOTICE file" in content


# ---------------------------------------------------------------------------
# aggregate() — check mode
# ---------------------------------------------------------------------------


def test_check_mode_returns_0_when_file_matches(tmp_path: Path) -> None:
    """--check returns 0 when the NOTICE file is already up to date."""
    output = tmp_path / "NOTICE"
    with patch("scripts.aggregate_notice._find_apache_deps", return_value=[]):
        # Write the file first so it matches what --check would generate.
        aggregate(output, check=False)
        # Now verify.
        rc = aggregate(output, check=True)
    assert rc == 0


def test_check_mode_returns_1_when_file_outdated(tmp_path: Path) -> None:
    """--check returns 1 when the NOTICE file content does not match."""
    output = tmp_path / "NOTICE"
    output.write_text("stale content that will not match", encoding="utf-8")

    with patch("scripts.aggregate_notice._find_apache_deps", return_value=[]):
        rc = aggregate(output, check=True)
    assert rc == 1


def test_check_mode_returns_1_when_file_missing(tmp_path: Path) -> None:
    """--check returns 1 when the NOTICE file does not exist at all."""
    output = tmp_path / "NOTICE_MISSING"
    with patch("scripts.aggregate_notice._find_apache_deps", return_value=[]):
        rc = aggregate(output, check=True)
    assert rc == 1
