# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

from codeguide.entities.call_graph import CallGraph
from codeguide.entities.code_symbol import CodeSymbol


class StubTreeSitterParser:
    """Hardcoded parser for tests/fixtures/tiny_repo/ — returns pre-scripted symbols.

    Implements the Parser Protocol via duck typing.  The real tree-sitter
    adapter (Sprint 2) will replace this with actual AST extraction.
    """

    def parse(self, path: Path) -> tuple[list[CodeSymbol], CallGraph]:
        """Return fixed symbols and call graph regardless of which file is passed.

        Args:
            path: Source file path (ignored in stub — walking skeleton).

        Returns:
            A 2-tuple of (symbols, call_graph) covering the tiny_repo fixture.
        """
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
