# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _extract_json(html: str, script_id: str) -> object:
    """Pull a ``<script type="application/json" id="...">`` payload out of the HTML."""
    marker = f'id="{script_id}"'
    idx = html.find(marker)
    assert idx >= 0, f"Missing embedded JSON block: {script_id}"
    start = html.find(">", idx) + 1
    end = html.find("</script>", start)
    return json.loads(html[start:end])


def test_tutorial_html_exists(tutorial_html: Path) -> None:
    assert tutorial_html.exists()


def test_tutorial_html_size(tutorial_html: Path) -> None:
    """Sprint 5: inline WOFF2 fonts (~800 KB) + CSS + JS raise baseline.

    Spec budget (US-050) is <8 MB for a medium repo; tiny_repo should comfortably
    stay under 3 MB.
    """
    size = tutorial_html.stat().st_size
    assert size < 3 * 1024 * 1024, f"tutorial.html too large: {size} bytes (limit: 3 MB)"
    assert size > 50 * 1024, "tutorial.html suspiciously small (fonts should be inlined)"


def test_tutorial_html_has_three_lessons(tutorial_html: Path) -> None:
    lessons = _extract_json(tutorial_html.read_text(encoding="utf-8"), "tutorial-lessons")
    assert isinstance(lessons, list)
    lesson_ids = {lesson["id"] for lesson in lessons}
    assert "lesson-001" in lesson_ids
    assert "lesson-002" in lesson_ids
    assert "lesson-003" in lesson_ids


def test_tutorial_html_no_external_resources(tutorial_html: Path) -> None:
    """US-040: no outbound http(s) references in the rendered HTML."""
    html = tutorial_html.read_text(encoding="utf-8")
    external = re.findall(r"""(?<!data:)https?://(?!localhost)""", html)
    assert external == [], f"Found external URLs: {external}"


def test_tutorial_html_has_three_json_payloads(tutorial_html: Path) -> None:
    """ADR-0009 envelope: meta + clusters + lessons JSON scripts are present."""
    html = tutorial_html.read_text(encoding="utf-8")
    assert '<script type="application/json" id="tutorial-meta">' in html
    assert '<script type="application/json" id="tutorial-clusters">' in html
    assert '<script type="application/json" id="tutorial-lessons">' in html


def test_tutorial_html_has_schema_version(tutorial_html: Path) -> None:
    """US-048: meta payload carries schema_version and wiedunflow_version."""
    meta = _extract_json(tutorial_html.read_text(encoding="utf-8"), "tutorial-meta")
    assert isinstance(meta, dict)
    assert meta["schema_version"] == "1.0.0"
    assert "wiedunflow_version" in meta
    assert meta["wiedunflow_version"]


def test_tutorial_html_has_topbar_and_footer(tutorial_html: Path) -> None:
    """Structural DOM contract per ADR-0009."""
    html = tutorial_html.read_text(encoding="utf-8")
    assert 'id="tutorial-topbar"' in html
    assert 'id="tutorial-footer"' in html
    assert 'id="tutorial-narration"' in html
    assert 'id="tutorial-code"' in html
    assert 'id="tutorial-splitter"' in html


def test_tutorial_html_offline_footer_message(tutorial_html: Path) -> None:
    """US-047: the footer asserts offline-guaranteed behaviour."""
    html = tutorial_html.read_text(encoding="utf-8")
    assert "fully offline" in html
    assert "Apache 2.0" in html


def test_default_output_filename_matches_wiedunflow_repo_pattern(
    tiny_repo_path: Path,
    providers,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v0.6.0 rebrand: default output filename is `wiedunflow-<repo>.html` in cwd.

    Regression guard for ADR-0015 (Phase 1.3 rename). Without an explicit
    `output_path`, the generator writes `wiedunflow-{repo_path.name}.html`
    relative to cwd — NOT the legacy `tutorial.html`.
    """
    from wiedunflow.use_cases.generate_tutorial import generate_tutorial

    monkeypatch.chdir(tmp_path)
    result = generate_tutorial(tiny_repo_path, providers)

    expected = tmp_path / f"wiedunflow-{tiny_repo_path.name}.html"
    assert result.output_path == expected, (
        f"default output path drifted: expected {expected}, got {result.output_path}"
    )
    assert expected.exists(), "default output file was not actually written"
    # Sanity: the legacy filename must NOT be created when default applies.
    assert not (tmp_path / "tutorial.html").exists(), (
        "legacy tutorial.html should not exist under default output rules"
    )
