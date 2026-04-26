# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

from codeguide.entities.call_graph import CallGraph
from codeguide.entities.code_symbol import CodeSymbol


class StubTreeSitterParser:
    """Hardcoded parser for the ``tests/fixtures/tiny_repo`` fixture.

    Implements the :class:`Parser` Protocol via duck typing. Returns a fixed
    ``(symbols, raw_graph)`` regardless of the ``files`` passed in. The real
    tree-sitter adapter (Sprint 2 Track A) replaces this on the CLI path.
    """

    def parse(
        self,
        files: list[Path],
        repo_root: Path,
    ) -> tuple[list[CodeSymbol], CallGraph]:
        """Return fixed symbols and call graph regardless of input.

        Args:
            files: Source files (ignored — stub returns fixture data).
            repo_root: Repository root (ignored — stub returns fixture data).

        Returns:
            A 2-tuple of ``(symbols, raw_graph)`` covering the tiny_repo fixture.
            ``raw_graph.resolution_stats`` is ``None`` — the Resolver fills it.
        """
        _ = files, repo_root
        symbols: list[CodeSymbol] = [
            CodeSymbol(
                name="calculator.add",
                kind="function",
                file_path=Path("calculator.py"),
                lineno=1,
                docstring=None,
            ),
            CodeSymbol(
                name="calculator.subtract",
                kind="function",
                file_path=Path("calculator.py"),
                lineno=4,
                docstring=None,
            ),
            CodeSymbol(
                name="main.cli",
                kind="function",
                file_path=Path("main.py"),
                lineno=3,
                docstring=None,
            ),
        ]
        graph = CallGraph(
            nodes=tuple(symbols),
            edges=(
                ("main.cli", "calculator.add"),
                ("main.cli", "calculator.subtract"),
            ),
        )
        return symbols, graph
