# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import re
from pathlib import Path

import pytest
from syrupy import SnapshotAssertion

pytestmark = pytest.mark.integration


def _normalize_html(html: str) -> str:
    """Remove volatile fields for stable snapshots.

    Normalizes:
      - Windows drive letters in ``file://`` paths.
      - The ``<branch>@<short-hash>`` footer token — volatile because the
        tiny_repo fixture lives inside the CodeGuide repo, so git_context
        returns the parent repo's HEAD and branch, both of which change on
        every commit.
    """
    html = re.sub(r"file:///[A-Za-z]:/", "file:///C:/", html)
    html = re.sub(r"<code>[^<@]+@[^<]+</code>", "<code>NORMALIZED_BRANCH@HASH</code>", html)
    return html


def test_tutorial_html_exists(tutorial_html: Path) -> None:
    assert tutorial_html.exists()


def test_tutorial_html_size(tutorial_html: Path) -> None:
    size = tutorial_html.stat().st_size
    assert size < 500 * 1024, f"tutorial.html too large: {size} bytes (limit: 500 KB)"
    assert size > 1024, "tutorial.html suspiciously small"


def test_tutorial_html_snapshot(tutorial_html: Path, snapshot: SnapshotAssertion) -> None:
    """Golden snapshot — any template change must be intentional (run with --snapshot-update)."""
    html = tutorial_html.read_text(encoding="utf-8")
    assert _normalize_html(html) == snapshot


def test_tutorial_html_has_three_lessons(tutorial_html: Path) -> None:
    html = tutorial_html.read_text(encoding="utf-8")
    assert html.count('"lesson-001"') >= 1
    assert html.count('"lesson-002"') >= 1
    assert html.count('"lesson-003"') >= 1


def test_tutorial_html_no_external_resources(tutorial_html: Path) -> None:
    html = tutorial_html.read_text(encoding="utf-8")
    # Should have no external http/https references (FakeLLM doesn't add them)
    external = re.findall(r"https?://(?!localhost)", html)
    assert external == [], f"Found external URLs: {external}"


def test_tutorial_html_has_nav_buttons(tutorial_html: Path) -> None:
    html = tutorial_html.read_text(encoding="utf-8")
    assert 'id="btn-prev"' in html
    assert 'id="btn-next"' in html


def test_tutorial_html_has_tutorial_data_script(tutorial_html: Path) -> None:
    html = tutorial_html.read_text(encoding="utf-8")
    assert '<script type="application/json" id="tutorial-data">' in html
