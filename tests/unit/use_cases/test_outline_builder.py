# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.ranked_graph import RankedGraph, RankedSymbol
from wiedunflow.entities.resolution_stats import ResolutionStats
from wiedunflow.use_cases.outline_builder import build_outline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _symbol(
    name: str,
    *,
    kind: str = "function",
    lineno: int = 1,
    docstring: str | None = None,
    is_uncertain: bool = False,
    is_dynamic_import: bool = False,
) -> CodeSymbol:
    return CodeSymbol(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        file_path=Path("mod.py"),
        lineno=lineno,
        docstring=docstring,
        is_uncertain=is_uncertain,
        is_dynamic_import=is_dynamic_import,
    )


def _ranked_graph(
    names: list[str],
    *,
    topological_order: list[str] | None = None,
    has_cycles: bool = False,
    cycle_groups: list[tuple[str, ...]] | None = None,
) -> RankedGraph:
    n = len(names)
    flat = 1.0 / n if n else 0.0
    ranked_symbols = tuple(
        RankedSymbol(symbol_name=name, pagerank_score=flat, community_id=0) for name in names
    )
    members = frozenset(names)
    communities: tuple[frozenset[str], ...] = (members,) if members else ()
    topo = tuple(topological_order or names)
    cg: tuple[tuple[str, ...], ...] = tuple(cycle_groups or [])
    return RankedGraph(
        ranked_symbols=ranked_symbols,
        communities=communities,
        topological_order=topo,
        has_cycles=has_cycles,
        cycle_groups=cg,
    )


