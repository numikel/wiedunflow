# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for the custom ``CodeGuideHtmlFormatter`` (Sprint 5 decision #4).

The formatter maps Pygments TokenType to ``.tok-*`` CSS classes so the output
HTML can be styled via ``tokens.css`` / ``tutorial.css`` instead of relying on
inline ``style=`` attributes.
"""

from __future__ import annotations

from codeguide.adapters.pygments_highlighter import highlight_python


def test_highlight_python_uses_tok_classes() -> None:
    """Custom formatter emits ``.tok-*`` CSS classes instead of inline styles."""
    result = highlight_python("def add(a, b): return a + b")
    assert 'class="tok-kw"' in result, f"Expected .tok-kw class for 'def', got: {result}"
    assert 'class="tok-fn"' in result, f"Expected .tok-fn class for 'add', got: {result}"


def test_highlight_python_no_inline_styles() -> None:
    """Decision #4 — no inline ``style=`` attributes should be emitted."""
    result = highlight_python("x = 1")
    assert 'style="' not in result, f"Expected no inline style= attributes, got: {result}"


def test_highlight_python_contains_def_keyword() -> None:
    result = highlight_python("def add(a, b): return a + b")
    assert "def" in result


def test_highlight_python_nowrap() -> None:
    """``nowrap=True`` — no surrounding ``<div class='highlight'><pre>`` wrapper."""
    result = highlight_python("x = 1")
    assert "<div" not in result or "highlight" not in result


def test_highlight_python_string_and_comment_classes() -> None:
    result = highlight_python('# hello\nx = "world"')
    assert 'class="tok-com"' in result, f"Expected .tok-com class for comment, got: {result}"
    assert 'class="tok-str"' in result, f"Expected .tok-str class for string, got: {result}"
