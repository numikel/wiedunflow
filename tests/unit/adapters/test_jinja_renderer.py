# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for JinjaRenderer — focusing on XSS-prevention and CSP contracts.

Coverage:
- _sanitize_html_chunk: script/iframe stripping, event-handler removal, js: URL neutralisation
- _safe_for_script_tag: </script> breakout prevention
- JinjaRenderer.render: CSP meta tag present in output
- End-to-end: XSS payloads in lesson title, narrative, and code_panel_html are
  neutralised before they reach the HTML envelope.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wiedunflow.adapters.jinja_renderer import (
    JinjaRenderer,
    _safe_for_script_tag,
    _sanitize_html_chunk,
)
from wiedunflow.entities.lesson import Lesson
from wiedunflow.entities.lesson_plan import LessonPlan

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan(*lessons: Lesson) -> LessonPlan:
    """Build a minimal LessonPlan wrapping the supplied lessons."""
    return LessonPlan(
        lessons=lessons,
        concepts_introduced=(),
        repo_commit_hash="abc1234",
        repo_branch="main",
    )


def _make_lesson(
    *,
    title: str = "Test Lesson",
    narrative: str = "Hello world.",
    lesson_id: str = "lesson-001",
    code_panel_html: str | None = None,
) -> Lesson:
    """Build a minimal Lesson entity."""
    return Lesson(
        id=lesson_id,
        title=title,
        narrative=narrative,
        code_panel_html=code_panel_html,
    )


def _render(lesson: Lesson) -> str:
    """Render a single-lesson plan and return the full HTML string."""
    renderer = JinjaRenderer()
    plan = _make_plan(lesson)
    return renderer.render(
        plan,
        repo_name="test-repo",
        generated_at="2026-01-01T00:00:00Z",
    )


def _extract_lessons_payload(html: str) -> list[dict]:
    """Pull the tutorial-lessons JSON payload out of the rendered HTML.

    This is the data that tutorial.js reads and uses for innerHTML assignment —
    the actual XSS-relevant content path.  The ``narrative`` field is only used
    with ``textContent`` (safe); only ``segments[*].text`` and
    ``code_panel_html`` reach ``innerHTML`` (via DOMPurify on the client, and
    ``_sanitize_html_chunk`` on the server).
    """
    m = re.search(r'id="tutorial-lessons">(.*?)</script>', html, re.DOTALL)
    assert m, "tutorial-lessons JSON block not found in rendered HTML"
    # Unescape the <\\/ → </ substitution applied by _safe_for_script_tag.
    raw = m.group(1).replace("<\\/", "</")
    return json.loads(raw)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# _sanitize_html_chunk unit tests
# ---------------------------------------------------------------------------


class TestSanitizeHtmlChunk:
    """Direct unit tests for the server-side HTML sanitiser."""

    def test_strips_script_tag_with_content(self) -> None:
        payload = '<script>alert("xss")</script>'
        result = _sanitize_html_chunk(payload)
        assert "<script" not in result
        assert "alert" not in result

    def test_strips_iframe_tag(self) -> None:
        payload = '<iframe src="https://evil.example"></iframe>'
        result = _sanitize_html_chunk(payload)
        assert "<iframe" not in result

    def test_strips_on_event_attribute(self) -> None:
        payload = '<img src="x" onerror="alert(1)">'
        result = _sanitize_html_chunk(payload)
        assert "onerror" not in result

    def test_neutralises_javascript_href(self) -> None:
        payload = '<a href="javascript:alert(1)">click</a>'
        result = _sanitize_html_chunk(payload)
        assert "javascript:" not in result

    def test_preserves_safe_html(self) -> None:
        payload = "<p>Hello <strong>world</strong></p>"
        result = _sanitize_html_chunk(payload)
        assert "<strong>world</strong>" in result

    def test_strips_object_embed(self) -> None:
        payload = '<object data="evil.swf"></object>'
        result = _sanitize_html_chunk(payload)
        assert "<object" not in result


# ---------------------------------------------------------------------------
# _safe_for_script_tag unit tests
# ---------------------------------------------------------------------------