def _call_graph(
    names: list[str],
    edges: list[tuple[str, str]] | None = None,
) -> CallGraph:
    nodes = tuple(_symbol(n) for n in names)
    edge_tuples: tuple[tuple[str, str], ...] = tuple(edges or [])
    stats = ResolutionStats(resolved_pct=100.0, uncertain_count=0, unresolved_count=0)
    return CallGraph(nodes=nodes, edges=edge_tuples, resolution_stats=stats)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBuildOutline:
    """Unit tests for outline_builder.build_outline."""

    # --- Empty symbols -------------------------------------------------------

    def test_empty_symbols_contains_header(self) -> None:
        outline = build_outline([], _call_graph([]), _ranked_graph([]))
        assert "Codebase outline" in outline

    def test_empty_symbols_contains_call_edges_heading(self) -> None:
        outline = build_outline([], _call_graph([]), _ranked_graph([]))
        assert "Call edges:" in outline

    def test_empty_symbols_no_symbol_lines(self) -> None:
        outline = build_outline([], _call_graph([]), _ranked_graph([]))
        # No indented symbol lines should appear.
        for line in outline.splitlines():
            assert not line.startswith("  function:"), f"Unexpected symbol line: {line!r}"

    # --- No cycles -----------------------------------------------------------

    def test_no_cycles_section_absent(self) -> None:
        symbols = [_symbol("A"), _symbol("B")]
        ranked = _ranked_graph(["A", "B"])
        cg = _call_graph(["A", "B"], [("A", "B")])
        outline = build_outline(symbols, cg, ranked)
        assert "Cycles detected:" not in outline

    # --- With cycles ---------------------------------------------------------

    def test_cycles_section_present_when_has_cycles(self) -> None:
        symbols = [_symbol("A"), _symbol("B")]
        ranked = _ranked_graph(
            ["A", "B"],
            has_cycles=True,
            cycle_groups=[("A", "B")],
        )
        cg = _call_graph(["A", "B"], [("A", "B"), ("B", "A")])
        outline = build_outline(symbols, cg, ranked)
        assert "Cycles detected:" in outline

    def test_cycles_group_rendered_in_outline(self) -> None:
        symbols = [_symbol("A"), _symbol("B")]
        ranked = _ranked_graph(
            ["A", "B"],
            has_cycles=True,
            cycle_groups=[("A", "B")],
        )
        cg = _call_graph(["A", "B"], [("A", "B"), ("B", "A")])
        outline = build_outline(symbols, cg, ranked)
        assert "A → B" in outline

    # --- Topological order ---------------------------------------------------

    def test_symbols_appear_in_topological_order(self) -> None:
        """Symbols must appear in the order given by ranked.topological_order."""
        symbols = [_symbol("C"), _symbol("B"), _symbol("A")]
        ranked = _ranked_graph(["A", "B", "C"], topological_order=["A", "B", "C"])
        cg = _call_graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        outline = build_outline(symbols, cg, ranked)
        lines = outline.splitlines()
        # Find positions of the symbol lines.
        positions: dict[str, int] = {}
        for i, line in enumerate(lines):
            for name in ("A", "B", "C"):
                # Match the "  function: <name>" pattern.
                if f": {name} " in line:
                    positions[name] = i
        assert positions["A"] < positions["B"] < positions["C"]

    def test_symbols_not_in_topo_order_appended_at_end(self) -> None:
        """A symbol absent from topological_order must still appear in outline."""
        symbols = [_symbol("A"), _symbol("B"), _symbol("orphan")]
        # orphan is not in topological_order.
        ranked = _ranked_graph(["A", "B"], topological_order=["A", "B"])
        cg = _call_graph(["A", "B"], [("A", "B")])
        outline = build_outline(symbols, cg, ranked)
        assert "orphan" in outline

    # --- Symbol metadata rendering -------------------------------------------

    def test_docstring_rendered_in_outline(self) -> None:
        symbols = [_symbol("A", docstring="Does stuff")]
        ranked = _ranked_graph(["A"])
        cg = _call_graph(["A"])
        outline = build_outline(symbols, cg, ranked)
        assert "Does stuff" in outline

    def test_uncertain_flag_rendered(self) -> None:
        symbols = [_symbol("A", is_uncertain=True)]
        ranked = _ranked_graph(["A"])
        cg = _call_graph(["A"])
        outline = build_outline(symbols, cg, ranked)
        assert "[uncertain]" in outline

    def test_dynamic_import_flag_rendered(self) -> None:
        symbols = [_symbol("A", is_dynamic_import=True)]
        ranked = _ranked_graph(["A"])
        cg = _call_graph(["A"])
        outline = build_outline(symbols, cg, ranked)
        assert "[dynamic]" in outline

    def test_call_edges_rendered(self) -> None:
        symbols = [_symbol("A"), _symbol("B")]
        ranked = _ranked_graph(["A", "B"])
        cg = _call_graph(["A", "B"], [("A", "B")])
        outline = build_outline(symbols, cg, ranked)
        assert "A → B" in outline

    def test_pagerank_score_in_output(self) -> None:
        symbols = [_symbol("A")]
        ranked = _ranked_graph(["A"])
        cg = _call_graph(["A"])
        outline = build_outline(symbols, cg, ranked)
        assert "pr=" in outline

    def test_community_id_in_output(self) -> None:
        symbols = [_symbol("A")]
        ranked = _ranked_graph(["A"])
        cg = _call_graph(["A"])
        outline = build_outline(symbols, cg, ranked)
        assert "community=" in outline


# ---------------------------------------------------------------------------
# Edge cap and PageRank-sorted edge selection
# ---------------------------------------------------------------------------


