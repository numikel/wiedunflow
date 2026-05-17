# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for the pygments_highlighter adapter.

Coverage:
- highlight_python_lines: multi-line docstring correctness (all lines carry
  tok-string class, not just the opening line)
- highlight_python_lines: empty input returns empty list without calling Pygments
- highlight_python_lines: single-line input returns a length-1 list
- Module-level singleton identity: _LEXER and _FORMATTER are the same objects
  across two calls (no per-call construction overhead)
"""

from __future__ import annotations

from wiedunflow.adapters.pygments_highlighter import (
    _FORMATTER,
    _LEXER,
    highlight_python_lines,
)

# ---------------------------------------------------------------------------
# highlight_python_lines — correctness
# ---------------------------------------------------------------------------


class TestHighlightPythonLines:
    """Functional tests for highlight_python_lines."""

    def test_empty_input_returns_empty_list(self) -> None:
        """highlight_python_lines([]) must return [] without invoking Pygments."""
        result = highlight_python_lines([])
        assert result == []

    def test_single_line_returns_length_one(self) -> None:
        """A single-element input must produce a single-element output."""
        result = highlight_python_lines(["x = 1"])
        assert len(result) == 1
        # The output must be a non-empty string (Pygments always emits something
        # for valid Python tokens).
        assert isinstance(result[0], str)
        assert result[0]  # not empty

    def test_output_length_matches_input_length(self) -> None:
        """The result list must have the same number of elements as the input."""
        lines = ["def foo():", "    return 42", ""]
        result = highlight_python_lines(lines)
        assert len(result) == len(lines)

    def test_multiline_docstring_all_lines_have_tok_string(self) -> None:
        """All four lines of a triple-quoted docstring must carry tok-str class.

        This is the key regression from the old per-line approach: calling
        highlight on each line individually would tokenise '\"\"\"' as an
        *opening* string token on line 1 and produce broken/plain text for
        lines 2-4.  The one-pass approach must preserve the full string span.
        """
        # Four-line triple-quoted string: opening, content, content, closing.
        docstring_lines = ['"""', "hello", "world", '"""']
        result = highlight_python_lines(docstring_lines)

        assert len(result) == 4, f"Expected 4 output lines, got {len(result)}"
        for i, html in enumerate(result):
            assert "tok-str" in html, (
                f"Line {i} ({docstring_lines[i]!r}) does not contain 'tok-str' class.\n"
                f"Full output: {result}"
            )

    def test_multiline_docstring_with_content(self) -> None:
        """A complete docstring block spanning 5 lines must all be string tokens."""
        lines = [
            '    """',
            "    This is a docstring.",
            "    It has two content lines.",
            "    More.",
            '    """',
        ]
        result = highlight_python_lines(lines)
        assert len(result) == 5
        for i, html in enumerate(result):
            assert "tok-str" in html, f"Line {i} does not carry tok-str. Full output:\n{result}"

    def test_keyword_line_has_tok_kw_class(self) -> None:
        """A line with a Python keyword must carry the tok-kw class."""
        result = highlight_python_lines(["def foo():"])
        assert len(result) == 1
        assert "tok-kw" in result[0], f"Expected tok-kw in: {result[0]}"

    def test_comment_line_has_tok_com_class(self) -> None:
        """A comment line must carry the tok-com class."""
        result = highlight_python_lines(["# this is a comment"])
        assert len(result) == 1
        assert "tok-com" in result[0], f"Expected tok-com in: {result[0]}"

    def test_number_literal_has_tok_num_class(self) -> None:
        """A numeric literal must carry the tok-num class."""
        result = highlight_python_lines(["x = 42"])
        assert len(result) == 1
        assert "tok-num" in result[0], f"Expected tok-num in: {result[0]}"

    def test_multiline_input_preserves_order(self) -> None:
        """The output list order must match input order (no reordering)."""
        lines = ["a = 1", "b = 2", "c = 3"]
        result = highlight_python_lines(lines)
        assert len(result) == 3
        # Each output line must mention its variable (sanity check).
        assert "a" in result[0]
        assert "b" in result[1]
        assert "c" in result[2]


# ---------------------------------------------------------------------------
# Module-level singleton identity
# ---------------------------------------------------------------------------


class TestSingletonIdentity:
    """Verify that _LEXER and _FORMATTER are module-level singletons."""

    def test_highlight_lines_singleton_lexer(self) -> None:
        """_LEXER used across two calls must be the same object (identity)."""
        # Import twice — Python caches module imports, so both aliases resolve
        # to the same module-level object.
        from wiedunflow.adapters import pygments_highlighter as _mod

        lexer_before = _mod._LEXER
        highlight_python_lines(["x = 1"])
        highlight_python_lines(["y = 2"])
        lexer_after = _mod._LEXER

        assert lexer_before is lexer_after, (
            "Expected _LEXER to remain the same object across calls (singleton), "
            f"but got different instances: {id(lexer_before)} vs {id(lexer_after)}"
        )

    def test_highlight_lines_singleton_formatter(self) -> None:
        """_FORMATTER must be the same object across calls."""
        from wiedunflow.adapters import pygments_highlighter as _mod

        formatter_before = _mod._FORMATTER
        highlight_python_lines(["class Foo:"])
        formatter_after = _mod._FORMATTER

        assert formatter_before is formatter_after, (
            "Expected _FORMATTER singleton to persist across calls, "
            f"but got {id(formatter_before)} vs {id(formatter_after)}"
        )

    def test_module_exports_singleton_objects(self) -> None:
        """_LEXER and _FORMATTER exported from the module must match the ones used."""
        from wiedunflow.adapters import pygments_highlighter as _mod

        # The objects imported at module level must be the same as re-fetching them.
        assert _LEXER is _mod._LEXER
        assert _FORMATTER is _mod._FORMATTER
