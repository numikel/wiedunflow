# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

import pytest

from wiedunflow.adapters.networkx_ranker import NetworkxRanker
from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.ranked_graph import RankedGraph
from wiedunflow.entities.resolution_stats import ResolutionStats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _symbol(name: str) -> CodeSymbol:
    """Create a minimal CodeSymbol with the given name."""
    return CodeSymbol(name=name, kind="function", file_path=Path("mod.py"), lineno=1)


def _graph(names: list[str], edges: list[tuple[str, str]] | None = None) -> CallGraph:
    """Build a resolved CallGraph with resolution_stats so edge validation runs."""
    nodes = tuple(_symbol(n) for n in names)
    edge_tuples: tuple[tuple[str, str], ...] = tuple(edges or [])
    # Provide resolution_stats so the edge-reference validator runs.
    stats = ResolutionStats(resolved_pct=100.0, uncertain_count=0, unresolved_count=0)
    return CallGraph(nodes=nodes, edges=edge_tuples, resolution_stats=stats)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNetworkxRanker:
    """Unit tests for NetworkxRanker."""

    def setup_method(self) -> None:
        self.ranker = NetworkxRanker()

    # --- Empty graph ---------------------------------------------------------

    def test_empty_graph_returns_empty_ranked_graph(self) -> None:
        graph = _graph([])
        result = self.ranker.rank(graph)
        assert result.ranked_symbols == ()
        assert result.communities == ()
        assert result.topological_order == ()
        assert result.has_cycles is False
        assert result.cycle_groups == ()

    # --- Single-node graph ---------------------------------------------------

    def test_single_node_graph(self) -> None:
        graph = _graph(["A"])
        result = self.ranker.rank(graph)
        assert len(result.ranked_symbols) == 1
        sym = result.ranked_symbols[0]
        assert sym.symbol_name == "A"
        # PageRank on a 1-node graph sums to 1.0.
        assert sym.pagerank_score == pytest.approx(1.0, abs=0.01)
        assert len(result.communities) == 1
        assert "A" in result.communities[0]

    # --- Linear 3-node DAG ---------------------------------------------------

    def test_linear_dag_topological_order(self) -> None:
        """A → B → C: C has no successors (leaf), A is the root."""
        graph = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = self.ranker.rank(graph)
        assert result.has_cycles is False
        assert result.cycle_groups == ()
        # Topological sort: A before B before C.
        topo = result.topological_order
        assert topo.index("A") < topo.index("B") < topo.index("C")

    def test_linear_dag_pagerank_sum(self) -> None:
        graph = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = self.ranker.rank(graph)
        total = sum(s.pagerank_score for s in result.ranked_symbols)
        assert total == pytest.approx(1.0, abs=0.01)

    def test_linear_dag_contains_all_nodes(self) -> None:
        graph = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = self.ranker.rank(graph)
        names = {s.symbol_name for s in result.ranked_symbols}
        assert names == {"A", "B", "C"}

    # --- Single cycle --------------------------------------------------------

    def test_single_cycle_has_cycles_true(self) -> None:
        graph = _graph(["A", "B"], [("A", "B"), ("B", "A")])
        result = self.ranker.rank(graph)
        assert result.has_cycles is True
        assert len(result.cycle_groups) >= 1

    def test_single_cycle_group_membership(self) -> None:
        """cycle_groups must include a group containing both A and B."""
        graph = _graph(["A", "B"], [("A", "B"), ("B", "A")])
        result = self.ranker.rank(graph)
        found = any(
            set(group) == {"A", "B"} or ("A" in group and "B" in group)
            for group in result.cycle_groups
        )
        assert found, f"Expected A and B in a cycle group; got {result.cycle_groups}"

    # --- Self-loop -----------------------------------------------------------

    def test_self_loop_is_cycle(self) -> None:
        graph = _graph(["A"], [("A", "A")])
        result = self.ranker.rank(graph)
        assert result.has_cycles is True
        assert len(result.cycle_groups) >= 1

    # --- Disconnected graph (2 components) -----------------------------------

    def test_disconnected_graph_multiple_communities(self) -> None:
        """Two isolated cliques should end up in at least 2 communities."""
        graph = _graph(
            ["A", "B", "C", "D"],
            [("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")],
        )
        result = self.ranker.rank(graph)
        assert len(result.communities) >= 2

    # --- PageRank sum --------------------------------------------------------

    def test_pagerank_sum_approximately_one(self) -> None:
        """PageRank scores must sum to ≈1.0 for any non-empty graph."""
        graph = _graph(["X", "Y", "Z", "W"], [("X", "Y"), ("Y", "Z"), ("Z", "X"), ("X", "W")])
        result = self.ranker.rank(graph)
        total = sum(s.pagerank_score for s in result.ranked_symbols)
        assert total == pytest.approx(1.0, abs=0.01)

    # --- Determinism ---------------------------------------------------------

    def test_determinism_same_community_ids(self) -> None:
        """Two calls on the same graph must produce identical community IDs."""
        graph = _graph(
            ["A", "B", "C", "D"],
            [("A", "B"), ("B", "C"), ("C", "A"), ("D", "A")],
        )
        result1 = self.ranker.rank(graph)
        result2 = self.ranker.rank(graph)
        ids1 = {s.symbol_name: s.community_id for s in result1.ranked_symbols}
        ids2 = {s.symbol_name: s.community_id for s in result2.ranked_symbols}
        assert ids1 == ids2

    def test_determinism_same_topological_order(self) -> None:
        graph = _graph(
            ["A", "B", "C", "D"],
            [("A", "B"), ("B", "C"), ("C", "A"), ("D", "A")],
        )
        result1 = self.ranker.rank(graph)
        result2 = self.ranker.rank(graph)
        assert result1.topological_order == result2.topological_order

    # --- Invariant checks ----------------------------------------------------

    def test_topological_order_covers_all_ranked_symbols(self) -> None:
        """Every ranked symbol must appear in topological_order."""
        graph = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = self.ranker.rank(graph)
        ranked_names = {s.symbol_name for s in result.ranked_symbols}
        topo_names = set(result.topological_order)
        assert ranked_names == topo_names

    def test_community_members_are_ranked_symbols(self) -> None:
        """Every community member must appear in ranked_symbols."""
        graph = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = self.ranker.rank(graph)
        ranked_names = {s.symbol_name for s in result.ranked_symbols}
        for community in result.communities:
            for member in community:
                assert member in ranked_names

    def test_result_is_valid_ranked_graph(self) -> None:
        """RankedGraph Pydantic validators must all pass (no ValidationError)."""
        graph = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result: RankedGraph = self.ranker.rank(graph)
        # If validators fail, Pydantic raises ValidationError at construction time.
        assert isinstance(result, RankedGraph)
