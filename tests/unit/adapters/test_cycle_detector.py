# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

import pytest

from wiedunflow.adapters.cycle_detector import detect_cycles
from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.resolution_stats import ResolutionStats

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATS = ResolutionStats(resolved_pct=100.0, uncertain_count=0, unresolved_count=0)


def _sym(name: str) -> CodeSymbol:
    """Build a minimal CodeSymbol for use in tests."""
    return CodeSymbol(
        name=name,
        kind="function",
        file_path=Path("module.py"),
        lineno=1,
    )


def _graph(names: list[str], edges: list[tuple[str, str]]) -> CallGraph:
    """Build a resolved CallGraph from node names and edges."""
    nodes = tuple(_sym(n) for n in names)
    return CallGraph(nodes=nodes, edges=tuple(edges), resolution_stats=_STATS)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_three_node_cycle() -> None:
    """A → B → C → A should produce exactly one 3-element cycle."""
    graph = _graph(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
    cycles = detect_cycles(graph)
    assert len(cycles) == 1
    cycle = set(cycles[0])
    assert cycle == {"A", "B", "C"}


def test_linear_chain_no_cycles() -> None:
    """A → B → C (no back edge) must produce no cycles."""
    graph = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
    cycles = detect_cycles(graph)
    assert cycles == ()


def test_self_loop() -> None:
    """A → A is a 1-element simple cycle."""
    graph = _graph(["A"], [("A", "A")])
    cycles = detect_cycles(graph)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A"}


def test_empty_graph() -> None:
    """Graph with no nodes and no edges returns no cycles."""
    graph = CallGraph(nodes=(), edges=(), resolution_stats=_STATS)
    assert detect_cycles(graph) == ()


def test_disconnected_two_components_one_cycle() -> None:
    """Two disconnected components where only one has a cycle."""
    # Component 1: A → B → A (cycle)
    # Component 2: C → D (no cycle)
    graph = _graph(
        ["A", "B", "C", "D"],
        [("A", "B"), ("B", "A"), ("C", "D")],
    )
    cycles = detect_cycles(graph)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"A", "B"}


def test_two_independent_cycles() -> None:
    """Two independent disjoint cycles are both returned."""
    # Cycle 1: A ↔ B
    # Cycle 2: C ↔ D
    graph = _graph(
        ["A", "B", "C", "D"],
        [("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")],
    )
    cycles = detect_cycles(graph)
    assert len(cycles) == 2
    cycle_sets = [set(c) for c in cycles]
    assert {"A", "B"} in cycle_sets
    assert {"C", "D"} in cycle_sets


def test_raw_graph_no_resolution_stats() -> None:
    """detect_cycles works on raw graphs (resolution_stats is None)."""
    nodes = tuple(_sym(n) for n in ["X", "Y"])
    # Raw graph: resolution_stats is None, validator skips edge checks.
    raw = CallGraph(nodes=nodes, edges=(("X", "Y"), ("Y", "X")), resolution_stats=None)
    cycles = detect_cycles(raw)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"X", "Y"}


@pytest.mark.parametrize(
    "names,edges,expected_cycle_count",
    [
        (["A", "B"], [("A", "B"), ("B", "A")], 1),
        (["A", "B", "C"], [("A", "B"), ("B", "C")], 0),
        (["A"], [], 0),
    ],
    ids=["two_cycle", "three_linear", "single_isolated"],
)
def test_parametrised_basic_cases(
    names: list[str],
    edges: list[tuple[str, str]],
    expected_cycle_count: int,
) -> None:
    """Parametrised sanity checks for common graph shapes."""
    graph = _graph(names, edges)
    cycles = detect_cycles(graph)
    assert len(cycles) == expected_cycle_count
