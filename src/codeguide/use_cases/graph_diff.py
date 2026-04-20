# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Graph diff utilities — pure functions, zero I/O.

Used by the caching layer to decide whether a structural change in the ranked
graph warrants regenerating the full lesson plan (full regen) or whether the
cached plan can be reused with only incremental lesson updates.

``compute_structural_change`` compares the symmetric difference between the
top-N symbols of two :class:`~codeguide.entities.ranked_graph.RankedGraph`
instances and returns a ratio in ``[0, 1]``.  ``is_structural_change`` wraps it
with a configurable threshold (default ``0.20`` — 20 % change triggers regen).
"""

from __future__ import annotations

from codeguide.entities.ranked_graph import RankedGraph


def compute_structural_change(
    prev: RankedGraph | None,
    curr: RankedGraph,
    top_n: int = 20,
) -> float:
    """Return the structural change ratio between two ranked graphs.

    The ratio is ``symmetric_difference / (2 * top_n)`` — the proportion of
    the combined top-N population that changed.

    Special cases:
    - ``prev is None`` (no prior run) → ``1.0`` (full regen).
    - ``top_n == 0`` → ``0.0`` (no symbols to compare).

    Args:
        prev: Previous :class:`RankedGraph`, or ``None`` for a first run.
        curr: Current :class:`RankedGraph` to compare against *prev*.
        top_n: Number of top-PageRank symbols considered for the comparison.

    Returns:
        Float in ``[0.0, 1.0]`` representing the proportion of change.
    """
    if prev is None:
        return 1.0
    if top_n == 0:
        return 0.0

    prev_top = _top_symbols(prev, top_n)
    curr_top = _top_symbols(curr, top_n)
    diff = prev_top.symmetric_difference(curr_top)
    return len(diff) / (2 * top_n)


def is_structural_change(
    prev: RankedGraph | None,
    curr: RankedGraph,
    threshold: float = 0.20,
    top_n: int = 20,
) -> bool:
    """Return ``True`` when the structural change ratio meets or exceeds *threshold*.

    Args:
        prev: Previous :class:`RankedGraph`, or ``None`` for a first run.
        curr: Current :class:`RankedGraph`.
        threshold: Ratio at-or-above which a structural change is declared
            (default ``0.20``).
        top_n: Number of top symbols considered (forwarded to
            :func:`compute_structural_change`).

    Returns:
        ``True`` when regeneration of the lesson plan is warranted.
    """
    return compute_structural_change(prev, curr, top_n) >= threshold


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _top_symbols(graph: RankedGraph, top_n: int) -> frozenset[str]:
    """Return a frozenset of the *top_n* symbol names ranked by PageRank.

    Args:
        graph: Ranked graph from which to extract top symbols.
        top_n: Maximum number of symbols to include.

    Returns:
        Frozenset of symbol names (fewer than *top_n* when the graph is small).
    """
    sorted_syms = sorted(
        graph.ranked_symbols,
        key=lambda s: s.pagerank_score,
        reverse=True,
    )
    return frozenset(s.symbol_name for s in sorted_syms[:top_n])
