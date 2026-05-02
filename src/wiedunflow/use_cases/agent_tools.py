# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.interfaces.ports import VectorStore

# ---------------------------------------------------------------------------
# Size caps
# ---------------------------------------------------------------------------

_CAP_SYMBOL_BODY = 8 * 1024  # 8 KB
_CAP_CALLERS = 50  # entries
_CAP_CALLEES = 50  # entries
_CAP_DOCS = 5 * 1024  # 5 KB
_CAP_TESTS = 10 * 1024  # 10 KB
_CAP_GREP = 30  # hits
_CAP_LIST_FILES = 100  # entries
_CAP_LINES = 200  # lines
_CAP_TEST_CTX_BLOCKS = 5  # max context blocks per test file

# Directories to skip when walking the repo tree.
_SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".mypy_cache"}

ToolFn = Callable[[dict[str, Any]], str]


# ---------------------------------------------------------------------------
# Graph helpers — CallGraph has no predecessors()/successors() methods; we
# derive them from the raw ``edges`` tuple at factory time so each tool call
# is O(1) after a one-time O(E) build.
# ---------------------------------------------------------------------------


def _build_predecessor_map(graph: CallGraph) -> dict[str, list[str]]:
    """Build callee → [callers] mapping from ``graph.edges``."""
    result: dict[str, list[str]] = {}
    for caller, callee in graph.edges:
        result.setdefault(callee, []).append(caller)
    return result


def _build_successor_map(graph: CallGraph) -> dict[str, list[str]]:
    """Build caller → [callees] mapping from ``graph.edges``."""
    result: dict[str, list[str]] = {}
    for caller, callee in graph.edges:
        result.setdefault(caller, []).append(callee)
    return result


# ---------------------------------------------------------------------------
# Tool factories
# ---------------------------------------------------------------------------


def make_read_symbol_body(symbols: list[CodeSymbol]) -> ToolFn:
    """Return the source body of a named symbol (up to 8 KB).

    Because ``CodeSymbol`` does not carry the raw source body — that lives in
    the file on disk — the tool reads the file and extracts the relevant line
    range when ``lineno`` / ``end_lineno`` are available.  The ``docstring``
    field is used as a fallback when the file cannot be read.

    Args:
        symbols: All symbols from the ingestion snapshot.

    Returns:
        A tool function ``(args) -> str`` suitable for LLM ``tool_result``
        content.
    """
    idx: dict[str, CodeSymbol] = {s.name: s for s in symbols}

    def _call(args: dict[str, Any]) -> str:
        name = str(args.get("symbol", ""))
        sym = idx.get(name)
        if sym is None:
            available = ", ".join(list(idx)[:20])
            return f"[read_symbol_body] Symbol '{name}' not found. Available: {available}"

        # Attempt to read from the file using the line-span recorded by the parser.
        body_str = _read_symbol_from_file(sym)
        if not body_str:
            # Fallback: expose the docstring as the best available description.
            doc = sym.docstring or ""
            if doc:
                return (
                    f"# {name} ({sym.kind}) — {sym.file_path}:{sym.lineno}\n\n"
                    f"*(source not available — docstring only)*\n\n{doc}"
                )
            return (
                f"[read_symbol_body] No source body available for '{name}' "
                f"(kind={sym.kind}, file={sym.file_path})"
            )

        if len(body_str) > _CAP_SYMBOL_BODY:
            body_str = body_str[:_CAP_SYMBOL_BODY] + "\n... [truncated]"
        return f"# {name} ({sym.kind}) — {sym.file_path}:{sym.lineno}\n\n```python\n{body_str}\n```"

    return _call


def _read_symbol_from_file(sym: CodeSymbol) -> str:
    """Read the source lines for *sym* directly from its file.

    Returns an empty string when the file cannot be read or the path is
    relative without a resolvable anchor.
    """
    try:
        path = Path(sym.file_path)
        if not path.is_absolute():
            # Relative paths cannot be opened without the repo root context;
            # return empty and let the caller fall back to the docstring.
            return ""
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, sym.lineno - 1)
        end = len(lines) if sym.end_lineno is None else min(sym.end_lineno, len(lines))
        return "\n".join(lines[start:end])
    except OSError:
        return ""


