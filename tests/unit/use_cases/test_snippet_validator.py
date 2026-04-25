# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for validate_narrative_snippets."""

from __future__ import annotations

from pathlib import Path

import pytest

from codeguide.entities.code_ref import CodeRef
from codeguide.use_cases.snippet_validator import validate_narrative_snippets

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ref(
    symbol: str = "mod.foo",
    source_excerpt: str | None = None,
) -> CodeRef:
    return CodeRef(
        file_path=Path("mod.py"),
        symbol=symbol,
        line_start=1,
        line_end=5,
        source_excerpt=source_excerpt,
    )


def _fenced(code: str) -> str:
    """Wrap code in a ```python fenced block."""
    return f"```python\n{code}\n```"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_signature_match_returns_no_errors() -> None:
    """code_ref has matching def signature → no errors."""
    excerpt = "def foo(x, y):\n    return x + y"
    fenced = _fenced("def foo(x, y):\n    return x + y")
    narrative = "Here is the function:\n\n" + fenced
    result = validate_narrative_snippets(narrative, (_make_ref("mod.foo", excerpt),))
    assert result == []


def test_signature_mismatch_param_order_returns_error() -> None:
    """Param order mismatch → exactly 1 error mentioning the misquoted signature."""
    excerpt = "def write(content, file_path):\n    pass"
    narrative = _fenced("def write(file_path, content):\n    pass")
    result = validate_narrative_snippets(narrative, (_make_ref("mod.write", excerpt),))
    assert len(result) == 1
    assert "write" in result[0]


def test_signature_mismatch_function_name_returns_error() -> None:
    """Function name mismatch → exactly 1 error."""
    excerpt = "def load_json_file(path):\n    pass"
    # narrative spells it 'load_json' instead of 'load_json_file'
    narrative = _fenced("def load_json(path):\n    pass")
    # Provide a ref for the correct name so the validator tries to match
    result = validate_narrative_snippets(
        narrative,
        (_make_ref("mod.load_json_file", excerpt),),
    )
    # load_json has no matching ref → lenient (no error for unknown name)
    assert result == []


def test_function_name_exact_mismatch_detected() -> None:
    """When narrative has a block with a def that IS in code_refs but has wrong name."""
    # We make a ref whose simple name matches what is in the narrative
    # and whose excerpt has a different function name
    excerpt_with_different_name = "def load_json_file(path):\n    pass"
    # ref.symbol = "mod.load_json" → simple name "load_json"
    # narrative def load_json(x) → matches "load_json" ref
    # excerpt says "def load_json_file" → name mismatch
    narrative = _fenced("def load_json(path):\n    pass")
    result = validate_narrative_snippets(
        narrative,
        (_make_ref("mod.load_json", excerpt_with_different_name),),
    )
    # name in snippet ("load_json") != name in excerpt ("load_json_file")
    assert len(result) == 1
    assert "load_json" in result[0]


def test_no_python_fence_returns_no_errors() -> None:
    """Narrative without any ```python block → no errors."""
    narrative = "This lesson explains the module.\n\nIt has no code blocks."
    ref = _make_ref("mod.foo", "def foo(x): pass")
    result = validate_narrative_snippets(narrative, (ref,))
    assert result == []


def test_multi_block_one_valid_one_invalid_returns_one_error() -> None:
    """Two ```python blocks: first valid, second has wrong param order → 1 error."""
    excerpt_foo = "def foo(a, b):\n    pass"
    excerpt_bar = "def bar(x, y, z):\n    pass"

    block_valid = _fenced("def foo(a, b):\n    pass")
    block_invalid = _fenced("def bar(z, y, x):\n    pass")  # param order wrong
    narrative = f"First:\n\n{block_valid}\n\nSecond:\n\n{block_invalid}"

    refs = (
        _make_ref("mod.foo", excerpt_foo),
        _make_ref("mod.bar", excerpt_bar),
    )
    result = validate_narrative_snippets(narrative, refs)
    assert len(result) == 1
    assert "bar" in result[0]


def test_source_excerpt_none_skips_validation() -> None:
    """code_ref with source_excerpt=None → validator skips (no error)."""
    narrative = _fenced("def foo(x, y, z):\n    pass")  # would be wrong if checked
    ref = _make_ref("mod.foo", None)  # no ground truth
    result = validate_narrative_snippets(narrative, (ref,))
    assert result == []


def test_body_abbreviation_with_ellipsis_no_error() -> None:
    """Abbreviated body (# ...) in narrative matches def signature → no error."""
    excerpt = "def foo(x):\n    return x * 2"
    narrative = _fenced("def foo(x):\n    # ...")
    result = validate_narrative_snippets(narrative, (_make_ref("mod.foo", excerpt),))
    assert result == []


def test_trailing_comment_after_signature_no_error() -> None:
    """Trailing comment after signature line is ignored → no error."""
    excerpt = "def foo(x):  # original"
    # narrative strips annotations — both have same param
    narrative = _fenced("def foo(x):  # description")
    result = validate_narrative_snippets(narrative, (_make_ref("mod.foo", excerpt),))
    assert result == []


def test_unknown_function_in_narrative_no_error() -> None:
    """Narrative references a function not in code_refs → lenient, no error."""
    narrative = _fenced("def totally_made_up(a, b, c):\n    pass")
    ref = _make_ref("mod.foo", "def foo(x): pass")
    result = validate_narrative_snippets(narrative, (ref,))
    assert result == []


def test_empty_code_refs_returns_no_errors() -> None:
    """Empty code_refs tuple → no errors regardless of narrative content."""
    narrative = _fenced("def foo(a, b):\n    pass")
    result = validate_narrative_snippets(narrative, ())
    assert result == []


def test_type_annotations_stripped_for_comparison() -> None:
    """Type annotations in both narrative and excerpt are stripped before comparison."""
    excerpt = "def foo(x: int, y: str) -> bool:\n    pass"
    # narrative omits annotations — should still match
    narrative = _fenced("def foo(x, y):\n    pass")
    result = validate_narrative_snippets(narrative, (_make_ref("mod.foo", excerpt),))
    assert result == []


@pytest.mark.parametrize(
    "narrative_sig,excerpt_sig,expect_error",
    [
        ("def fn(a, b, c):", "def fn(a, b, c):", False),
        ("def fn(a, c, b):", "def fn(a, b, c):", True),
        ("def fn(a):", "def fn(a, b):", True),
        ("def fn(a, b):", "def fn(a):", True),
    ],
)
def test_param_comparison_parametrized(
    narrative_sig: str, excerpt_sig: str, expect_error: bool
) -> None:
    """Parametrized check: param lists compared order-sensitively."""
    narrative = _fenced(f"{narrative_sig}\n    pass")
    excerpt = f"{excerpt_sig}\n    pass"
    result = validate_narrative_snippets(narrative, (_make_ref("mod.fn", excerpt),))
    if expect_error:
        assert len(result) == 1
    else:
        assert result == []
