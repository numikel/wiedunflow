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
