# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

from codeguide.entities.call_graph import CallGraph
from codeguide.entities.code_symbol import CodeSymbol
from codeguide.entities.resolution_stats import ResolutionStats


class StubJediResolver:
    """Stub Resolver returning the raw graph unchanged with 100% coverage.

    Implements the :class:`Resolver` Protocol via duck typing. Used by the
    walking-skeleton pipeline so that golden tests remain deterministic. The
    real Jedi adapter lands in Sprint 2 Track B.
    """

    def resolve(
        self,
        symbols: list[CodeSymbol],
        raw_graph: CallGraph,
        repo_root: Path,
    ) -> CallGraph:
        """Return a resolved graph: same edges plus perfect ResolutionStats.

        Args:
            symbols: Symbols from the parser (used as graph nodes).
            raw_graph: Parser output (edges carried over unchanged).
            repo_root: Repository root (ignored in stub).
        """
        _ = repo_root
        return CallGraph(
            nodes=tuple(symbols),
            edges=raw_graph.edges,
            resolution_stats=ResolutionStats(
                resolved_pct=100.0,
                uncertain_count=0,
                unresolved_count=0,
            ),
        )