def make_get_callers(symbols: list[CodeSymbol], graph: CallGraph) -> ToolFn:
    """Return the list of symbols that call the given symbol.

    Args:
        symbols: All symbols from the ingestion snapshot (used only for
            name validation in error messages).
        graph: The resolved call graph; edges are ``(caller, callee)`` tuples.

    Returns:
        A tool function ``(args) -> str``.
    """
    predecessor_map = _build_predecessor_map(graph)

    def _call(args: dict[str, Any]) -> str:
        name = str(args.get("symbol", ""))
        callers = predecessor_map.get(name, [])[:_CAP_CALLERS]
        if not callers:
            return f"[get_callers] No callers found for '{name}'"
        lines = [f"- {c}" for c in callers]
        return f"Callers of `{name}` ({len(callers)}):\n" + "\n".join(lines)

    return _call


def make_get_callees(symbols: list[CodeSymbol], graph: CallGraph) -> ToolFn:
    """Return the list of symbols called by the given symbol.

    Args:
        symbols: All symbols from the ingestion snapshot.
        graph: The resolved call graph.

    Returns:
        A tool function ``(args) -> str``.
    """
    successor_map = _build_successor_map(graph)

    def _call(args: dict[str, Any]) -> str:
        name = str(args.get("symbol", ""))
        callees = successor_map.get(name, [])[:_CAP_CALLEES]
        if not callees:
            return f"[get_callees] No callees found for '{name}'"
        lines = [f"- {c}" for c in callees]
        return f"Callees of `{name}` ({len(callees)}):\n" + "\n".join(lines)

    return _call


def make_search_docs(vector_store: VectorStore) -> ToolFn:
    """BM25 search over docs/README/inline comments.

    Args:
        vector_store: The RAG index implementing ``VectorStore.search()``.

    Returns:
        A tool function ``(args) -> str``.
    """

    def _call(args: dict[str, Any]) -> str:
        query = str(args.get("query", ""))
        k = min(int(args.get("k", 5)), 10)
        results = vector_store.search(query, k=k)
        if not results:
            return "[search_docs] No results found"
        lines: list[str] = []
        total = 0
        for doc_id, score in results:
            snippet = f"[{doc_id}] (score={score:.3f})"
            lines.append(snippet)
            total += len(snippet)
            if total > _CAP_DOCS:
                lines.append("... [truncated]")
                break
        return "\n".join(lines)

    return _call


def make_read_tests(repo_root: Path, symbols: list[CodeSymbol]) -> ToolFn:
    """Find and return test code that mentions a symbol (up to 10 KB).

    Searches ``<repo_root>/tests/`` and ``<repo_root>/test/`` for
    ``test_*.py`` files that contain the symbol's short name (the part after
    the last dot), then returns up to 5 line-context excerpts per file.

    Args:
        repo_root: Absolute path to the repository root.
        symbols: All symbols from the ingestion snapshot.

    Returns:
        A tool function ``(args) -> str``.
    """

    def _call(args: dict[str, Any]) -> str:
        symbol = str(args.get("symbol", ""))
        short = symbol.rsplit(".", maxsplit=1)[-1]
        test_dirs = [repo_root / "tests", repo_root / "test"]
        hits: list[str] = []
        total_chars = 0
        for test_dir in test_dirs:
            if not test_dir.exists():
                continue
            for test_file in sorted(test_dir.rglob("test_*.py")):
                try:
                    content = test_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if short not in content:
                    continue
                try:
                    rel = test_file.relative_to(repo_root)
                except ValueError:
                    rel = test_file
                excerpt_lines: list[str] = [f"# {rel}"]
                file_lines = content.splitlines()
                ctx_blocks: list[str] = []
                for i, line in enumerate(file_lines):
                    if short in line:
                        start = max(0, i - 2)
                        end = min(len(file_lines), i + 5)
                        block = "\n".join(file_lines[start:end])
                        ctx_blocks.append(f"... line {i + 1}:\n{block}")
                        if len(ctx_blocks) >= _CAP_TEST_CTX_BLOCKS:
                            break
                excerpt_lines.extend(ctx_blocks)
                excerpt = "\n".join(excerpt_lines)
                hits.append(excerpt)
                total_chars += len(excerpt)
                if total_chars > _CAP_TESTS:
                    hits.append("... [truncated — more test files not shown]")
                    break
            if total_chars > _CAP_TESTS:
                break
        if not hits:
            return f"[read_tests] No tests found for '{symbol}'"
        return "\n\n---\n\n".join(hits)

    return _call


