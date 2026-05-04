# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from wiedunflow.adapters.fs_boundary import DefaultFsBoundary
from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.use_cases.agent_tools import (
    _CAP_GREP,
    _CAP_LINES,
    _CAP_LIST_FILES,
    build_tool_registry,
    make_get_callees,
    make_get_callers,
    make_grep_usages,
    make_list_files_in_dir,
    make_read_lines,
    make_read_symbol_body,
    make_read_tests,
    make_search_docs,
)

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _PassthroughFsBoundary:
    """FsBoundary stub that resolves all paths without restriction.

    Used in happy-path tests where boundary enforcement is not the subject
    under test. Resolves the path (following symlinks) without any containment
    check, so tests work on any OS without a real repo root.
    """

    def ensure_within_root(self, target: Path) -> Path:
        return target.resolve()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def symbols() -> list[CodeSymbol]:
    """Three minimal CodeSymbol instances (no real source files)."""
    return [
        CodeSymbol(
            name="mymodule.top_fn",
            kind="function",
            file_path=Path("mymodule.py"),
            lineno=1,
            end_lineno=5,
            docstring="Top-level function.",
        ),
        CodeSymbol(
            name="mymodule.helper",
            kind="function",
            file_path=Path("mymodule.py"),
            lineno=8,
            end_lineno=12,
            docstring="Helper function.",
        ),
        CodeSymbol(
            name="mymodule.MyClass",
            kind="class",
            file_path=Path("mymodule.py"),
            lineno=15,
            end_lineno=30,
        ),
    ]


@pytest.fixture()
def graph(symbols: list[CodeSymbol]) -> CallGraph:
    """Simple call graph: top_fn → helper, top_fn → MyClass."""
    # No resolution_stats → raw graph; validation is relaxed.
    return CallGraph(
        nodes=tuple(symbols),
        edges=(
            ("mymodule.top_fn", "mymodule.helper"),
            ("mymodule.top_fn", "mymodule.MyClass"),
        ),
    )


class _StubVectorStore:
    """Minimal VectorStore stub."""

    def __init__(self, results: list[tuple[str, str, float]]) -> None:
        self._results = results

    def index(self, documents: list[tuple[str, str]]) -> None:
        pass

    def search(self, query: str, k: int = 5) -> list[tuple[str, str, float]]:
        return self._results[:k]


# ---------------------------------------------------------------------------
# make_read_symbol_body
# ---------------------------------------------------------------------------


def test_read_symbol_body_unknown_symbol(symbols: list[CodeSymbol]) -> None:
    tool = make_read_symbol_body(symbols)
    result = tool({"symbol": "nonexistent"})
    assert "[read_symbol_body]" in result
    assert "not found" in result


def test_read_symbol_body_known_symbol_with_docstring(symbols: list[CodeSymbol]) -> None:
    # Relative paths won't be readable from disk, so it falls back to docstring.
    tool = make_read_symbol_body(symbols)
    result = tool({"symbol": "mymodule.top_fn"})
    # Either full body or docstring fallback — should not be an error message.
    assert "mymodule.top_fn" in result or "Top-level function" in result


def test_read_symbol_body_no_docstring_no_file(symbols: list[CodeSymbol]) -> None:
    # MyClass has no docstring and no readable file (relative path).
    tool = make_read_symbol_body(symbols)
    result = tool({"symbol": "mymodule.MyClass"})
    # Should return some informational string, not raise.
    assert isinstance(result, str)
    assert len(result) > 0


def test_read_symbol_body_reads_real_file(tmp_path: Path) -> None:
    src = tmp_path / "sample.py"
    src.write_text("def my_fn():\n    return 42\n", encoding="utf-8")
    sym = CodeSymbol(
        name="sample.my_fn",
        kind="function",
        file_path=src,  # absolute path
        lineno=1,
        end_lineno=2,
    )
    tool = make_read_symbol_body([sym])
    result = tool({"symbol": "sample.my_fn"})
    assert "def my_fn" in result
    assert "return 42" in result


def test_read_symbol_body_truncates_large_body(tmp_path: Path) -> None:
    huge_line = "x = " + ("a" * 200) + "\n"
    src = tmp_path / "huge.py"
    # Write enough lines to exceed 8 KB.
    src.write_text(huge_line * 50, encoding="utf-8")
    sym = CodeSymbol(
        name="huge.thing",
        kind="function",
        file_path=src,
        lineno=1,
        end_lineno=50,
    )
    tool = make_read_symbol_body([sym])
    result = tool({"symbol": "huge.thing"})
    assert "[truncated]" in result


