# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Integration tests for XSS-prevention in the tutorial rendering pipeline.

These tests exercise the full path from lesson data -> JinjaRenderer.render() ->
HTML output, asserting that attacker-controlled content (e.g. a malicious repo
README) does not produce exploitable output in the rendered HTML file.

We do not run the full 7-stage pipeline here (that requires a real API key and
is covered by ``pytest -m eval``). Instead we exercise the rendering stage
directly, which is where the three XSS vectors materialise:

1. ``code_panel_html`` -- mistune-rendered README (attacker-controlled).
   Server-side: _lesson_to_payload applies _sanitize_html_chunk.
   Client-side: tutorial.js wraps innerHTML with DOMPurify.sanitize.

2. ``segments[*].text`` -- mistune-rendered LLM narration.
   Server-side: mistune escape=True HTML-escapes raw tags; block_html/inline_html
   overrides strip dangerous tags from raw HTML blocks.
   Client-side: tutorial.js wraps innerHTML with DOMPurify.sanitize.

3. JSON envelope ``lessons_json`` -- ``<script>`` block breakout.
   Server-side: _safe_for_script_tag escapes </script> sequences.

The XSS-relevant fields are those assigned to innerHTML in tutorial.js:
- segments[*].text (kind=html and kind=p)
- lesson.code_panel_html

The ``narrative`` field is only used via textContent (safe by design).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wiedunflow.adapters.jinja_renderer import JinjaRenderer
from wiedunflow.entities.lesson import Lesson
from wiedunflow.entities.lesson_plan import LessonPlan

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MALICIOUS_SCRIPT = "<script>alert(1)</script>"
_MALICIOUS_ONERROR = '<img src="x" onerror="alert(1)">'
_MALICIOUS_IFRAME = '<iframe src="javascript:alert(1)"></iframe>'
_BREAKOUT_TITLE = "Good title </script><script>alert(1)</script>"


def _make_lesson(
    *,
    lesson_id: str = "lesson-001",
    title: str = "Test",
    narrative: str = "Safe narrative.",
    code_panel_html: str | None = None,
) -> Lesson:
    return Lesson(
        id=lesson_id,
        title=title,
        narrative=narrative,
        code_panel_html=code_panel_html,
    )


def _render_html(lessons: list[Lesson]) -> str:
    """Render a LessonPlan and return the HTML string."""
    plan = LessonPlan(
        lessons=tuple(lessons),
        concepts_introduced=(),
        repo_commit_hash="deadbeef",
        repo_branch="main",
    )
    renderer = JinjaRenderer()
    return renderer.render(
        plan,
        repo_name="malicious-repo",
        generated_at="2026-01-01T00:00:00Z",
    )


def _render_to_file(lessons: list[Lesson], tmp_dir: Path) -> Path:
    """Render and write to a temp HTML file."""
    html = _render_html(lessons)
    out = tmp_dir / "tutorial.html"
    out.write_text(html, encoding="utf-8")
    return out


def _extract_lessons_payload(html: str) -> list[dict]:
    """Extract the tutorial-lessons JSON payload — the innerHTML-bound data."""
    m = re.search(r'id="tutorial-lessons">(.*?)</script>', html, re.DOTALL)
    assert m, "tutorial-lessons JSON block not found in rendered HTML"
    raw = m.group(1).replace("<\\/", "</")
    return json.loads(raw)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_malicious_readme_no_payload_in_output(tmp_path: Path) -> None:
    """Attacker-controlled README with <script>alert(1)</script> must not appear raw.

    Simulates the real pipeline path where the project README is rendered by
    mistune (_markdown_to_html) and stored as ``code_panel_html`` on the Project
    README lesson.  The server-side ``_sanitize_html_chunk`` applied in
    ``_lesson_to_payload`` must strip the script tag before it reaches the
    JSON payload (which is then injected via innerHTML in the browser).
    """
    malicious_readme_html = (
        f"<h1>My Project</h1>\n{_MALICIOUS_SCRIPT}\n<p>Totally normal README content.</p>"
    )
    lesson = _make_lesson(
        lesson_id="lesson-readme",
        title="Project README",
        narrative="See the README for details.",
        code_panel_html=malicious_readme_html,
    )
    html = _render_html([lesson])
    lessons = _extract_lessons_payload(html)

    # The code_panel_html field is the one tutorial.js assigns to innerHTML.
    code_panel = lessons[0].get("code_panel_html", "")
    assert "<script>alert(1)" not in code_panel, (
        f"Raw <script>alert(1)</script> found in code_panel_html payload: {code_panel!r}"
    )


def test_onerror_in_code_panel_html_absent(tmp_path: Path) -> None:
    """onerror event handler in code_panel_html must be stripped before embedding."""
    lesson = _make_lesson(
        lesson_id="lesson-readme",
        title="Project README",
        narrative="README.",
        code_panel_html=f"<p>Safe</p>{_MALICIOUS_ONERROR}",
    )
    html = _render_html([lesson])
    lessons = _extract_lessons_payload(html)

    code_panel = lessons[0].get("code_panel_html", "")
    assert "onerror=" not in code_panel, (
        f"onerror= attribute found in code_panel_html payload: {code_panel!r}"
    )


def test_iframe_in_narrative_segments_absent(tmp_path: Path) -> None:
    """<iframe> injected via LLM narrative must not appear in the segments innerHTML path.

    mistune ``escape=True`` HTML-escapes raw tags in the input; the block_html /
    inline_html overrides provide a belt-and-suspenders layer for raw HTML blocks.
    Either way, ``<iframe>`` must not appear in ``segments[*].text`` unescaped.
    """
    lesson = _make_lesson(
        narrative=f"Normal intro.\n\n{_MALICIOUS_IFRAME}\n\nMore content.",
    )
    html = _render_html([lesson])
    lessons = _extract_lessons_payload(html)

    for seg in lessons[0].get("segments", []):
        seg_text = seg.get("text", "")
        assert "<iframe" not in seg_text, (
            f"Raw <iframe> found in segment text (innerHTML path): {seg_text!r}"
        )


def test_script_tag_breakout_via_lesson_title_absent(tmp_path: Path) -> None:
    """</script> in lesson title must not produce a JSON script-block breakout.

    Without _safe_for_script_tag(), the sequence ``</script>`` inside the JSON
    payload would terminate the ``<script type="application/json">`` block early,
    allowing the rest of the title string to be interpreted as raw HTML.
    """
    lesson = _make_lesson(title=_BREAKOUT_TITLE)
    html_path = _render_to_file([lesson], tmp_path)
    html = html_path.read_text(encoding="utf-8")

    # The raw breakout string must not appear verbatim.
    assert "</script><script>alert(1)</script>" not in html, (
        "Raw </script><script> breakout sequence found — JSON block not escaped!"
    )
    # The escaped form must be present as evidence the substitution actually ran.
    assert "<\\/script>" in html, (
        "_safe_for_script_tag() did not produce expected <\\/ escape in output"
    )


def test_html_output_contains_csp_header(tmp_path: Path) -> None:
    """Every rendered HTML must carry the Content-Security-Policy meta tag."""
    lesson = _make_lesson()
    html_path = _render_to_file([lesson], tmp_path)
    html = html_path.read_text(encoding="utf-8")

    assert 'http-equiv="Content-Security-Policy"' in html
    assert "default-src 'none'" in html
    assert "base-uri 'none'" in html
