# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Cross-track integration: real parser + resolver + ranker on medium_repo fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiedunflow.adapters.jedi_resolver import JediResolver
from wiedunflow.adapters.networkx_ranker import NetworkxRanker
from wiedunflow.adapters.tree_sitter_parser import TreeSitterParser
from wiedunflow.use_cases.ingestion import ingest

pytestmark = pytest.mark.integration

_MEDIUM_REPO = Path(__file__).parent.parent / "fixtures" / "medium_repo"


def test_ingestion_filters_cache_and_git() -> None:
    """Ingestion must exclude __pycache__ and dotted dirs; return absolute paths."""
    result = ingest(_MEDIUM_REPO)
    assert len(result.files) >= 15, f"expected ≥15 python files, got {len(result.files)}"
    for p in result.files:
        assert p.is_absolute()
        assert "__pycache__" not in p.parts
        assert not any(part.startswith(".") for part in p.parts)


def test_parser_emits_symbols_and_raw_edges() -> None:
    """Tree-sitter parser must discover cross-module call edges."""
    result = ingest(_MEDIUM_REPO)
    parser = TreeSitterParser()
    symbols, raw_graph = parser.parse(list(result.files), result.repo_root)
    assert len(symbols) >= 25, f"expected ≥25 symbols, got {len(symbols)}"
    assert len(raw_graph.edges) >= 10, f"expected ≥10 raw edges, got {len(raw_graph.edges)}"
    assert raw_graph.resolution_stats is None, "raw graph must not carry ResolutionStats"


def test_resolver_produces_resolution_stats() -> None:
    """Jedi resolver must attach ResolutionStats with a reasonable coverage."""
    result = ingest(_MEDIUM_REPO)
    parser = TreeSitterParser()
    symbols, raw_graph = parser.parse(list(result.files), result.repo_root)
    resolver = JediResolver()
    resolved = resolver.resolve(symbols, raw_graph, result.repo_root)
    assert resolved.resolution_stats is not None
    stats = resolved.resolution_stats
    total = stats.uncertain_count + stats.unresolved_count
    assert stats.resolved_pct >= 0.0
    assert total >= 0


def test_ranker_builds_well_formed_ranked_graph() -> None:
    """networkx ranker must produce a valid RankedGraph over the resolved graph."""
    result = ingest(_MEDIUM_REPO)
    parser = TreeSitterParser()
    symbols, raw_graph = parser.parse(list(result.files), result.repo_root)
    resolver = JediResolver()
    resolved = resolver.resolve(symbols, raw_graph, result.repo_root)
    ranker = NetworkxRanker()
    ranked = ranker.rank(resolved)
    assert len(ranked.ranked_symbols) == len(resolved.nodes)
    assert len(ranked.topological_order) == len(resolved.nodes)
    names_in_ranked = {rs.symbol_name for rs in ranked.ranked_symbols}
    for community in ranked.communities:
        for member in community:
            assert member in names_in_ranked


def test_medium_repo_has_no_cycles() -> None:
    """medium_repo fixture is designed DAG-only; `has_cycles` must be False."""
    result = ingest(_MEDIUM_REPO)
    parser = TreeSitterParser()
    symbols, raw_graph = parser.parse(list(result.files), result.repo_root)
    resolver = JediResolver()
    resolved = resolver.resolve(symbols, raw_graph, result.repo_root)
    ranker = NetworkxRanker()
    ranked = ranker.rank(resolved)
    assert ranked.has_cycles is False
    assert ranked.cycle_groups == ()
