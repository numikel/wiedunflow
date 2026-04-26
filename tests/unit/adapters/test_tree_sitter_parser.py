# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for the TreeSitterParser adapter."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from wiedunflow.adapters.tree_sitter_parser import TreeSitterParser
from wiedunflow.entities.code_symbol import CodeSymbol

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def parser() -> TreeSitterParser:
    return TreeSitterParser()


def _write(tmp_path: Path, filename: str, source: str) -> Path:
    """Write *source* to *tmp_path/filename* and return the absolute path."""
    p = tmp_path / filename
    p.write_text(dedent(source), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Helper assertions
# ---------------------------------------------------------------------------


def _symbol_names(symbols: list[CodeSymbol]) -> set[str]:
    return {s.name for s in symbols}


def _find(symbols: list[CodeSymbol], name: str) -> CodeSymbol:
    matches = [s for s in symbols if s.name == name]
    assert matches, f"Symbol {name!r} not found; available: {_symbol_names(symbols)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Basic function / class detection
# ---------------------------------------------------------------------------


def test_detects_top_level_functions(parser: TreeSitterParser, tmp_path: Path) -> None:
    """Three top-level functions are all detected with correct names."""
    f = _write(
        tmp_path,
        "mod.py",
        """\
        def alpha():
            pass

        def beta():
            pass

        def gamma():
            pass
        """,
    )
    symbols, _ = parser.parse([f], tmp_path)
    names = _symbol_names(symbols)
    assert "mod.alpha" in names
    assert "mod.beta" in names
    assert "mod.gamma" in names


def test_detects_class_definition(parser: TreeSitterParser, tmp_path: Path) -> None:
    """A class definition is captured as kind='class'."""
    f = _write(tmp_path, "shapes.py", "class Circle:\n    pass\n")
    symbols, _ = parser.parse([f], tmp_path)
    sym = _find(symbols, "shapes.Circle")
    assert sym.kind == "class"


def test_detects_method_inside_class(parser: TreeSitterParser, tmp_path: Path) -> None:
    """Methods nested inside a class carry a dotted qualified name."""
    f = _write(
        tmp_path,
        "pkg.py",
        """\
        class Dog:
            def bark(self):
                pass
        """,
    )
    symbols, _ = parser.parse([f], tmp_path)
    names = _symbol_names(symbols)
    assert "pkg.Dog" in names
    assert "pkg.Dog.bark" in names


def test_nested_class(parser: TreeSitterParser, tmp_path: Path) -> None:
    """Nested class gets a multi-level qualified name."""
    f = _write(
        tmp_path,
        "nested.py",
        """\
        class Outer:
            class Inner:
                def method(self):
                    pass
        """,
    )
    symbols, _ = parser.parse([f], tmp_path)
    names = _symbol_names(symbols)
    assert "nested.Outer" in names
    assert "nested.Outer.Inner" in names
    assert "nested.Outer.Inner.method" in names


# ---------------------------------------------------------------------------
# Async / decorators
# ---------------------------------------------------------------------------


def test_async_def_detected(parser: TreeSitterParser, tmp_path: Path) -> None:
    """``async def`` functions are detected like regular functions."""
    f = _write(
        tmp_path,
        "tasks.py",
        """\
        async def fetch_data():
            pass
        """,
    )
    symbols, _ = parser.parse([f], tmp_path)
    assert "tasks.fetch_data" in _symbol_names(symbols)


def test_decorated_function_detected(parser: TreeSitterParser, tmp_path: Path) -> None:
    """Decorated functions (e.g. @staticmethod) are still detected."""
    f = _write(
        tmp_path,
        "utils.py",
        """\
        class Util:
            @staticmethod
            def helper():
                pass

            @classmethod
            def factory(cls):
                pass
        """,
    )
    symbols, _ = parser.parse([f], tmp_path)
    names = _symbol_names(symbols)
    assert "utils.Util.helper" in names
    assert "utils.Util.factory" in names


# ---------------------------------------------------------------------------
# Docstring extraction
# ---------------------------------------------------------------------------


def test_docstring_extracted(parser: TreeSitterParser, tmp_path: Path) -> None:
    """A triple-quoted docstring is attached to the symbol."""
    f = _write(
        tmp_path,
        "documented.py",
        '''\
        def greet():
            """Say hello."""
            pass
        ''',
    )
    symbols, _ = parser.parse([f], tmp_path)
    sym = _find(symbols, "documented.greet")
    assert sym.docstring == "Say hello."


def test_no_docstring_is_none(parser: TreeSitterParser, tmp_path: Path) -> None:
    """Functions without a docstring have ``docstring=None``."""
    f = _write(
        tmp_path,
        "plain.py",
        """\
        def no_doc():
            x = 1
        """,
    )
    symbols, _ = parser.parse([f], tmp_path)
    sym = _find(symbols, "plain.no_doc")
    assert sym.docstring is None


# ---------------------------------------------------------------------------
# Call edges
# ---------------------------------------------------------------------------


def test_call_edges_detected(parser: TreeSitterParser, tmp_path: Path) -> None:
    """Intra-file call edges are present in the raw graph (> 0)."""
    f = _write(
        tmp_path,
        "calls.py",
        """\
        def callee_a():
            pass

        def callee_b():
            pass

        def caller():
            callee_a()
            callee_b()
        """,
    )
    _, graph = parser.parse([f], tmp_path)
    assert len(graph.edges) > 0


def test_cross_function_call_edge(parser: TreeSitterParser, tmp_path: Path) -> None:
    """A direct function-to-function call creates a corresponding edge."""
    f = _write(
        tmp_path,
        "simple_calls.py",
        """\
        def foo():
            pass

        def bar():
            foo()
        """,
    )
    _, graph = parser.parse([f], tmp_path)
    # caller is simple_calls.bar, callee text is 'foo'
    caller_names = {e[0] for e in graph.edges}
    assert "simple_calls.bar" in caller_names


# ---------------------------------------------------------------------------
# Raw graph invariants
# ---------------------------------------------------------------------------


def test_resolution_stats_is_none(parser: TreeSitterParser, tmp_path: Path) -> None:
    """The raw graph emitted by the parser always has ``resolution_stats=None``."""
    f = _write(tmp_path, "any.py", "def func(): pass\n")
    _, graph = parser.parse([f], tmp_path)
    assert graph.resolution_stats is None


def test_graph_nodes_match_symbols(parser: TreeSitterParser, tmp_path: Path) -> None:
    """The CallGraph nodes are the same objects as the returned symbols list."""
    f = _write(
        tmp_path,
        "check.py",
        """\
        def one(): pass
        def two(): pass
        """,
    )
    symbols, graph = parser.parse([f], tmp_path)
    graph_names = {n.name for n in graph.nodes}
    symbol_names = _symbol_names(symbols)
    assert graph_names == symbol_names


# ---------------------------------------------------------------------------
# Multiple files
# ---------------------------------------------------------------------------


def test_multiple_files_parsed_together(parser: TreeSitterParser, tmp_path: Path) -> None:
    """Symbols from multiple files are combined into a single result."""
    f1 = _write(tmp_path, "alpha.py", "def alpha_func(): pass\n")
    f2 = _write(tmp_path, "beta.py", "def beta_func(): pass\n")
    symbols, _graph = parser.parse([f1, f2], tmp_path)
    names = _symbol_names(symbols)
    assert "alpha.alpha_func" in names
    assert "beta.beta_func" in names


# ---------------------------------------------------------------------------
# File path handling
# ---------------------------------------------------------------------------


def test_file_path_relative_to_repo_root(parser: TreeSitterParser, tmp_path: Path) -> None:
    """``file_path`` on each symbol is relative to *repo_root*."""
    sub = tmp_path / "pkg"
    sub.mkdir()
    f = _write(sub, "mod.py", "def fn(): pass\n")
    symbols, _ = parser.parse([f], tmp_path)
    sym = _find(symbols, "pkg.mod.fn")
    assert not sym.file_path.is_absolute()
    assert sym.file_path == Path("pkg") / "mod.py"


def test_lineno_is_one_indexed(parser: TreeSitterParser, tmp_path: Path) -> None:
    """Line numbers are 1-indexed."""
    f = _write(
        tmp_path,
        "lines.py",
        """\
        def first():
            pass

        def second():
            pass
        """,
    )
    symbols, _ = parser.parse([f], tmp_path)
    first = _find(symbols, "lines.first")
    second = _find(symbols, "lines.second")
    assert first.lineno == 1
    assert second.lineno >= 4  # at least after the first function


# ---------------------------------------------------------------------------
# Edge case: empty file
# ---------------------------------------------------------------------------


def test_empty_file_produces_no_symbols(parser: TreeSitterParser, tmp_path: Path) -> None:
    """An empty Python file yields no symbols and an empty edge list."""
    f = _write(tmp_path, "empty.py", "")
    symbols, graph = parser.parse([f], tmp_path)
    assert symbols == []
    assert graph.edges == ()
