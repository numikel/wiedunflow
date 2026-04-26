# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for compute_doc_coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.use_cases.doc_coverage import compute_doc_coverage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sym(name: str, docstring: str | None) -> CodeSymbol:
    return CodeSymbol(
        name=name,
        kind="function",
        file_path=Path("mod.py"),
        lineno=1,
        docstring=docstring,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_low_coverage_10_percent() -> None:
    """1 out of 10 symbols documented → ratio=0.1, is_low=True."""
    symbols = [_sym("s1", "Documented.")] + [_sym(f"s{i}", None) for i in range(2, 11)]
    coverage = compute_doc_coverage(symbols)
    assert coverage.total_symbols == 10
    assert coverage.symbols_with_docstring == 1
    assert coverage.ratio == pytest.approx(0.1)
    assert coverage.is_low is True


def test_medium_coverage_50_percent() -> None:
    """5 out of 10 symbols documented → ratio=0.5, is_low=False."""
    symbols = [_sym(f"doc_{i}", "Documented.") for i in range(5)] + [
        _sym(f"nodoc_{i}", None) for i in range(5)
    ]
    coverage = compute_doc_coverage(symbols)
    assert coverage.total_symbols == 10
    assert coverage.symbols_with_docstring == 5
    assert coverage.ratio == pytest.approx(0.5)
    assert coverage.is_low is False


def test_empty_symbols_full_coverage() -> None:
    """No symbols → ratio=1.0, is_low=False (nothing to document)."""
    coverage = compute_doc_coverage([])
    assert coverage.total_symbols == 0
    assert coverage.symbols_with_docstring == 0
    assert coverage.ratio == pytest.approx(1.0)
    assert coverage.is_low is False


def test_all_documented() -> None:
    """All 5 symbols documented → ratio=1.0, is_low=False."""
    symbols = [_sym(f"s{i}", f"Docstring for s{i}.") for i in range(5)]
    coverage = compute_doc_coverage(symbols)
    assert coverage.total_symbols == 5
    assert coverage.symbols_with_docstring == 5
    assert coverage.ratio == pytest.approx(1.0)
    assert coverage.is_low is False


def test_whitespace_only_docstring_not_counted() -> None:
    """Symbols with whitespace-only docstrings are treated as undocumented."""
    symbols = [
        _sym("s1", "Real docstring."),
        _sym("s2", "   "),
        _sym("s3", "\t\n"),
    ]
    coverage = compute_doc_coverage(symbols)
    assert coverage.symbols_with_docstring == 1
    assert coverage.ratio == pytest.approx(1 / 3)
