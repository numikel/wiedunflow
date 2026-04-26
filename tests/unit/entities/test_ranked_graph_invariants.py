# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import pytest
from pydantic import ValidationError

from wiedunflow.entities import RankedGraph, RankedSymbol


def _sym(name: str, score: float = 0.1, community: int = 0) -> RankedSymbol:
    return RankedSymbol(symbol_name=name, pagerank_score=score, community_id=community)


def test_minimal_valid_instance():
    graph = RankedGraph(
        ranked_symbols=(_sym("a"), _sym("b")),
        communities=(frozenset({"a", "b"}),),
        topological_order=("a", "b"),
        has_cycles=False,
    )
    assert graph.cycle_groups == ()


def test_ranked_symbol_negative_pagerank_rejected():
    with pytest.raises(ValidationError, match="pagerank_score must be >= 0"):
        RankedSymbol(symbol_name="a", pagerank_score=-0.1, community_id=0)


def test_ranked_symbol_negative_community_rejected():
    with pytest.raises(ValidationError, match="community_id must be >= 0"):
        RankedSymbol(symbol_name="a", pagerank_score=0.1, community_id=-1)


def test_topological_order_must_reference_known_symbols():
    with pytest.raises(ValidationError, match="topological_order references unknown symbol"):
        RankedGraph(
            ranked_symbols=(_sym("a"),),
            communities=(frozenset({"a"}),),
            topological_order=("a", "ghost"),
            has_cycles=False,
        )


def test_community_members_must_be_known_symbols():
    with pytest.raises(ValidationError, match="contains unknown symbol"):
        RankedGraph(
            ranked_symbols=(_sym("a"),),
            communities=(frozenset({"a", "ghost"}),),
            topological_order=("a",),
            has_cycles=False,
        )


def test_has_cycles_true_requires_cycle_groups():
    with pytest.raises(ValidationError, match="has_cycles=True requires"):
        RankedGraph(
            ranked_symbols=(_sym("a"), _sym("b")),
            communities=(frozenset({"a", "b"}),),
            topological_order=("a", "b"),
            has_cycles=True,
            cycle_groups=(),
        )


def test_has_cycles_false_forbids_cycle_groups():
    with pytest.raises(ValidationError, match="has_cycles=False forbids"):
        RankedGraph(
            ranked_symbols=(_sym("a"), _sym("b")),
            communities=(frozenset({"a", "b"}),),
            topological_order=("a", "b"),
            has_cycles=False,
            cycle_groups=(("a", "b"),),
        )


def test_cyclic_graph_accepted_with_matching_groups():
    graph = RankedGraph(
        ranked_symbols=(_sym("a"), _sym("b")),
        communities=(frozenset({"a", "b"}),),
        topological_order=("a", "b"),
        has_cycles=True,
        cycle_groups=(("a", "b"),),
    )
    assert graph.has_cycles is True


def test_is_frozen():
    graph = RankedGraph(
        ranked_symbols=(_sym("a"),),
        communities=(frozenset({"a"}),),
        topological_order=("a",),
        has_cycles=False,
    )
    with pytest.raises(ValidationError):
        graph.has_cycles = True  # type: ignore[misc]
