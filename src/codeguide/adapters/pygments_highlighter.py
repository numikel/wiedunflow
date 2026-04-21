# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Pygments-based syntax highlighting with CodeGuide `.tok-*` CSS classes.

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
_TOKEN_TO_CLASS: tuple[tuple[object, str], ...] = (
    (Token.Comment, "tok-com"),
    (Token.Keyword, "tok-kw"),
    (Token.Operator.Word, "tok-kw"),
    (Token.Name.Function, "tok-fn"),
    (Token.Name.Decorator, "tok-fn"),
    (Token.Name.Class, "tok-cls"),
    (Token.Name.Builtin, "tok-cls"),
    (Token.Name.Exception, "tok-cls"),
    (Token.Literal.String, "tok-str"),
    (Token.Literal.Number, "tok-num"),
)


class CodeGuideHtmlFormatter(HtmlFormatter):  # type: ignore[misc]
    """Maps Pygments TokenType to CodeGuide-specific `.tok-*` CSS classes."""

    def _get_css_class(self, ttype: object) -> str:
        for token_type, css_class in _TOKEN_TO_CLASS:
            if ttype in token_type:  # type: ignore[operator]
                return css_class
        return ""

    def _get_css_classes(self, ttype: object) -> str:
        return self._get_css_class(ttype)


def highlight_python(code: str) -> str:
    """Pre-render Python code to HTML spans with ``.tok-*`` CSS classes.

    Args:
        code: Raw Python source code string.

    Returns:
        HTML string with ``<span class="tok-kw">`` etc. classes. The
        ``nowrap=True`` flag omits the surrounding ``<div>``/``<pre>`` wrapper
        so callers can embed the output inside their own container elements.
    """
    formatter = CodeGuideHtmlFormatter(nowrap=True, noclasses=False)
    return str(highlight(code, PythonLexer(), formatter))
