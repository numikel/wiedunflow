# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Pygments-based syntax highlighting with WiedunFlow `.tok-*` CSS classes.

Decision #4 (Sprint 5 plan): custom `HtmlFormatter` subclass maps Pygments
token types to `.tok-kw/.tok-str/.tok-com/.tok-fn/.tok-cls/.tok-num` CSS classes
so that `tokens.css` can style them with the A1 Paper palette. This avoids
inline styles (`noclasses=True`) and keeps the output HTML small and themable.
"""

from __future__ import annotations

from pygments import highlight  # type: ignore[import-untyped]
from pygments.formatters import HtmlFormatter  # type: ignore[import-untyped]
from pygments.lexers import PythonLexer  # type: ignore[import-untyped]
from pygments.token import Token  # type: ignore[import-untyped]

# Mapping: ordered from most-specific to most-general so the first matching
# parent token wins. Pygments tokens use class inheritance via `in` operator.
#
# v0.2.0 contrast bump: split builtins from classes (``tok-builtin``), split
# decorators from function names (``tok-deco``), add ``tok-op`` for arithmetic
# / comparison operators. Pre-v0.2.0 mapping folded all of these together,
# producing a near-monochrome rendering that the user reported as illegible.
_TOKEN_TO_CLASS: tuple[tuple[object, str], ...] = (
    (Token.Comment, "tok-com"),
    (Token.Keyword, "tok-kw"),
    (Token.Operator.Word, "tok-kw"),
    (Token.Name.Decorator, "tok-deco"),
    (Token.Name.Function, "tok-fn"),
    (Token.Name.Class, "tok-cls"),
    (Token.Name.Exception, "tok-cls"),
    (Token.Name.Builtin.Pseudo, "tok-builtin"),  # self, cls, True, False, None
    (Token.Name.Builtin, "tok-builtin"),
    (Token.Literal.String, "tok-str"),
    (Token.Literal.Number, "tok-num"),
    (Token.Operator, "tok-op"),
)


class WiedunFlowHtmlFormatter(HtmlFormatter):  # type: ignore[misc]
    """Maps Pygments TokenType to WiedunFlow-specific `.tok-*` CSS classes."""

    def _get_css_class(self, ttype: object) -> str:
        for token_type, css_class in _TOKEN_TO_CLASS:
            if ttype in token_type:  # type: ignore[operator]
                return css_class
        return ""

    def _get_css_classes(self, ttype: object) -> str:
        return self._get_css_class(ttype)


# Module-level singletons: constructing PythonLexer / WiedunFlowHtmlFormatter
# once saves ~1 ms of regex-compilation overhead per call — measurable when
# highlighting 30+ code snippets in a single build pass.
_LEXER = PythonLexer()
_FORMATTER = WiedunFlowHtmlFormatter(nowrap=True, noclasses=False)


def highlight_python_lines(lines: list[str]) -> list[str]:
    """Pre-render a list of Python source lines to per-line HTML spans.

    Tokenises the entire block in one Pygments pass (preserving multi-line
    token semantics like triple-quoted strings) then splits the resulting HTML
    back into per-line strings by splitting on ``\\n``.

    Why one-pass instead of per-line calls: Pygments lexes *tokens*, not
    characters.  A triple-quoted docstring ``'\"\"\"\\nhello\\n\"\"\"'``
    spans four lines; calling ``highlight`` on each line individually yields
    four broken fragments without the string token context.  One-pass + split
    is the canonical approach recommended in the Pygments docs for line-level
    output.

    Args:
        lines: Raw Python source lines (no trailing ``\\n`` required; the
            function joins them with ``\\n`` before tokenisation).

    Returns:
        List of HTML strings, one per input line, in the same order.
        Each string contains ``<span class="tok-*">`` elements.
        Returns ``[]`` for empty input without invoking Pygments.
    """
    if not lines:
        return []
    # Join with newlines so the lexer sees a coherent block; Pygments emits
    # one trailing newline after the last token, which we strip before splitting.
    joined = "\n".join(lines)
    html = str(highlight(joined, _LEXER, _FORMATTER))
    # Pygments appends a single trailing '\n' in nowrap mode; strip it so
    # split('\n') doesn't produce a spurious empty element at the end.
    html = html.rstrip("\n")
    parts = html.split("\n")
    # Guard: if Pygments collapses lines (edge case for empty strings at the
    # end of a block) pad the result to match the input length.
    while len(parts) < len(lines):
        parts.append("")
    return parts[: len(lines)]
