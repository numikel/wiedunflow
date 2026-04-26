# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import cast

import networkx as nx

from codeguide.entities.call_graph import CallGraph
from codeguide.entities.ranked_graph import RankedGraph, RankedSymbol

_PAGERANK_ALPHA = 0.85
_PAGERANK_MAX_ITER = 100
_PAGERANK_TOL = 1.0e-6


def _pagerank_power(
    digraph: nx.DiGraph,
    alpha: float = _PAGERANK_ALPHA,
    max_iter: int = _PAGERANK_MAX_ITER,
    tol: float = _PAGERANK_TOL,
) -> dict[str, float]:
    """Pure-Python power-iteration PageRank (no numpy/scipy required).

    Equivalent to ``nx.pagerank(digraph, alpha=alpha)`` for the purposes of
    ordering symbols by structural importance.  Avoids the scipy dependency
    that NetworkX 3.6+ requires for its built-in implementation.

    Args:
        digraph: Directed graph whose nodes are string symbol names.
        alpha: Damping factor (teleportation probability = 1 - alpha).
        max_iter: Maximum number of power-iteration steps.
        tol: Convergence threshold (L1 norm of rank delta per node).

    Returns:
        Dictionary mapping each node name to its PageRank score.
        Scores sum to approximately 1.0.
    """
    nodes = list(digraph.nodes())
    n = len(nodes)
    if n == 0:
        return {}

    # Uniform initial distribution.
    rank: dict[str, float] = {node: 1.0 / n for node in nodes}

    # Pre-compute out-degree for dangling-node handling.
    out_degree = {node: digraph.out_degree(node) for node in nodes}
    dangling = [node for node in nodes if out_degree[node] == 0]

    for _ in range(max_iter):
        prev = rank.copy()

        # Dangling nodes contribute uniformly to all nodes.
        dangling_sum = alpha * sum(prev[node] for node in dangling) / n

        new_rank: dict[str, float] = {}
        for node in nodes:
            # Sum of alpha * (predecessor's rank / predecessor's out-degree).
            incoming = sum(
                alpha * prev[pred] / out_degree[pred]
                for pred in digraph.predecessors(node)
                if out_degree[pred] > 0
            )
            new_rank[node] = incoming + dangling_sum + (1.0 - alpha) / n

        # Normalise to correct floating-point drift.
        total = sum(new_rank.values())
        new_rank = {node: v / total for node, v in new_rank.items()}

        # Check convergence.
        err = sum(abs(new_rank[node] - prev[node]) for node in nodes)
        rank = new_rank
        if err < n * tol:
            break

    return rank


class NetworkxRanker:
    """Production :class:`Ranker` backed by NetworkX 3.x.

    Implements the full Stage 3 graph-ranking pipeline:
    - PageRank (alpha=0.85) for node importance scoring.
    - Louvain community detection (seed=42, deterministic).
    - SCC-condensed topological sort (handles cyclic graphs).
    - Simple-cycle enumeration for narrative ``Cycles detected`` section.
    """

    def rank(self, graph: CallGraph) -> RankedGraph:
        """Compute PageRank, Louvain communities, and SCC-condensed topological order.

        Args:
            graph: Resolved call graph from Stage 2.  ``graph.resolution_stats``
                must be set (i.e. Resolver has already processed the raw graph).

        Returns:
            :class:`RankedGraph` with all ranking metadata populated.
        """
        # --- Empty graph fast-path -------------------------------------------
        if not graph.nodes:
            return RankedGraph(
                ranked_symbols=(),
                communities=(),
                topological_order=(),
                has_cycles=False,
                cycle_groups=(),
            )

        # --- Build DiGraph ----------------------------------------------------
        digraph: nx.DiGraph = nx.DiGraph()
        digraph.add_nodes_from(s.name for s in graph.nodes)
        digraph.add_edges_from(graph.edges)

        # --- PageRank (pure-Python power iteration) ---------------------------
        # NetworkX 3.6+ requires scipy for nx.pagerank(); we use our own
        # power-iteration implementation to avoid the numpy/scipy dependency.
        ranks: dict[str, float] = _pagerank_power(digraph, alpha=0.85)

        # --- Cycle detection --------------------------------------------------
        raw_cycles: list[list[str]] = list(nx.simple_cycles(digraph))
        has_cycles = bool(raw_cycles)
        cycle_groups: tuple[tuple[str, ...], ...] = (
            tuple(tuple(c) for c in raw_cycles) if has_cycles else ()
        )

        # --- Louvain community detection -------------------------------------
        # louvain_communities operates on an undirected graph; seed ensures
        # deterministic output across multiple .rank() calls.
        undirected: nx.Graph = digraph.to_undirected()
        raw_communities: list[set[str]] = cast(
            "list[set[str]]",
            nx.community.louvain_communities(undirected, seed=42),
        )
        communities: tuple[frozenset[str], ...] = tuple(frozenset(c) for c in raw_communities)

        # Build node → community_id mapping (index into communities tuple).
        community_id_of: dict[str, int] = {}
        for idx, community in enumerate(communities):
            for member in community:
                community_id_of[member] = idx

        # --- SCC-condensed topological order ---------------------------------
        # nx.topological_sort raises on cyclic graphs, so we always condense
        # first.  On a DAG, each SCC is a single node (trivial condensation).
        scc_dag: nx.DiGraph = cast("nx.DiGraph", nx.condensation(digraph))
        # topological_sort on the condensed DAG is always safe.
        scc_topo: list[int] = list(nx.topological_sort(scc_dag))
        topological_order_names: list[str] = []
        for scc_node in scc_topo:
            members: set[str] = cast("set[str]", scc_dag.nodes[scc_node]["members"])
            # Within each SCC, sort by PageRank descending (stable tie-break).
            sorted_members = sorted(members, key=lambda n: ranks.get(n, 0.0), reverse=True)
            topological_order_names.extend(sorted_members)

        topological_order: tuple[str, ...] = tuple(topological_order_names)

        # --- Build RankedSymbol tuple ----------------------------------------
        # Use topological_order as the canonical iteration order so that the
        # invariant "every name in topological_order is in ranked_symbols" holds.
        all_node_names = {s.name for s in graph.nodes}
        # Nodes not reached by condensation (shouldn't happen, but defensive):
        remaining = [n for n in all_node_names if n not in set(topological_order_names)]
        full_order = list(topological_order_names) + remaining

        ranked_symbols: tuple[RankedSymbol, ...] = tuple(
            RankedSymbol(
                symbol_name=name,
                pagerank_score=ranks.get(name, 0.0),
                community_id=community_id_of.get(name, 0),
            )
            for name in full_order
        )

        return RankedGraph(
            ranked_symbols=ranked_symbols,
            communities=communities,
            topological_order=topological_order,
            has_cycles=has_cycles,
            cycle_groups=cycle_groups,
        )
