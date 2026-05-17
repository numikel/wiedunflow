# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for the custom ``WiedunFlowHtmlFormatter`` (Sprint 5 decision #4).

The formatter maps Pygments TokenType to ``.tok-*`` CSS classes so the output
HTML can be styled via ``tokens.css`` / ``tutorial.css`` instead of relying on
inline ``style=`` attributes. These tests focus on token-to-class mapping —
correctness of the per-block ``highlight_python_lines`` helper lives in
``test_pygments_highlighter.py``.
"""

from __future__ import annotations

from wiedunflow.adapters.pygments_highlighter import highlight_python_lines


def _highlight(code: str) -> str:
    """Join per-line highlighted output for a single-string assertion."""
    return "\n".join(highlight_python_lines(code.splitlines() or [""]))


def test_highlight_python_uses_tok_classes() -> None:
    """Custom formatter emits ``.tok-*`` CSS classes instead of inline styles."""
    result = _highlight("def add(a, b): return a + b")
    assert 'class="tok-kw"' in result, f"Expected .tok-kw class for 'def', got: {result}"
    assert 'class="tok-fn"' in result, f"Expected .tok-fn class for 'add', got: {result}"


def test_highlight_python_no_inline_styles() -> None:
    """Decision #4 — no inline ``style=`` attributes should be emitted."""
    result = _highlight("x = 1")
    assert 'style="' not in result, f"Expected no inline style= attributes, got: {result}"


def test_highlight_python_contains_def_keyword() -> None:
    result = _highlight("def add(a, b): return a + b")
    assert "def" in result


def test_highlight_python_nowrap() -> None:
    """``nowrap=True`` — no surrounding ``<div class='highlight'><pre>`` wrapper."""
    result = _highlight("x = 1")
    assert "<div" not in result or "highlight" not in result


def test_highlight_python_string_and_comment_classes() -> None:
    result = _highlight('# hello\nx = "world"')
    assert 'class="tok-com"' in result, f"Expected .tok-com class for comment, got: {result}"
    assert 'class="tok-str"' in result, f"Expected .tok-str class for string, got: {result}"
