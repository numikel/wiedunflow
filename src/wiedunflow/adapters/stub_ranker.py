# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from codeguide.entities.call_graph import CallGraph
from codeguide.entities.ranked_graph import RankedGraph, RankedSymbol


class StubRanker:
    """Deterministic :class:`Ranker` stub used by the walking skeleton tests.

    Assigns a flat PageRank score (1/N) to every node, lumps everything into a
    single community, and preserves the node order as the topological order.
    The real networkx-backed adapter lands in Sprint 2 Track C.
    """

    def rank(self, graph: CallGraph) -> RankedGraph:
        """Build a trivial :class:`RankedGraph` from the resolved call graph.

        Args:
            graph: Resolved call graph produced by the Resolver stage.
        """
        node_count = len(graph.nodes)
        flat_score = 1.0 / node_count if node_count else 0.0
        ranked_symbols = tuple(
            RankedSymbol(symbol_name=n.name, pagerank_score=flat_score, community_id=0)
            for n in graph.nodes
        )
        member_names = frozenset(n.name for n in graph.nodes)
        communities: tuple[frozenset[str], ...] = (member_names,) if member_names else ()
        topological_order = tuple(n.name for n in graph.nodes)
        return RankedGraph(
            ranked_symbols=ranked_symbols,
            communities=communities,
            topological_order=topological_order,
            has_cycles=False,
            cycle_groups=(),
        )
