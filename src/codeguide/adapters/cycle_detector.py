# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import networkx as nx

from codeguide.entities.call_graph import CallGraph


def detect_cycles(graph: CallGraph) -> tuple[tuple[str, ...], ...]:
    """Return all simple cycles in *graph* as tuples of node names.

    Uses ``networkx.simple_cycles`` on a ``DiGraph`` built from
    ``graph.nodes`` and ``graph.edges``.

    networkx 3.x returns each cycle **without** the duplicated closing node:
    the cycle A → B → A comes back as ``("A", "B")``, not ``("A", "B", "A")``.

    Args:
        graph: Resolved or raw ``CallGraph`` from the analysis stage.

    Returns:
        A tuple of cycles; each cycle is itself a tuple of node-name strings.
        Returns an empty tuple when no cycles exist or the graph is empty.
    """
    g: nx.DiGraph[str] = nx.DiGraph()

    # Add all known nodes first so isolated nodes are represented.
    for symbol in graph.nodes:
        g.add_node(symbol.name)

    for caller, callee in graph.edges:
        g.add_edge(caller, callee)

    return tuple(tuple(cycle) for cycle in nx.simple_cycles(g))