class TestSafeForScriptTag:
    """Ensure the JSON envelope cannot break out of <script> blocks."""

    def test_escapes_closing_script_tag(self) -> None:
        payload = '{"title": "</script><script>alert(1)</script>"}'
        result = _safe_for_script_tag(payload)
        assert "</script>" not in result
        assert "<\\/script>" in result

    def test_escapes_html_comment_open(self) -> None:
        payload = '{"x": "<!--"}'
        result = _safe_for_script_tag(payload)
        assert "<!--" not in result

    def test_escapes_cdata_open(self) -> None:
        payload = '{"x": "<![CDATA["}'
        result = _safe_for_script_tag(payload)
        assert "<![CDATA[" not in result

    def test_plain_json_unchanged_structure(self) -> None:
        """Safe JSON must remain parseable after escaping."""
        import json

        payload = json.dumps({"key": "safe value", "num": 42})
        escaped = _safe_for_script_tag(payload)
        # The escaped form must decode back identically when </> is un-escaped
        # (browsers do that when reading <script type="application/json">).
        decoded = escaped.replace("<\\/", "</")
        assert json.loads(decoded) == {"key": "safe value", "num": 42}


# ---------------------------------------------------------------------------
# XSS payload end-to-end tests through JinjaRenderer.render()
# ---------------------------------------------------------------------------


class TestXssViaJinjaRenderer:
    """Verify that XSS payloads embedded in lesson data are neutralised in output HTML."""

    def test_xss_script_in_narrative_stripped(self) -> None:
        """<script> in narrative must not appear in the segments HTML path (innerHTML path).

        mistune's ``escape=True`` converts raw ``<script>`` tags to entities in
        the rendered ``segments[*].text`` output, which is what the browser
        actually assigns to ``innerHTML`` (via DOMPurify).  The raw ``narrative``
        field is rendered via ``textContent`` only — not an XSS vector.
        """
        lesson = _make_lesson(
            narrative="Normal text\n\n<script>alert('xss')</script>\n\nMore text."
        )
        html = _render(lesson)
        lessons = _extract_lessons_payload(html)
        # Check that the segment text (the innerHTML path) contains no raw <script>.
        for seg in lessons[0].get("segments", []):
            assert "<script" not in seg.get("text", ""), (
                f"Raw <script> found in segment text (innerHTML path): {seg['text']!r}"
            )

    def test_xss_img_onerror_in_readme_stripped(self) -> None:
        """onerror attribute in code_panel_html (attacker README) must be stripped.

        ``code_panel_html`` is set directly to ``innerHTML`` in tutorial.js after
        DOMPurify sanitisation (client-side); the server-side ``_sanitize_html_chunk``
        call in ``_lesson_to_payload`` provides a defence-in-depth layer.
        """
        lesson = _make_lesson(
            narrative="README lesson.",
            code_panel_html='<p>Safe</p><img src="x" onerror="alert(1)">',
        )
        html = _render(lesson)
        lessons = _extract_lessons_payload(html)
        code_panel = lessons[0].get("code_panel_html", "")
        assert "onerror" not in code_panel, (
            f"onerror= attribute found in code_panel_html payload: {code_panel!r}"
        )

    def test_xss_iframe_in_narrative_stripped(self) -> None:
        """<iframe> in narrative must not appear in the segments HTML path."""
        lesson = _make_lesson(
            narrative='<iframe src="https://evil.example"></iframe>\n\nLegit content.'
        )
        html = _render(lesson)
        lessons = _extract_lessons_payload(html)
        for seg in lessons[0].get("segments", []):
            assert "<iframe" not in seg.get("text", ""), (
                f"Raw <iframe> found in segment text (innerHTML path): {seg['text']!r}"
            )

    def test_xss_javascript_url_in_link_neutralized(self) -> None:
        """javascript: href inside code_panel_html must be neutralised in the payload."""
        lesson = _make_lesson(
            narrative="Link lesson.",
            code_panel_html='<a href="javascript:alert(1)">click me</a>',
        )
        html = _render(lesson)
        lessons = _extract_lessons_payload(html)
        code_panel = lessons[0].get("code_panel_html", "")
        assert "javascript:" not in code_panel, (
            f"javascript: URL found in code_panel_html payload: {code_panel!r}"
        )

    def test_xss_script_tag_breakout_in_lesson_title_escaped(self) -> None:
        """</script> in lesson title must not break out of the JSON <script> block.

        The title is embedded inside the ``lessons_json`` payload which lives in
        ``<script type="application/json" id="tutorial-lessons">``.  Without
        _safe_for_script_tag(), a crafted ``</script>`` sequence would close that
        block prematurely and allow arbitrary HTML/JS injection after it.
        """
        lesson = _make_lesson(
            title="Legit title </script><script>alert(1)</script>",
            narrative="Content.",
        )
        html = _render(lesson)
        # The raw breakout sequence must not appear verbatim.
        assert "</script><script>alert(1)</script>" not in html
        # The escaped form of the closing-slash should be present instead.
        assert "<\\/script>" in html

    def test_csp_meta_tag_present_in_output(self) -> None:
        """The rendered HTML must carry a Content-Security-Policy meta tag."""
        lesson = _make_lesson()
        html = _render(lesson)
        assert 'http-equiv="Content-Security-Policy"' in html
        # Verify the most critical directives are present.
        assert "default-src 'none'" in html
        assert "base-uri 'none'" in html
        assert "form-action 'none'" in html


