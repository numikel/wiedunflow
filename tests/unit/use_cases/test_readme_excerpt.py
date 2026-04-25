# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for ``use_cases.readme_excerpt.load_readme_excerpt``."""

from __future__ import annotations

from pathlib import Path

from codeguide.use_cases.readme_excerpt import load_readme_excerpt


def test_no_readme_returns_none(tmp_path: Path) -> None:
    """Repos without any README file should return None — no appendix rendered."""
    assert load_readme_excerpt(tmp_path) is None


def test_short_readme_returned_verbatim(tmp_path: Path) -> None:
    """README ≤ max_lines is returned exactly as written."""
    body = "# Project\n\nDoes a thing.\n\n## Install\n\nrun it.\n"
    (tmp_path / "README.md").write_text(body, encoding="utf-8")

    excerpt = load_readme_excerpt(tmp_path, max_lines=250)

    assert excerpt == body


def test_long_readme_truncated_with_marker(tmp_path: Path) -> None:
    """README > max_lines collapses to head + truncation marker + tail."""
    lines = [f"line {i}" for i in range(500)]
    (tmp_path / "README.md").write_text("\n".join(lines), encoding="utf-8")

    excerpt = load_readme_excerpt(tmp_path, max_lines=250)

    assert excerpt is not None
    assert "(270 lines omitted)" in excerpt  # 500 - 200 head - 30 tail
    assert "line 0" in excerpt  # head preserved
    assert "line 499" in excerpt  # tail preserved
    assert "line 250" not in excerpt  # middle dropped


def test_uppercase_filename_match(tmp_path: Path) -> None:
    """README.MD (all-caps) is also recognised."""
    (tmp_path / "README.MD").write_text("# Project\n", encoding="utf-8")

    excerpt = load_readme_excerpt(tmp_path)

    assert excerpt == "# Project\n"


def test_empty_readme_returns_empty_string(tmp_path: Path) -> None:
    """An empty README file returns ``""`` (truthy guard skips the appendix)."""
    (tmp_path / "README.md").write_text("", encoding="utf-8")

    excerpt = load_readme_excerpt(tmp_path)

    assert excerpt == ""


def test_max_lines_below_head_plus_tail_clamps_omitted_to_zero(tmp_path: Path) -> None:
    """Callers passing ``max_lines`` below 230 must not see a negative ``omitted``.

    Regression guard for the rubber-duck P2 finding: when ``max_lines=100``
    and the file has 150 lines (>100 → truncate path), naive arithmetic
    would yield ``omitted = 150 - 200 - 30 = -80``. The clamp keeps the
    marker meaningful while head/tail slices fall back gracefully.
    """
    lines = [f"line {i}" for i in range(150)]
    (tmp_path / "README.md").write_text("\n".join(lines), encoding="utf-8")

    excerpt = load_readme_excerpt(tmp_path, max_lines=100)

    assert excerpt is not None
    assert "(0 lines omitted)" in excerpt  # not negative
    assert "line 0" in excerpt
    assert "line 149" in excerpt