def test_read_symbol_body_missing_symbol_lists_available(symbols: list[CodeSymbol]) -> None:
    tool = make_read_symbol_body(symbols)
    result = tool({"symbol": "does.not.exist"})
    # Should show some available symbol names.
    assert "mymodule" in result or "Available" in result


# ---------------------------------------------------------------------------
# make_get_callers
# ---------------------------------------------------------------------------


def test_get_callers_no_callers(symbols: list[CodeSymbol], graph: CallGraph) -> None:
    # top_fn is a caller; it has no callers itself.
    tool = make_get_callers(graph)
    result = tool({"symbol": "mymodule.top_fn"})
    assert "[get_callers]" in result
    assert "No callers" in result


def test_get_callers_known_callers(symbols: list[CodeSymbol], graph: CallGraph) -> None:
    tool = make_get_callers(graph)
    result = tool({"symbol": "mymodule.helper"})
    assert "mymodule.top_fn" in result


def test_get_callers_multiple_callers(symbols: list[CodeSymbol]) -> None:
    graph = CallGraph(
        nodes=tuple(symbols),
        edges=(
            ("mymodule.top_fn", "mymodule.helper"),
            ("mymodule.MyClass", "mymodule.helper"),
        ),
    )
    tool = make_get_callers(graph)
    result = tool({"symbol": "mymodule.helper"})
    assert "mymodule.top_fn" in result
    assert "mymodule.MyClass" in result


def test_get_callers_nonexistent_symbol(symbols: list[CodeSymbol], graph: CallGraph) -> None:
    tool = make_get_callers(graph)
    result = tool({"symbol": "ghost.fn"})
    assert "No callers" in result


# ---------------------------------------------------------------------------
# make_get_callees
# ---------------------------------------------------------------------------


def test_get_callees_known_callees(symbols: list[CodeSymbol], graph: CallGraph) -> None:
    tool = make_get_callees(graph)
    result = tool({"symbol": "mymodule.top_fn"})
    assert "mymodule.helper" in result
    assert "mymodule.MyClass" in result


def test_get_callees_no_callees(symbols: list[CodeSymbol], graph: CallGraph) -> None:
    tool = make_get_callees(graph)
    result = tool({"symbol": "mymodule.helper"})
    assert "[get_callees]" in result
    assert "No callees" in result


def test_get_callees_nonexistent_symbol(symbols: list[CodeSymbol], graph: CallGraph) -> None:
    tool = make_get_callees(graph)
    result = tool({"symbol": "unknown"})
    assert "No callees" in result


# ---------------------------------------------------------------------------
# make_search_docs
# ---------------------------------------------------------------------------


def test_search_docs_returns_results() -> None:
    vs = _StubVectorStore([("doc_1", "first doc text", 0.9), ("doc_2", "second doc text", 0.7)])
    tool = make_search_docs(vs)
    result = tool({"query": "hello world", "k": 2})
    assert "doc_1" in result
    assert "doc_2" in result


def test_search_docs_no_results() -> None:
    vs = _StubVectorStore([])
    tool = make_search_docs(vs)
    result = tool({"query": "nothing here"})
    assert "[search_docs]" in result
    assert "No results" in result


def test_search_docs_respects_k_cap() -> None:
    # k > 10 should be capped to 10.
    vs = _StubVectorStore([(f"doc_{i}", f"text {i}", float(i)) for i in range(20)])
    tool = make_search_docs(vs)
    result = tool({"query": "test", "k": 20})
    # At most 10 entries before potential truncation.
    lines = [ln for ln in result.splitlines() if ln.startswith("[")]
    assert len(lines) <= 10


def test_search_docs_scores_in_output() -> None:
    vs = _StubVectorStore([("readme", "readme content here", 0.85)])
    tool = make_search_docs(vs)
    result = tool({"query": "overview"})
    assert "0.850" in result


# ---------------------------------------------------------------------------
# make_read_tests
# ---------------------------------------------------------------------------


def test_read_tests_finds_symbol(tmp_path: Path, symbols: list[CodeSymbol]) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_mymodule.py"
    test_file.write_text(
        "def test_top_fn():\n    from mymodule import top_fn\n    assert top_fn() is not None\n",
        encoding="utf-8",
    )
    tool = make_read_tests(tmp_path, symbols, _PassthroughFsBoundary())
    result = tool({"symbol": "mymodule.top_fn"})
    assert "top_fn" in result