def make_grep_usages(repo_root: Path) -> ToolFn:
    """Regex grep over Python files in the repo (skips common noise dirs).

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        A tool function ``(args) -> str``.  Accepts ``pattern`` (required)
        as a Python-compatible regex string.
    """

    def _call(args: dict[str, Any]) -> str:
        pattern_str = str(args.get("pattern", ""))
        try:
            pat = re.compile(pattern_str)
        except re.error as e:
            return f"[grep_usages] Invalid regex: {e}"
        hits: list[str] = []
        for src_file in _iter_python_files(repo_root, _SKIP_DIRS):
            try:
                content = src_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(content.splitlines(), 1):
                if pat.search(line):
                    try:
                        rel = src_file.relative_to(repo_root)
                    except ValueError:
                        rel = src_file
                    hits.append(f"{rel}:{i}: {line.rstrip()}")
                    if len(hits) >= _CAP_GREP:
                        hits.append(f"... [{_CAP_GREP} hits limit reached]")
                        return "\n".join(hits)
        if not hits:
            return f"[grep_usages] No matches for '{pattern_str}'"
        return "\n".join(hits)

    return _call


def make_list_files_in_dir(repo_root: Path) -> ToolFn:
    """List files and subdirectories relative to ``repo_root``.

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        A tool function ``(args) -> str``.  Accepts ``path`` (default
        ``"."``), which is interpreted relative to ``repo_root``.
    """

    def _call(args: dict[str, Any]) -> str:
        rel_path = str(args.get("path", "."))
        target = repo_root / rel_path
        if not target.exists():
            return f"[list_files_in_dir] Path '{rel_path}' does not exist"
        if not target.is_dir():
            return f"[list_files_in_dir] '{rel_path}' is a file, not a directory"
        all_entries = sorted(target.iterdir())
        truncated = len(all_entries) > _CAP_LIST_FILES
        entries = all_entries[:_CAP_LIST_FILES]
        lines: list[str] = []
        for e in entries:
            try:
                rel = e.relative_to(repo_root)
            except ValueError:
                rel = e
            suffix = "/" if e.is_dir() else ""
            lines.append(f"{rel}{suffix}")
        if truncated:
            lines.append(f"... [{_CAP_LIST_FILES} entries limit reached]")
        return "\n".join(lines) or "[list_files_in_dir] Empty directory"

    return _call


def make_read_lines(repo_root: Path) -> ToolFn:
    """Read specific lines from a file (up to ``_CAP_LINES`` lines).

    Args:
        repo_root: Absolute path to the repository root.

    Returns:
        A tool function ``(args) -> str``.  Accepts ``file_path`` (relative to
        ``repo_root``), ``start`` (1-indexed, default 1), and ``end``
        (1-indexed inclusive, default ``start + 50``).
    """

    def _call(args: dict[str, Any]) -> str:
        file_path = str(args.get("file_path", ""))
        start = int(args.get("start", 1))
        end_arg = args.get("end")
        end = int(end_arg) if end_arg is not None else start + 50
        target = repo_root / file_path
        if not target.exists():
            return f"[read_lines] File '{file_path}' does not exist"
        if not target.is_file():
            return f"[read_lines] '{file_path}' is not a file"
        try:
            all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            return f"[read_lines] Cannot read '{file_path}': {e}"
        start_idx = max(0, start - 1)
        end_idx = min(len(all_lines), end, start_idx + _CAP_LINES)
        selected = all_lines[start_idx:end_idx]
        header = f"# {file_path} lines {start_idx + 1}-{start_idx + len(selected)}\n"
        return header + "\n".join(selected)

    return _call


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------


def build_tool_registry(
    *,
    symbols: list[CodeSymbol],
    graph: CallGraph,
    vector_store: VectorStore,
    repo_root: Path,
) -> dict[str, ToolFn]:
    """Build a ``name → tool_fn`` registry.  Called once per run.

    All closures capture their snapshot arguments at construction time so
    subsequent calls are effectively stateless from the caller's perspective.

    Args:
        symbols: All symbols from the ingestion + analysis snapshot.
        graph: The resolved (Jedi-processed) call graph.
        vector_store: An indexed :class:`~wiedunflow.interfaces.ports.VectorStore`.
        repo_root: Absolute path to the repository root used for file tools.

    Returns:
        Dictionary mapping tool names to their ``(args) -> str`` callables.
    """
    return {
        "read_symbol_body": make_read_symbol_body(symbols),
        "get_callers": make_get_callers(symbols, graph),
        "get_callees": make_get_callees(symbols, graph),
        "search_docs": make_search_docs(vector_store),
        "read_tests": make_read_tests(repo_root, symbols),
        "grep_usages": make_grep_usages(repo_root),
        "list_files_in_dir": make_list_files_in_dir(repo_root),
        "read_lines": make_read_lines(repo_root),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _iter_python_files(root: Path, skip_dirs: set[str]) -> Iterator[Path]:
    """Yield ``*.py`` files under *root*, skipping directories in *skip_dirs*."""
    for path in root.rglob("*.py"):
        if not any(part in skip_dirs for part in path.parts):
            yield path
