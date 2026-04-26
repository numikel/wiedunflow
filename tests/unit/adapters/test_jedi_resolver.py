# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

import pytest

from wiedunflow.adapters.jedi_resolver import JediResolver
from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sym(
    name: str,
    file_path: Path,
    lineno: int = 1,
    docstring: str | None = None,
) -> CodeSymbol:
    """Build a CodeSymbol with minimal required fields."""
    return CodeSymbol(
        name=name,
        kind="function",
        file_path=file_path,
        lineno=lineno,
        docstring=docstring,
    )


def _raw_graph(
    symbols: list[CodeSymbol],
    edges: list[tuple[str, str]],
) -> CallGraph:
    """Build a raw CallGraph (resolution_stats=None) as the parser would emit."""
    return CallGraph(
        nodes=tuple(symbols),
        edges=tuple(edges),
        resolution_stats=None,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo_ab(tmp_path: Path) -> tuple[Path, CodeSymbol, CodeSymbol]:
    """Two-file repo: a.py defines f() calling g(); b.py defines g()."""
    a_py = tmp_path / "a.py"
    b_py = tmp_path / "b.py"

    a_py.write_text("from b import g\n\ndef f():\n    g()\n", encoding="utf-8")
    b_py.write_text("def g():\n    pass\n", encoding="utf-8")

    sym_f = _sym("f", a_py, lineno=3)
    sym_g = _sym("g", b_py, lineno=1)
    return tmp_path, sym_f, sym_g


@pytest.fixture()
def resolver() -> JediResolver:
    return JediResolver()


# ---------------------------------------------------------------------------
# Test: resolved cross-file edge
# ---------------------------------------------------------------------------


def test_resolved_edge_f_to_g(
    repo_ab: tuple[Path, CodeSymbol, CodeSymbol],
    resolver: JediResolver,
) -> None:
    """f() calling g() in a sibling file should resolve to 100%."""
    repo_root, sym_f, sym_g = repo_ab

    symbols = [sym_f, sym_g]
    raw = _raw_graph(symbols, [("f", "g")])

    result = resolver.resolve(symbols, raw, repo_root)

    assert result.resolution_stats is not None
    assert result.resolution_stats.resolved_pct == pytest.approx(100.0, abs=0.1)


# ---------------------------------------------------------------------------
# Test: empty graph → 100% resolved
# ---------------------------------------------------------------------------


def test_empty_graph_resolved_pct_100(
    tmp_path: Path,
    resolver: JediResolver,
) -> None:
    """No edges ⇒ resolved_pct must be 100.0 (nothing to fail resolving)."""
    py = tmp_path / "empty.py"
    py.write_text("# nothing\n", encoding="utf-8")
    sym = _sym("empty_module", py)

    raw = _raw_graph([sym], [])
    result = resolver.resolve([sym], raw, tmp_path)

    assert result.resolution_stats is not None
    assert result.resolution_stats.resolved_pct == pytest.approx(100.0)
    assert result.resolution_stats.unresolved_count == 0
    assert result.resolution_stats.uncertain_count == 0


# ---------------------------------------------------------------------------
# Test: unresolved — callee does not exist
# ---------------------------------------------------------------------------


def test_unresolved_callee(tmp_path: Path, resolver: JediResolver) -> None:
    """Reference to a completely undefined callee → unresolved_count == 1."""
    a_py = tmp_path / "a.py"
    a_py.write_text("def f():\n    totally_nonexistent_function()\n", encoding="utf-8")

    sym_f = _sym("f", a_py, lineno=1)
    symbols = [sym_f]
    raw = _raw_graph(symbols, [("f", "totally_nonexistent_function")])

    result = resolver.resolve(symbols, raw, tmp_path)

    assert result.resolution_stats is not None
    assert result.resolution_stats.unresolved_count == 1
    assert result.resolution_stats.resolved_pct == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# Test: missing caller symbol → unresolved
# ---------------------------------------------------------------------------


def test_missing_caller_symbol_counted_as_unresolved(
    tmp_path: Path,
    resolver: JediResolver,
) -> None:
    """Edge whose caller name does not match any CodeSymbol is unresolved."""
    a_py = tmp_path / "a.py"
    a_py.write_text("def f():\n    pass\n", encoding="utf-8")

    sym_f = _sym("f", a_py)
    # Edge references "nonexistent_caller" which is not in the symbols list.
    raw = _raw_graph([sym_f], [("nonexistent_caller", "f")])

    result = resolver.resolve([sym_f], raw, tmp_path)

    assert result.resolution_stats is not None
    assert result.resolution_stats.unresolved_count == 1


# ---------------------------------------------------------------------------
# Test: dynamic import marker propagation
# ---------------------------------------------------------------------------


def test_dynamic_import_marker_propagated(
    tmp_path: Path,
    resolver: JediResolver,
) -> None:
    """Symbol from a file with importlib.import_module gets is_dynamic_import=True."""
    dyn_py = tmp_path / "dyn.py"
    dyn_py.write_text(
        "import importlib\n"
        "def loader(name: str) -> object:\n"
        "    return importlib.import_module(name)\n",
        encoding="utf-8",
    )

    sym = _sym("loader", dyn_py, lineno=2)
    raw = _raw_graph([sym], [])  # no edges needed — just marker propagation

    result = resolver.resolve([sym], raw, tmp_path)

    # Find the resolved symbol in the output nodes.
    output_sym = next(s for s in result.nodes if s.name == "loader")
    assert output_sym.is_dynamic_import is True
    assert output_sym.is_uncertain is True


# ---------------------------------------------------------------------------
# Test: static-import file does NOT get marked
# ---------------------------------------------------------------------------


def test_static_import_no_dynamic_marker(
    tmp_path: Path,
    resolver: JediResolver,
) -> None:
    """Symbol from a file with only static imports must NOT be flagged."""
    static_py = tmp_path / "static.py"
    static_py.write_text(
        "import os\nfrom pathlib import Path\n\ndef helper() -> str:\n    return os.getcwd()\n",
        encoding="utf-8",
    )

    sym = _sym("helper", static_py, lineno=4)
    raw = _raw_graph([sym], [])

    result = resolver.resolve([sym], raw, tmp_path)

    output_sym = next(s for s in result.nodes if s.name == "helper")
    assert output_sym.is_dynamic_import is False
    assert output_sym.is_uncertain is False


# ---------------------------------------------------------------------------
# Test: cycle graph does not crash the resolver
# ---------------------------------------------------------------------------


def test_resolve_does_not_crash_on_cyclic_graph(
    tmp_path: Path,
    resolver: JediResolver,
) -> None:
    """f() → g() and g() → f() (mutual recursion) must not raise."""
    a_py = tmp_path / "a.py"
    b_py = tmp_path / "b.py"

    a_py.write_text("from b import g\n\ndef f():\n    g()\n", encoding="utf-8")
    b_py.write_text("from a import f\n\ndef g():\n    f()\n", encoding="utf-8")

    sym_f = _sym("f", a_py, lineno=3)
    sym_g = _sym("g", b_py, lineno=3)
    symbols = [sym_f, sym_g]
    raw = _raw_graph(symbols, [("f", "g"), ("g", "f")])

    # Should not raise.
    result = resolver.resolve(symbols, raw, tmp_path)
    assert result.resolution_stats is not None


# ---------------------------------------------------------------------------
# Test: node names preserved in output
# ---------------------------------------------------------------------------


def test_output_nodes_include_all_input_symbols(
    tmp_path: Path,
    resolver: JediResolver,
) -> None:
    """All input symbols must appear in the output nodes (possibly with updated flags)."""
    files = []
    syms: list[CodeSymbol] = []
    for i in range(3):
        p = tmp_path / f"mod{i}.py"
        p.write_text(f"def func{i}():\n    pass\n", encoding="utf-8")
        files.append(p)
        syms.append(_sym(f"func{i}", p, lineno=1))

    raw = _raw_graph(syms, [])
    result = resolver.resolve(syms, raw, tmp_path)

    output_names = {s.name for s in result.nodes}
    assert output_names == {"func0", "func1", "func2"}