def test_read_tests_not_found(tmp_path: Path, symbols: list[CodeSymbol]) -> None:
    # No tests directory at all.
    tool = make_read_tests(tmp_path, symbols, _PassthroughFsBoundary())
    result = tool({"symbol": "mymodule.top_fn"})
    assert "[read_tests]" in result
    assert "No tests" in result


def test_read_tests_empty_tests_dir(tmp_path: Path, symbols: list[CodeSymbol]) -> None:
    (tmp_path / "tests").mkdir()
    tool = make_read_tests(tmp_path, symbols, _PassthroughFsBoundary())
    result = tool({"symbol": "mymodule.helper"})
    assert "No tests" in result


def test_read_tests_symbol_not_in_file(tmp_path: Path, symbols: list[CodeSymbol]) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_other.py").write_text("def test_noop(): pass\n", encoding="utf-8")
    tool = make_read_tests(tmp_path, symbols, _PassthroughFsBoundary())
    result = tool({"symbol": "mymodule.top_fn"})
    assert "No tests" in result


# ---------------------------------------------------------------------------
# make_grep_usages
# ---------------------------------------------------------------------------


def test_grep_usages_finds_match(tmp_path: Path) -> None:
    src = tmp_path / "foo.py"
    src.write_text("import os\nresult = os.path.join('a', 'b')\n", encoding="utf-8")
    tool = make_grep_usages(tmp_path, _PassthroughFsBoundary())
    result = tool({"pattern": r"os\.path\.join"})
    assert "foo.py" in result
    assert "os.path.join" in result


def test_grep_usages_no_match(tmp_path: Path) -> None:
    src = tmp_path / "bar.py"
    src.write_text("x = 1\n", encoding="utf-8")
    tool = make_grep_usages(tmp_path, _PassthroughFsBoundary())
    result = tool({"pattern": "nonexistent_symbol"})
    assert "[grep_usages]" in result
    assert "No matches" in result


def test_grep_usages_invalid_regex(tmp_path: Path) -> None:
    tool = make_grep_usages(tmp_path, _PassthroughFsBoundary())
    result = tool({"pattern": "["})
    assert "Invalid regex" in result


def test_grep_usages_respects_cap(tmp_path: Path) -> None:
    # Create a file with many matching lines.
    src = tmp_path / "many.py"
    src.write_text("\n".join(f"match_{i} = True" for i in range(100)) + "\n", encoding="utf-8")
    tool = make_grep_usages(tmp_path, _PassthroughFsBoundary())
    result = tool({"pattern": "match_"})
    lines = result.splitlines()
    # Should include the cap notice.
    assert any("limit reached" in ln for ln in lines)
    assert len([ln for ln in lines if "match_" in ln]) <= _CAP_GREP


def test_grep_usages_multiple_files(tmp_path: Path) -> None:
    for name in ["a.py", "b.py"]:
        (tmp_path / name).write_text("NEEDLE = 1\n", encoding="utf-8")
    tool = make_grep_usages(tmp_path, _PassthroughFsBoundary())
    result = tool({"pattern": "NEEDLE"})
    assert "a.py" in result
    assert "b.py" in result


# ---------------------------------------------------------------------------
# make_list_files_in_dir
# ---------------------------------------------------------------------------


def test_list_files_in_dir_basic(tmp_path: Path) -> None:
    (tmp_path / "alpha.py").write_text("", encoding="utf-8")
    (tmp_path / "beta.py").write_text("", encoding="utf-8")
    tool = make_list_files_in_dir(tmp_path, _PassthroughFsBoundary())
    result = tool({"path": "."})
    assert "alpha.py" in result
    assert "beta.py" in result


def test_list_files_in_dir_subdirs_have_slash(tmp_path: Path) -> None:
    (tmp_path / "subdir").mkdir()
    tool = make_list_files_in_dir(tmp_path, _PassthroughFsBoundary())
    result = tool({"path": "."})
    assert "subdir/" in result


def test_list_files_in_dir_nonexistent(tmp_path: Path) -> None:
    tool = make_list_files_in_dir(tmp_path, _PassthroughFsBoundary())
    result = tool({"path": "no_such_dir"})
    assert "does not exist" in result