class TestBuildOutlineEdgeCap:
    """Unit tests for the max_edges parameter of build_outline."""

    def _make_large_cg(
        self,
        n_symbols: int = 10,
        n_edges: int = 5000,
        *,
        assign_pagerank: bool = False,
    ) -> tuple[list[CodeSymbol], CallGraph, RankedGraph]:
        """Build a call graph with *n_edges* edges over *n_symbols* symbols.

        When *assign_pagerank* is True, symbol PageRank scores are distributed
        non-uniformly so the sort order can be meaningfully tested.
        """
        import random

        rng = random.Random(42)
        names = [f"sym_{i}" for i in range(n_symbols)]
        symbols = [_symbol(name) for name in names]

        # Generate edges (may have duplicates — that's fine for this test).
        edges: list[tuple[str, str]] = []
        for _ in range(n_edges):
            caller = rng.choice(names)
            callee = rng.choice(names)
            edges.append((caller, callee))

        # Build ranked graph.  When assign_pagerank=True, symbol i gets score i/n.
        n = n_symbols
        if assign_pagerank:
            ranked_symbols = tuple(
                RankedSymbol(
                    symbol_name=names[i],
                    pagerank_score=float(i) / n,
                    community_id=0,
                )
                for i in range(n)
            )
        else:
            flat = 1.0 / n
            ranked_symbols = tuple(
                RankedSymbol(symbol_name=name, pagerank_score=flat, community_id=0)
                for name in names
            )
        members = frozenset(names)
        ranked = RankedGraph(
            ranked_symbols=ranked_symbols,
            communities=(members,),
            topological_order=tuple(names),
            has_cycles=False,
            cycle_groups=(),
        )

        stats = ResolutionStats(resolved_pct=100.0, uncertain_count=0, unresolved_count=0)
        cg = CallGraph(nodes=tuple(symbols), edges=tuple(edges), resolution_stats=stats)
        return symbols, cg, ranked

    @staticmethod
    def _edge_lines(outline: str) -> list[str]:
        """Extract only the indented call-edge lines (two-space indent + caller → callee)."""
        # Edge lines are always indented with exactly two spaces: "  caller → callee".
        # The header "Codebase outline (... leaves → roots):" is NOT indented, so
        # filtering by leading "  " (two spaces) reliably excludes the header.
        return [ln for ln in outline.splitlines() if ln.startswith("  ") and " → " in ln]

    def test_edge_cap_default_200_limits_output(self) -> None:
        """5000 edges with default max_edges=200 → at most 200 edge lines in outline."""
        symbols, cg, ranked = self._make_large_cg(n_edges=5000)
        outline = build_outline(symbols, cg, ranked)  # default max_edges=200

        assert len(self._edge_lines(outline)) <= 200

    def test_edge_cap_explicit_50(self) -> None:
        """max_edges=50 → at most 50 edge lines."""
        symbols, cg, ranked = self._make_large_cg(n_edges=500)
        outline = build_outline(symbols, cg, ranked, max_edges=50)

        assert len(self._edge_lines(outline)) <= 50

    def test_edge_cap_zero_retains_all_edges(self) -> None:
        """max_edges=0 disables the cap — all edges are retained."""
        n_edges = 300
        symbols, cg, ranked = self._make_large_cg(n_edges=n_edges)
        outline = build_outline(symbols, cg, ranked, max_edges=0)

        assert len(self._edge_lines(outline)) == n_edges

    def test_edges_sorted_by_pagerank_sum(self) -> None:
        """Edges in the outline must be sorted by caller_PR + callee_PR descending."""
        # Build a small graph with highly differentiated PageRank scores.
        names = ["low_0", "low_1", "high_2", "high_3"]
        symbols = [_symbol(n) for n in names]

        # Assign explicit scores: high_2=0.4, high_3=0.35, low_0=0.15, low_1=0.1
        scores = {"low_0": 0.15, "low_1": 0.10, "high_2": 0.40, "high_3": 0.35}
        ranked_symbols = tuple(
            RankedSymbol(symbol_name=n, pagerank_score=scores[n], community_id=0) for n in names
        )
        ranked = RankedGraph(
            ranked_symbols=ranked_symbols,
            communities=(frozenset(names),),
            topological_order=tuple(names),
            has_cycles=False,
            cycle_groups=(),
        )

        # Edges: high→high should come before low→low.
        edges = [
            ("low_0", "low_1"),  # PR sum = 0.25
            ("high_2", "high_3"),  # PR sum = 0.75  <- should be first
            ("low_1", "high_2"),  # PR sum = 0.50  <- second
        ]
        stats = ResolutionStats(resolved_pct=100.0, uncertain_count=0, unresolved_count=0)
        cg = CallGraph(nodes=tuple(symbols), edges=tuple(edges), resolution_stats=stats)

        outline = build_outline(symbols, cg, ranked, max_edges=10)
        edge_lines = [ln.strip() for ln in self._edge_lines(outline)]

        # The first edge line must be the highest-PR edge.
        assert edge_lines[0] == "high_2 → high_3", (
            f"Expected 'high_2 -> high_3' as first edge, got: {edge_lines[0]!r}"
        )
        # Last edge must be the lowest-PR edge.
        assert edge_lines[-1] == "low_0 → low_1", (
            f"Expected 'low_0 -> low_1' as last edge, got: {edge_lines[-1]!r}"
        )

    def test_fewer_edges_than_cap_all_included(self) -> None:
        """When total edges < max_edges, all edges appear in the outline."""
        symbols, cg, ranked = self._make_large_cg(n_edges=50)
        outline = build_outline(symbols, cg, ranked, max_edges=200)

        assert len(self._edge_lines(outline)) == 50
