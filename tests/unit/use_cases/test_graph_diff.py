# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for graph_diff pure functions."""

from __future__ import annotations

import pytest

from codeguide.entities.cache_entry import PageRankSnapshot
from codeguide.entities.ranked_graph import RankedGraph, RankedSymbol
from codeguide.use_cases.graph_diff import (
    compute_structural_change,
    is_structural_change,
    pagerank_diff,
    should_regenerate_manifest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ranked_graph(names_scores: list[tuple[str, float]]) -> RankedGraph:
    """Build a minimal RankedGraph from (name, pagerank) pairs.

    All symbols are placed in community 0; topological order mirrors name order.
    """
    ranked_symbols = tuple(
        RankedSymbol(symbol_name=name, pagerank_score=score, community_id=0)
        for name, score in names_scores
    )
    return RankedGraph(
        ranked_symbols=ranked_symbols,
        communities=(frozenset(n for n, _ in names_scores),) if names_scores else (),
        topological_order=tuple(n for n, _ in names_scores),
        has_cycles=False,
    )


def _uniform_graph(names: list[str]) -> RankedGraph:
    """Build a RankedGraph with equal PageRank scores across all symbols."""
    score = 1.0 / len(names) if names else 0.0
    return _make_ranked_graph([(n, score) for n in names])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_prev_none_returns_1_0() -> None:
    """When prev is None (first run), structural change is 1.0."""
    curr = _uniform_graph([f"sym_{i}" for i in range(20)])
    assert compute_structural_change(None, curr) == pytest.approx(1.0)


def test_prev_none_is_structural_change_true() -> None:
    """First run always triggers a structural change."""
    curr = _uniform_graph([f"sym_{i}" for i in range(20)])
    assert is_structural_change(None, curr) is True


def test_identical_top20_returns_0_0() -> None:
    """When prev and curr share the same top-20, ratio is 0.0."""
    names = [f"sym_{i}" for i in range(20)]
    prev = _uniform_graph(names)
    curr = _uniform_graph(names)
    assert compute_structural_change(prev, curr, top_n=20) == pytest.approx(0.0)
    assert is_structural_change(prev, curr) is False


def test_4_symbols_changed_out_of_20_below_threshold() -> None:
    """4 symbols differ (2 added, 2 removed) -> ratio=0.10, is_structural_change=False.

    Symmetric difference = {new_0, new_1, old_18, old_19} -> size 4.
    ratio = 4 / (2 * 20) = 0.10, below threshold 0.20.
    """
    shared = [f"sym_{i}" for i in range(16)]
    prev_extra = ["old_18", "old_19"]
    curr_extra = ["new_0", "new_1"]

    # Assign higher scores to shared symbols so they're in the top-16 of both
    prev_names_scores = [(n, 1.0) for n in shared] + [(n, 0.5) for n in prev_extra]
    curr_names_scores = [(n, 1.0) for n in shared] + [(n, 0.5) for n in curr_extra]

    prev = _make_ranked_graph(prev_names_scores)
    curr = _make_ranked_graph(curr_names_scores)

    ratio = compute_structural_change(prev, curr, top_n=18)
    # top-18: 16 shared + 2 extras each side -> symmetric diff = 4 -> 4/(2*18)=0.111
    # Let's use top_n=20 but with 18 symbols total -> top_n caps at available symbols
    # Use the exact scenario: 16 shared + 2 unique per side, top_n=20 (all 18 taken)
    # symmetric diff = 4, denominator = 2*20 = 40, ratio = 0.10
    ratio = compute_structural_change(prev, curr, top_n=20)
    assert ratio == pytest.approx(4 / 40)
    assert is_structural_change(prev, curr, top_n=20) is False


def test_8_symbols_changed_out_of_20_meets_threshold() -> None:
    """8 symbols differ (4 added, 4 removed) -> ratio=0.20, is_structural_change=True.

    Symmetric difference size = 8.
    ratio = 8 / (2 * 20) = 0.20, exactly at threshold -> True (>= 0.20).
    """
    shared = [f"sym_{i}" for i in range(12)]
    prev_extra = [f"old_{i}" for i in range(4)]
    curr_extra = [f"new_{i}" for i in range(4)]

    prev_names_scores = [(n, 1.0) for n in shared] + [(n, 0.5) for n in prev_extra]
    curr_names_scores = [(n, 1.0) for n in shared] + [(n, 0.5) for n in curr_extra]

    prev = _make_ranked_graph(prev_names_scores)
    curr = _make_ranked_graph(curr_names_scores)

    # top_n=20, only 16 symbols available in each graph -> top 16 are taken
    # prev top-16 = 12 shared + 4 prev_extra; curr top-16 = 12 shared + 4 curr_extra
    # symmetric diff = 4 prev_extra + 4 curr_extra = 8
    # ratio = 8 / (2 * 20) = 0.20
    ratio = compute_structural_change(prev, curr, top_n=20)
    assert ratio == pytest.approx(8 / 40)
    assert is_structural_change(prev, curr, threshold=0.20, top_n=20) is True


# ---------------------------------------------------------------------------
# PageRankSnapshot-based diff (US-024) -- pagerank_diff + should_regenerate_manifest
# ---------------------------------------------------------------------------


def _make_snapshot(names: list[str], top_n: int = 20) -> PageRankSnapshot:
    """Build a PageRankSnapshot with uniform scores for the given symbol names."""
    score = 1.0 / len(names) if names else 0.0
    return PageRankSnapshot(ranks={n: score for n in names}, top_n=top_n)


def test_us_024_pagerank_diff_identical_snapshots_returns_0() -> None:
    """Two identical snapshots produce a diff ratio of 0.0."""
    names = [f"sym_{i}" for i in range(20)]
    snap = _make_snapshot(names)
    assert pagerank_diff(snap, snap) == pytest.approx(0.0)


def test_us_024_pagerank_diff_completely_disjoint_returns_1() -> None:
    """Completely disjoint top-N sets produce a diff ratio of 1.0."""
    prev = _make_snapshot([f"old_{i}" for i in range(20)])
    curr = _make_snapshot([f"new_{i}" for i in range(20)])
    # All 20 in prev are absent from curr and vice-versa -> |sym_diff| = 40
    # ratio = 40 / (2 * 20) = 1.0
    assert pagerank_diff(prev, curr) == pytest.approx(1.0)


def test_us_024_pagerank_diff_5_of_20_changed_above_threshold() -> None:
    """5 symbols changed out of 20 -> ratio ~0.25, triggers regenerate (US-024 AC2)."""
    shared = [f"sym_{i}" for i in range(15)]
    prev_extra = [f"old_{i}" for i in range(5)]
    curr_extra = [f"new_{i}" for i in range(5)]

    # Give shared higher scores so they dominate the top_n
    prev_ranks = {n: 1.0 for n in shared} | {n: 0.5 for n in prev_extra}
    curr_ranks = {n: 1.0 for n in shared} | {n: 0.5 for n in curr_extra}

    prev = PageRankSnapshot(ranks=prev_ranks, top_n=20)
    curr = PageRankSnapshot(ranks=curr_ranks, top_n=20)

    # top-20: all 20 symbols are taken (15 shared + 5 extras each)
    # symmetric diff = {old_0..4} | {new_0..4} = 10
    # ratio = 10 / (2 * 20) = 0.25
    ratio = pagerank_diff(prev, curr)
    assert ratio == pytest.approx(10 / 40)
    assert should_regenerate_manifest(ratio) is True


def test_us_024_pagerank_diff_3_of_20_changed_below_threshold() -> None:
    """3 symbols changed out of 20 -> ratio ~0.15, does NOT trigger regenerate (US-024 AC1)."""
    shared = [f"sym_{i}" for i in range(17)]
    prev_extra = [f"old_{i}" for i in range(3)]
    curr_extra = [f"new_{i}" for i in range(3)]

    prev_ranks = {n: 1.0 for n in shared} | {n: 0.5 for n in prev_extra}
    curr_ranks = {n: 1.0 for n in shared} | {n: 0.5 for n in curr_extra}

    prev = PageRankSnapshot(ranks=prev_ranks, top_n=20)
    curr = PageRankSnapshot(ranks=curr_ranks, top_n=20)

    # top-20: all 20 symbols taken; symmetric diff = {old_0..2} | {new_0..2} = 6
    # ratio = 6 / 40 = 0.15
    ratio = pagerank_diff(prev, curr)
    assert ratio == pytest.approx(6 / 40)
    assert should_regenerate_manifest(ratio) is False


def test_us_024_should_regenerate_manifest_at_threshold() -> None:
    """Ratio exactly at threshold triggers regeneration (>= semantics)."""
    assert should_regenerate_manifest(0.20) is True


def test_us_024_should_regenerate_manifest_below_threshold() -> None:
    """Ratio strictly below threshold does NOT trigger regeneration."""
    assert should_regenerate_manifest(0.19) is False


def test_us_024_should_regenerate_manifest_above_threshold() -> None:
    """Ratio above threshold triggers regeneration."""
    assert should_regenerate_manifest(0.50) is True


def test_us_024_pagerank_diff_empty_snapshots_returns_0() -> None:
    """Two empty snapshots (no symbols) produce 0.0 diff."""
    prev = PageRankSnapshot(ranks={}, top_n=20)
    curr = PageRankSnapshot(ranks={}, top_n=20)
    assert pagerank_diff(prev, curr) == pytest.approx(0.0)


def test_us_024_pagerank_diff_custom_threshold() -> None:
    """should_regenerate_manifest respects a custom threshold."""
    assert should_regenerate_manifest(0.30, threshold=0.25) is True
    assert should_regenerate_manifest(0.20, threshold=0.25) is False
