# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from codeguide.adapters.pygments_highlighter import highlight_python


def test_highlight_python_inline_styles() -> None:
    """highlight_python() must produce inline style= attributes (noclasses=True)."""
    result = highlight_python("def add(a, b): return a + b")
    assert 'class="' not in result, "Expected noclasses=True output (no class= attributes)"


def test_highlight_python_contains_def_keyword() -> None:
    result = highlight_python("def add(a, b): return a + b")
    assert "def" in result


def test_highlight_python_nowrap() -> None:
    """nowrap=True means no surrounding <div class='highlight'><pre> wrapper."""
    result = highlight_python("x = 1")
    assert "<div" not in result or "highlight" not in result
