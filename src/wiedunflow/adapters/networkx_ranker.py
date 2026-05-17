# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from typing import cast

import networkx as nx
import numpy as np

from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.ranked_graph import RankedGraph, RankedSymbol

_PAGERANK_ALPHA = 0.85
_PAGERANK_MAX_ITER = 100
_PAGERANK_TOL = 1.0e-6


def _pagerank_power(
    digraph: nx.DiGraph,
    alpha: float = _PAGERANK_ALPHA,
    max_iter: int = _PAGERANK_MAX_ITER,
    tol: float = _PAGERANK_TOL,
) -> dict[str, float]:
    """Numpy dense-matrix power-iteration PageRank.

    Replaces the pure-Python nested loop that iterated over every predecessor
    per node per iteration (O(n^2) in dense graphs, ~5 s for 500 nodes).  The
    numpy matrix formulation reduces the inner loop to a single ``@`` matrix
    multiply, bringing 500 nodes down to <100 ms (>50x speedup).

    Determinism: node ordering is fixed by ``list(digraph.nodes())`` which
    preserves NetworkX insertion order.  Two calls on the same ``DiGraph``
    object will always produce bit-for-bit identical results.

    Dangling nodes (out-degree == 0) have their column set to ``1/n`` so they
    contribute uniform teleportation rather than silently leaking rank mass
    (standard PageRank dangling-node fix).

    Args:
        digraph: Directed graph whose nodes are string symbol names.
        alpha: Damping factor (teleportation probability = 1 - alpha).
        max_iter: Maximum number of power-iteration steps.
        tol: Convergence threshold (L1 norm of rank delta).

    Returns:
        Dictionary mapping each node name to its PageRank score.
        Scores sum to approximately 1.0.
    """
    nodes = list(digraph.nodes())
    n = len(nodes)
    if n == 0:
        return {}

    idx: dict[str, int] = {node: i for i, node in enumerate(nodes)}

    # Build column-stochastic transition matrix where matrix[dst, src] = 1/out_degree(src).
    # Using lowercase `adj` (adjacency) to comply with naming conventions.
    adj = np.zeros((n, n), dtype=np.float64)
    for src, dst in digraph.edges():
        adj[idx[dst], idx[src]] = 1.0

    # Normalise each column by out-degree; dangling columns (sum == 0) become
    # uniform so rank mass is redistributed rather than absorbed.
    col_sums = adj.sum(axis=0)
    dangling_mask = col_sums == 0.0
    col_sums[dangling_mask] = 1.0  # avoid division-by-zero
    adj /= col_sums
    # Dangling columns get uniform teleportation weight (1/n per destination).
    adj[:, dangling_mask] = 1.0 / n

    v = np.full(n, 1.0 / n, dtype=np.float64)
    teleport = np.full(n, (1.0 - alpha) / n, dtype=np.float64)

    for _ in range(max_iter):
        v_new = alpha * (adj @ v) + teleport
        if np.linalg.norm(v_new - v, ord=1) < tol:
            v = v_new
            break
        v = v_new

    return {node: float(v[idx[node]]) for node in nodes}


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

        # --- PageRank (numpy dense-matrix power iteration) -------------------
        ranks: dict[str, float] = _pagerank_power(digraph, alpha=0.85)

        # --- Cycle detection --------------------------------------------------
        # Fast-path: if every SCC is trivial (1 node, no self-loop), the graph
        # is a pure DAG.  ``nx.simple_cycles`` is still O(n+m) for a DAG but
        # allocates a full DFS stack; skipping it saves 10-50 ms on large DAGs
        # typical of Python projects.
        # Important: a self-loop A->A is a 1-node SCC, so SCCs==nodes is not
        # sufficient; we must also confirm no self-edges exist.
        n_sccs = nx.number_strongly_connected_components(digraph)
        n_nodes = digraph.number_of_nodes()
        is_dag = n_sccs == n_nodes and not any(
            digraph.has_edge(node, node) for node in digraph.nodes()
        )
        if is_dag:
            # All SCCs trivial and no self-loops -> pure DAG, cycle-free.
            has_cycles = False
            cycle_groups: tuple[tuple[str, ...], ...] = ()
        else:
            raw_cycles: list[list[str]] = list(nx.simple_cycles(digraph))
            has_cycles = bool(raw_cycles)
            cycle_groups = tuple(tuple(c) for c in raw_cycles) if has_cycles else ()

        # --- Louvain community detection -------------------------------------
        # louvain_communities operates on an undirected graph; seed ensures
        # deterministic output across multiple .rank() calls.
        undirected: nx.Graph = digraph.to_undirected()
        raw_communities: list[set[str]] = cast(
            "list[set[str]]",
            nx.community.louvain_communities(undirected, seed=42),
        )
        communities: tuple[frozenset[str], ...] = tuple(frozenset(c) for c in raw_communities)

        # Build node -> community_id mapping (index into communities tuple).
        community_id_of: dict[str, int] = {}
        for community_idx, community in enumerate(communities):
            for member in community:
                community_id_of[member] = community_idx

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
