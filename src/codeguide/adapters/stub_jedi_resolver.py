# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

from codeguide.entities.call_graph import CallGraph
from codeguide.entities.code_symbol import CodeSymbol


class StubJediResolver:
    """Stub Jedi resolver — returns a pre-scripted CallGraph for tiny_repo.

    Note: resolve() is NOT part of the Parser Protocol (which only requires
    parse()).  This class is wired directly into generate_tutorial.py for S1
    and will be replaced by the real Jedi adapter in Sprint 2.
    """

    def resolve(
        self,
        symbols: list[CodeSymbol],
        repo_root: Path,
    ) -> CallGraph:
        """Return a fixed call graph regardless of input symbols.

        Args:
            symbols: Symbols extracted by the parser (used as graph nodes).
            repo_root: Repository root path (ignored in stub).

        Returns:
            A CallGraph with hardcoded edges matching the tiny_repo fixture.
        """
        return CallGraph(
            nodes=tuple(symbols),
            edges=(
                ("main.cli", "calculator.add"),
                ("main.cli", "calculator.subtract"),
            ),
        )
