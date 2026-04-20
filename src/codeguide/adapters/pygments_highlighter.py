# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pygments import highlight  # type: ignore[import-untyped]
from pygments.formatters import HtmlFormatter  # type: ignore[import-untyped]
from pygments.lexers import PythonLexer  # type: ignore[import-untyped]


def highlight_python(code: str) -> str:
    """Pre-render Python code to inline HTML spans (no external CSS classes).

    Args:
        code: Raw Python source code string.

    Returns:
        HTML string with inline style spans produced by Pygments HtmlFormatter.
        The ``nowrap=True`` flag omits the surrounding ``<div>``/``<pre>`` wrapper
        so callers can embed the output inside their own container elements.
    """
    return str(highlight(code, PythonLexer(), HtmlFormatter(noclasses=True, nowrap=True)))
