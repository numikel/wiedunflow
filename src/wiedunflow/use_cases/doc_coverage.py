# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Documentation coverage use case — Stage 2 post-processing.

Computes a :class:`~wiedunflow.entities.doc_coverage.DocCoverage` summary from
the list of symbols produced by the analysis stage.  The result drives the
low-coverage warning banner injected into the generated HTML by the build stage.
"""

from __future__ import annotations

from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.doc_coverage import DocCoverage


def compute_doc_coverage(symbols: list[CodeSymbol]) -> DocCoverage:
    """Compute documentation coverage metrics over *symbols*.

    An empty repository (``symbols == []``) is treated as fully covered
    (``ratio = 1.0``, ``is_low = False``) — there is nothing to document.

    A symbol is considered *documented* when its ``docstring`` field is
    non-``None`` and contains at least one non-whitespace character.

    Args:
        symbols: Symbols extracted by the analysis stage.

    Returns:
        A frozen :class:`~wiedunflow.entities.doc_coverage.DocCoverage` instance.
    """
    total = len(symbols)
    with_doc = sum(1 for s in symbols if s.docstring is not None and s.docstring.strip())
    ratio = (with_doc / total) if total else 1.0
    return DocCoverage(
        total_symbols=total,
        symbols_with_docstring=with_doc,
        ratio=ratio,
        # Threshold 0.20: fewer than 1 in 5 symbols documented warrants a warning.
        is_low=ratio < 0.20 and total > 0,  # noqa: PLR2004
    )