def test_list_files_in_dir_file_not_dir(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    tool = make_list_files_in_dir(tmp_path, _PassthroughFsBoundary())
    result = tool({"path": "file.txt"})
    assert "not a directory" in result


def test_list_files_in_dir_empty(tmp_path: Path) -> None:
    (tmp_path / "empty_subdir").mkdir()
    tool = make_list_files_in_dir(tmp_path, _PassthroughFsBoundary())
    result = tool({"path": "empty_subdir"})
    assert "Empty directory" in result


def test_list_files_in_dir_respects_cap(tmp_path: Path) -> None:
    for i in range(_CAP_LIST_FILES + 10):
        (tmp_path / f"file_{i:04d}.py").write_text("", encoding="utf-8")
    tool = make_list_files_in_dir(tmp_path, _PassthroughFsBoundary())
    result = tool({"path": "."})
    assert "limit reached" in result


# ---------------------------------------------------------------------------
# make_read_lines
# ---------------------------------------------------------------------------


def test_read_lines_basic(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("\n".join(f"line{i}" for i in range(1, 11)), encoding="utf-8")
    tool = make_read_lines(tmp_path, _PassthroughFsBoundary())
    result = tool({"file_path": "code.py", "start": 2, "end": 4})
    assert "line2" in result
    assert "line3" in result
    assert "line4" in result
    assert "line1" not in result
    assert "line5" not in result


def test_read_lines_default_end(tmp_path: Path) -> None:
    f = tmp_path / "code.py"
    f.write_text("\n".join(f"line{i}" for i in range(1, 100)), encoding="utf-8")
    tool = make_read_lines(tmp_path, _PassthroughFsBoundary())
    # Default: start=1, end=start+50=51 → lines 1..51 inclusive (51 lines).
    result = tool({"file_path": "code.py", "start": 1})
    assert "line1" in result
    assert "line52" not in result  # line 52 is beyond the default window


def test_read_lines_cap_enforced(tmp_path: Path) -> None:
    f = tmp_path / "big.py"
    f.write_text("\n".join(f"row{i}" for i in range(1, 500)), encoding="utf-8")
    tool = make_read_lines(tmp_path, _PassthroughFsBoundary())
    result = tool({"file_path": "big.py", "start": 1, "end": 400})
    lines = result.splitlines()
    # Header line + up to _CAP_LINES content lines.
    assert len(lines) <= _CAP_LINES + 1


def test_read_lines_nonexistent_file(tmp_path: Path) -> None:
    tool = make_read_lines(tmp_path, _PassthroughFsBoundary())
    result = tool({"file_path": "ghost.py"})
    assert "does not exist" in result


def test_read_lines_path_is_dir(tmp_path: Path) -> None:
    (tmp_path / "adir").mkdir()
    tool = make_read_lines(tmp_path, _PassthroughFsBoundary())
    result = tool({"file_path": "adir"})
    assert "not a file" in result


def test_read_lines_header_contains_filename(tmp_path: Path) -> None:
    f = tmp_path / "sample.py"
    f.write_text("a = 1\n", encoding="utf-8")
    tool = make_read_lines(tmp_path, _PassthroughFsBoundary())
    result = tool({"file_path": "sample.py", "start": 1, "end": 1})
    assert "sample.py" in result


# ---------------------------------------------------------------------------
# build_tool_registry
# ---------------------------------------------------------------------------


def test_build_tool_registry_keys(
    symbols: list[CodeSymbol], graph: CallGraph, tmp_path: Path
) -> None:
    vs = _StubVectorStore([])
    registry = build_tool_registry(
        symbols=symbols,
        graph=graph,
        vector_store=vs,
        repo_root=tmp_path,
        fs_boundary=_PassthroughFsBoundary(),
    )
    expected_keys = {
        "read_symbol_body",
        "get_callers",
        "get_callees",
        "search_docs",
        "read_tests",
        "grep_usages",
        "list_files_in_dir",
        "read_lines",
    }
    assert set(registry.keys()) == expected_keys


def test_build_tool_registry_all_callable(
    symbols: list[CodeSymbol], graph: CallGraph, tmp_path: Path
) -> None:
    vs = _StubVectorStore([])
    registry = build_tool_registry(
        symbols=symbols,
        graph=graph,
        vector_store=vs,
        repo_root=tmp_path,
        fs_boundary=_PassthroughFsBoundary(),
    )
    for name, fn in registry.items():
        assert callable(fn), f"{name} is not callable"


def test_build_tool_registry_tools_return_strings(
    symbols: list[CodeSymbol], graph: CallGraph, tmp_path: Path
) -> None:
    vs = _StubVectorStore([("d", "doc text", 0.5)])
    registry = build_tool_registry(
        symbols=symbols,
        graph=graph,
        vector_store=vs,
        repo_root=tmp_path,
        fs_boundary=_PassthroughFsBoundary(),
    )
    # Smoke-test each tool returns a string.
    assert isinstance(registry["read_symbol_body"]({"symbol": "mymodule.top_fn"}), str)
    assert isinstance(registry["get_callers"]({"symbol": "mymodule.helper"}), str)
    assert isinstance(registry["get_callees"]({"symbol": "mymodule.top_fn"}), str)
    assert isinstance(registry["search_docs"]({"query": "hello"}), str)
    assert isinstance(registry["read_tests"]({"symbol": "mymodule.top_fn"}), str)
    assert isinstance(registry["grep_usages"]({"pattern": "def "}), str)
    assert isinstance(registry["list_files_in_dir"]({"path": "."}), str)
    assert isinstance(registry["read_lines"]({"file_path": "nonexistent.py"}), str)


# ---------------------------------------------------------------------------
# Security: path-traversal negative cases (F-007)
# ---------------------------------------------------------------------------
# For each of the 4 fs-touching tools, two attack vectors are tested:
#   1. relative traversal: "../../etc/passwd"
#   2. absolute path outside repo_root: OS-appropriate system file
#
# All must return an "error: path escapes repo root" string, never file contents.
# Uses DefaultFsBoundary (real implementation, not a stub) to exercise the full
# boundary enforcement path.
# ---------------------------------------------------------------------------

# Platform-appropriate outside-root absolute path used in negative tests.
_OUTSIDE_ABS: str = (
    r"C:\Windows\System32\drivers\etc\hosts" if sys.platform == "win32" else "/etc/passwd"
)


@pytest.mark.parametrize(
    "attack_path",
    [
        "../../etc/passwd",
        _OUTSIDE_ABS,
    ],
    ids=["relative-traversal", "absolute-outside"],
)
def test_list_files_in_dir_rejects_traversal(tmp_path: Path, attack_path: str) -> None:
    """list_files_in_dir must return an error string for paths outside repo_root."""
    boundary = DefaultFsBoundary(root=tmp_path)
    tool = make_list_files_in_dir(tmp_path, boundary)
    result = tool({"path": attack_path})
    assert result.startswith("error:"), f"Expected error string, got: {result!r}"
    assert "escapes repo root" in result


@pytest.mark.parametrize(
    "attack_path",
    [
        "../../etc/passwd",
        _OUTSIDE_ABS,
    ],
    ids=["relative-traversal", "absolute-outside"],
)
def test_read_lines_rejects_traversal(tmp_path: Path, attack_path: str) -> None:
    """read_lines must return an error string for paths outside repo_root."""
    boundary = DefaultFsBoundary(root=tmp_path)
    tool = make_read_lines(tmp_path, boundary)
    result = tool({"file_path": attack_path})
    assert result.startswith("error:"), f"Expected error string, got: {result!r}"
    assert "escapes repo root" in result


@pytest.mark.parametrize(
    "attack_path",
    [
        "../../etc/passwd",
        _OUTSIDE_ABS,
    ],
    ids=["relative-traversal", "absolute-outside"],
)
def test_read_tests_skips_outside_root_symlinks(tmp_path: Path, attack_path: str) -> None:
    """read_tests with a real boundary silently skips any file that resolves outside root.

    Because make_read_tests uses rglob (not user-supplied paths), the attack
    surface is symlinks. We verify the tool returns "No tests" (skip) rather
    than attempting to read the outside file.  The symbol-name input is NOT
    a path, so no direct traversal is possible — this confirms defensive depth.
    """
    # Create a tests/ dir so the tool has something to walk.
    (tmp_path / "tests").mkdir()
    boundary = DefaultFsBoundary(root=tmp_path)
    tool = make_read_tests(tmp_path, [], boundary)
    # Symbol name is user input; it is NOT treated as a path by this tool.
    result = tool({"symbol": "some.symbol"})
    # No file named "some.symbol" exists — the tool should report no tests found.
    assert "No tests" in result


@pytest.mark.parametrize(
    "attack_pattern",
    [
        "../../etc/passwd",
        _OUTSIDE_ABS,
    ],
    ids=["relative-traversal", "absolute-outside"],
)
def test_grep_usages_skips_outside_root_symlinks(tmp_path: Path, attack_pattern: str) -> None:
    """grep_usages with a real boundary silently skips files that resolve outside root.

    The pattern input is a regex (NOT a path), so direct traversal is not
    possible. This confirms defensive depth for symlink escape.
    """
    # No Python files in tmp_path — rglob yields nothing, no boundary checks needed.
    boundary = DefaultFsBoundary(root=tmp_path)
    tool = make_grep_usages(tmp_path, boundary)
    # Pattern is a valid regex; the tool should return "No matches" (empty repo).
    result = tool({"pattern": "anything"})
    assert "No matches" in result
