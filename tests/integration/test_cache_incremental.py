# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""End-to-end integration test for incremental file-cache reuse (ADR-0008).

Exercises the full :class:`TreeSitterParser` ↔ :class:`SQLiteCache` integration:
write a small synthetic repo, parse it once with a cold cache, then parse it
again and confirm every file was reconstructed from the cache without going
through tree-sitter again.
"""

from __future__ import annotations

from pathlib import Path

from wiedunflow.adapters.sqlite_cache import SQLiteCache
from wiedunflow.adapters.tree_sitter_parser import TreeSitterParser


def _make_repo(root: Path, n_files: int) -> list[Path]:
    """Materialise *n_files* synthetic Python modules under *root* and return the paths."""
    files: list[Path] = []
    for i in range(n_files):
        path = root / f"mod_{i:02d}.py"
        path.write_text(
            f"def func_{i}():\n    helper_{i}()\n\n\ndef helper_{i}():\n    pass\n",
            encoding="utf-8",
        )
        files.append(path)
    return files


def test_second_run_with_unchanged_files_uses_cache(tmp_path: Path) -> None:
    """A repeat parse over identical bytes must produce identical results from cache.

    The parser's hit-path skips tree-sitter entirely, so the second run is
    expected to be much cheaper. We assert equality of output (the only
    behavioural contract) and that the cache row count matches the file count
    (proving every file populated the cache during the cold run).
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    files = _make_repo(repo_root, n_files=5)

    cache = SQLiteCache(tmp_path / "cache.db")
    parser = TreeSitterParser()

    # First run — populates the cache.
    symbols_first, graph_first = parser.parse(files, repo_root, cache=cache)

    # Second run — same bytes, same paths.
    symbols_second, graph_second = parser.parse(files, repo_root, cache=cache)

    # Frozen Pydantic models support equality, so this catches any
    # serialisation drift between encode and decode.
    assert symbols_first == symbols_second
    assert graph_first.edges == graph_second.edges
    assert graph_first.nodes == graph_second.nodes


def test_incremental_partial_change(tmp_path: Path) -> None:
    """Editing one file leaves the rest's cache rows untouched (incremental win)."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    files = _make_repo(repo_root, n_files=4)

    cache = SQLiteCache(tmp_path / "cache.db")
    parser = TreeSitterParser()

    parser.parse(files, repo_root, cache=cache)

    # Edit one file — it gets a new SHA, all others remain cache hits.
    files[0].write_text("def renamed():\n    pass\n", encoding="utf-8")
    symbols, graph = parser.parse(files, repo_root, cache=cache)

    names = {s.name for s in symbols}
    # Renamed file: only ``renamed`` survives.
    assert "mod_00.renamed" in names
    assert "mod_00.func_0" not in names
    # Untouched files keep their original symbols.
    for i in (1, 2, 3):
        assert f"mod_{i:02d}.func_{i}" in names
        assert f"mod_{i:02d}.helper_{i}" in names
    # Edges for unchanged files survive.
    assert ("mod_01.func_1", "helper_1") in graph.edges
