# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Outline builder: converts Stage 2/3 outputs into a plain-text planning prompt.

The outline is consumed by Stage 5 (Planning) as the sole context for the
single Sonnet LLM call that produces the
:class:`~wiedunflow.entities.lesson_manifest.LessonManifest`.
"""

from __future__ import annotations

from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.ranked_graph import RankedGraph


def build_outline(
    symbols: list[CodeSymbol],
    call_graph: CallGraph,
    ranked: RankedGraph,
    *,
    max_edges: int = 200,
) -> str:
    """Build a plain-text outline of the codebase for the planning LLM call.

    Symbols are emitted in SCC-condensed topological order (leaves → roots)
    so the planning LLM sees the dependency structure without being told how
    to order lessons.  Symbols not found in ``ranked.topological_order`` are
    appended at the end preserving their original parse order.

    Call edges are sorted by the sum of caller + callee PageRank (descending)
    so structurally important paths always appear regardless of the cap.
    On a medium repo (300 symbols, ~2-5 K edges) the raw edge list consumed
    40-60% of the planning context window; capping at ``max_edges=200`` brings
    the edge section to a predictable ~15 KB.

    Args:
        symbols: Symbols emitted by the parser (post-resolver).
        call_graph: Resolved call graph from Stage 2.
        ranked: Output of Stage 3 — PageRank, communities, topological order.
        max_edges: Maximum number of call edges to include.  Edges are sorted
            by caller PageRank + callee PageRank descending so the most
            structurally significant paths are always retained.  ``0`` disables
            the cap (keeps all edges — backward-compatible with v0.11.x).

    Returns:
        Multi-line string describing symbols (ordered topologically) and call
        edges.  Format is stable across runs; any change breaks the golden
        snapshot test.
    """
    pagerank_by_name = {rs.symbol_name: rs.pagerank_score for rs in ranked.ranked_symbols}
    community_by_name = {rs.symbol_name: rs.community_id for rs in ranked.ranked_symbols}
    by_name = {s.name: s for s in symbols}

    ordered_names = [n for n in ranked.topological_order if n in by_name]
    trailing = [s.name for s in symbols if s.name not in ordered_names]
    ordered_names.extend(trailing)

    lines = ["Codebase outline (topological order, leaves → roots):", ""]
    for name in ordered_names:
        symbol = by_name[name]
        uncertainty = " [uncertain]" if symbol.is_uncertain else ""
        dynamic = " [dynamic]" if symbol.is_dynamic_import else ""
        doc = f" — {symbol.docstring}" if symbol.docstring else ""
        score = pagerank_by_name.get(name, 0.0)
        community = community_by_name.get(name, -1)
        lines.append(
            f"  {symbol.kind}: {symbol.name} (line {symbol.lineno}, "
            f"pr={score:.3f}, community={community}){uncertainty}{dynamic}{doc}"
        )
    lines.append("")
    lines.append("Call edges:")

    # Sort edges by PageRank importance so the cap always retains the most
    # structurally significant call paths rather than an arbitrary slice.
    edges_sorted = sorted(
        call_graph.edges,
        key=lambda e: pagerank_by_name.get(e[0], 0.0) + pagerank_by_name.get(e[1], 0.0),
        reverse=True,
    )
    capped_edges = edges_sorted[:max_edges] if max_edges > 0 else edges_sorted
    for caller, callee in capped_edges:
        lines.append(f"  {caller} → {callee}")
    if ranked.has_cycles:
        lines.append("")
        lines.append("Cycles detected:")
        for group in ranked.cycle_groups:
            lines.append(f"  {' → '.join(group)}")
    return "\n".join(lines)