# ---------------------------------------------------------------------------
# highlight_python_lines API integration — post-refactor smoke tests
# ---------------------------------------------------------------------------


class TestPygmentsApiIntegration:
    """Verify that the jinja_renderer works correctly after switching from
    the old per-line highlight_python() call to the batch highlight_python_lines()
    API.  These tests do not check exact HTML but assert that known Python tokens
    produce correct tok-* classes in the payload."""

    def test_jinja_renderer_pygments_integration(self, tmp_path: Path) -> None:
        """Renderer must produce tok-* HTML classes for Python code snippets.

        Verifies that after the API change (_build_code_snippet now calls
        highlight_python_lines), the rendered payload still embeds highlighted
        Python source with the expected tok-* span classes.
        """
        from wiedunflow.adapters.jinja_renderer import _build_code_snippet
        from wiedunflow.entities.code_symbol import CodeSymbol

        # Write a small Python file so _build_code_snippet can read it.
        src_file = tmp_path / "greet.py"
        src_file.write_text("def greet():\n    return 'hello'\n", encoding="utf-8")

        sym = CodeSymbol(
            name="greet",
            kind="function",
            file_path=Path("greet.py"),
            lineno=1,
            end_lineno=2,
            docstring=None,
        )

        lesson = Lesson(
            id="lesson-001",
            title="Greet",
            narrative="A greeting function.",
            code_refs=("greet",),
        )

        snippet = _build_code_snippet(lesson, {"greet": sym}, tmp_path)
        assert snippet is not None, "Expected a snippet dict"
        lines = snippet["lines"]
        assert isinstance(lines, list), "lines must be a list"
        assert len(lines) >= 1
        # At least the 'def' keyword line must have tok-kw class.
        assert any("tok-kw" in line for line in lines), (
            f"No tok-kw class found in any line. Lines: {lines}"
        )


def test_only_expected_templates_shipped() -> None:
    """Guard against re-introducing retired templates without CSP / script-tag escaping.

    Adding a new Jinja2 template requires an explicit decision: every shipped
    template must carry a CSP meta tag and route JSON payloads through
    ``_safe_for_script_tag`` (see ADR-0010 §D12). This test fails fast when a
    new ``.j2`` file lands in the templates directory.
    """
    from pathlib import Path

    templates_dir = (
        Path(__file__).resolve().parents[3] / "src" / "wiedunflow" / "renderer" / "templates"
    )
    jinja_files = sorted(p.name for p in templates_dir.glob("*.j2"))
    assert jinja_files == ["tutorial.html.j2"], (
        f"Unexpected Jinja2 templates in {templates_dir}: {jinja_files}. "
        f"Adding a new template requires explicit CSP review."
    )
