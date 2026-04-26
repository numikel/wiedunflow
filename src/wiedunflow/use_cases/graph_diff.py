# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Graph diff utilities — pure functions, zero I/O.

Used by the caching layer to decide whether a structural change in the ranked
graph warrants regenerating the full lesson plan (full regen) or whether the
cached plan can be reused with only incremental lesson updates.

Two families of functions are provided:

1. **RankedGraph-based** (``compute_structural_change`` / ``is_structural_change``):
   operate on live :class:`~codeguide.entities.ranked_graph.RankedGraph` objects
   and are used during the pipeline run before any persistence occurs.

2. **PageRankSnapshot-based** (``pagerank_diff`` / ``should_regenerate_manifest``):
   operate on the lightweight :class:`~codeguide.entities.cache_entry.PageRankSnapshot`
   persisted in the SQLite cache (ADR-0008), allowing the caching layer to compare
   the current run against the previous run without reconstructing full graph objects.

Both families apply the same 20 % symmetric-difference threshold.
"""

from __future__ import annotations

from codeguide.entities.cache_entry import PageRankSnapshot
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
    - ``prev is None`` (no prior run) -> ``1.0`` (full regen).
    - ``top_n == 0`` -> ``0.0`` (no symbols to compare).

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


# ---------------------------------------------------------------------------
# PageRankSnapshot-based diff (US-024) -- operates on persisted snapshots
# ---------------------------------------------------------------------------


def pagerank_diff(prev: PageRankSnapshot, curr: PageRankSnapshot) -> float:
    """Return the fraction of top-N symbols that changed between two snapshots.

    The ratio is ``|symmetric_difference| / (2 * max(|prev_top|, |curr_top|))``.
    This is the same formula used by :func:`compute_structural_change` but
    operates on cached :class:`PageRankSnapshot` objects rather than live
    :class:`RankedGraph` instances.

    Special cases:
    - Both snapshots have zero top symbols -> ``0.0``.
    - Both snapshots have identical top-N sets -> ``0.0``.
    - Completely disjoint top-N sets -> ``1.0``.

    Args:
        prev: PageRank snapshot from a previous pipeline run (loaded from the
            SQLite cache).
        curr: PageRank snapshot produced by the current run.

    Returns:
        Float in ``[0.0, 1.0]`` representing the proportion of change.
    """
    prev_top = prev.top_n_set()
    curr_top = curr.top_n_set()
    denom = max(len(prev_top), len(curr_top))
    if denom == 0:
        return 0.0
    symmetric_diff = (prev_top - curr_top) | (curr_top - prev_top)
    # Divide by 2 * denom to stay in [0, 1] even when prev and curr have
    # completely disjoint sets (each contributes |denom| to the symmetric diff).
    return len(symmetric_diff) / (2 * denom)


def should_regenerate_manifest(diff_ratio: float, threshold: float = 0.20) -> bool:
    """Return ``True`` when the diff ratio meets or exceeds *threshold*.

    Wraps :func:`pagerank_diff` result with the 20 % threshold policy defined
    in ADR-0008.  A ratio *strictly greater than* the threshold triggers full
    manifest regeneration; at exactly the threshold the manifest is regenerated
    (``>=`` semantics, consistent with :func:`is_structural_change`).

    Args:
        diff_ratio: Float in ``[0.0, 1.0]`` from :func:`pagerank_diff`.
        threshold: Regeneration threshold (default ``0.20``).

    Returns:
        ``True`` when regeneration is warranted.
    """
    return diff_ratio >= threshold
