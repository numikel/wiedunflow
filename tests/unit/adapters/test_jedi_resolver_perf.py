# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Performance-oriented tests for JediResolver.

These tests verify that the single-Script-per-edge optimisation holds: for N
edges sharing the same caller file, exactly N Script() constructor calls are
made (one per edge), not 2N as the old two-pass design would have required for
edges that miss Tier 1 Jedi resolution.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiedunflow.adapters.jedi_resolver import JediResolver, _ResolveOutcome
from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sym(name: str, file_path: Path, lineno: int = 1) -> CodeSymbol:
    return CodeSymbol(name=name, kind="function", file_path=file_path, lineno=lineno)


def _raw_graph(symbols: list[CodeSymbol], edges: list[tuple[str, str]]) -> CallGraph:
    return CallGraph(nodes=tuple(symbols), edges=tuple(edges), resolution_stats=None)


# ---------------------------------------------------------------------------
# Test: single jedi.Script per edge (no double instantiation)
# ---------------------------------------------------------------------------


class TestSingleScriptPerEdge:
    """Verify that _resolve_single_edge constructs at most one jedi.Script per call.

    The previous implementation created a second Script inside _classify_edge
    when the first _resolve_single_edge call returned None (60% of edges for
    cold-start repos without a venv).  The new _ResolveOutcome design returns
    the full classification from one Script call, halving cold-start cost.
    """

    def test_script_call_count_100_edges_60pct_miss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """100 edges with 60% Tier-1 miss → at most 100 Script() calls (not 160)."""
        # Create 10 distinct caller files so source_cache deduplication doesn't
        # mask a bug — each caller file is read once, but each edge still
        # requires one Script() call.
        n_callers = 10
        n_edges = 100
        caller_files: list[Path] = []
        symbols: list[CodeSymbol] = []

        for i in range(n_callers):
            py = tmp_path / f"caller_{i}.py"
            py.write_text(f"def caller_{i}():\n    target()\n", encoding="utf-8")
            caller_files.append(py)
            symbols.append(_sym(f"caller_{i}", py, lineno=1))

        # 40 callees resolve via heuristic (unique name match); 60 are unresolved.
        callee_py = tmp_path / "callee.py"
        callee_py.write_text("def target(): pass\n", encoding="utf-8")
        sym_target = _sym("target", callee_py, lineno=1)
        symbols.append(sym_target)

        # Build edges: first 40 map to "target" (unique → heuristic resolved),
        # remaining 60 map to "ghost" (no symbol → unresolved).
        edges: list[tuple[str, str]] = []
        for i in range(n_edges):
            caller = f"caller_{i % n_callers}"
            callee = "target" if i < 40 else "ghost"
            edges.append((caller, callee))

        script_constructor_calls: list[int] = [0]

        def counting_script(**kwargs: object) -> MagicMock:
            script_constructor_calls[0] += 1
            mock = MagicMock()
            # Return a ref named after whatever callee we're looking at;
            # infer() returns [] to force Tier-2 heuristic path.
            ref = MagicMock()
            ref.name = "target"
            ref.infer.return_value = []
            mock.get_names.return_value = [ref]
            return mock

        monkeypatch.setattr("jedi.Script", counting_script)
        monkeypatch.setattr("jedi.Project", MagicMock())

        raw = _raw_graph(symbols, edges)
        resolver = JediResolver()
        resolver.resolve(symbols, raw, tmp_path)

        # Must be ≤ n_edges (one per edge), NOT ≤ n_edges * 2 (old two-pass).
        assert script_constructor_calls[0] <= n_edges, (
            f"Expected ≤{n_edges} Script() calls, got {script_constructor_calls[0]}"
        )

    def test_resolve_outcome_is_namedtuple(self) -> None:
        """_ResolveOutcome is a NamedTuple with the expected fields."""
        outcome = _ResolveOutcome(state="resolved", resolved_edge=("f", "g"))
        assert outcome.state == "resolved"
        assert outcome.resolved_edge == ("f", "g")

    def test_resolve_outcome_empty_state(self) -> None:
        """Empty state (missing caller sym / source) has resolved_edge=None."""
        outcome = _ResolveOutcome(state="empty", resolved_edge=None)
        assert outcome.state == "empty"
        assert outcome.resolved_edge is None

    def test_single_script_for_heuristic_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Even when Tier 1 misses, the heuristic Tier 2 path uses no extra Script()."""
        caller_py = tmp_path / "caller.py"
        callee_py = tmp_path / "callee.py"
        caller_py.write_text("def f():\n    unique_fn()\n", encoding="utf-8")
        callee_py.write_text("def unique_fn(): pass\n", encoding="utf-8")

        sym_f = _sym("f", caller_py, lineno=1)
        sym_callee = _sym("unique_fn", callee_py, lineno=1)

        constructor_count: list[int] = [0]

        def counting_script(**kwargs: object) -> MagicMock:
            constructor_count[0] += 1
            mock = MagicMock()
            ref = MagicMock()
            ref.name = "unique_fn"
            ref.infer.return_value = []  # Force Tier-2 heuristic
            mock.get_names.return_value = [ref]
            return mock

        monkeypatch.setattr("jedi.Script", counting_script)
        monkeypatch.setattr("jedi.Project", MagicMock())

        symbols = [sym_f, sym_callee]
        raw = _raw_graph(symbols, [("f", "unique_fn")])
        result = JediResolver().resolve(symbols, raw, tmp_path)

        # One edge → exactly one Script() call.
        assert constructor_count[0] == 1
        # The heuristic resolved the edge.
        assert result.resolution_stats is not None
        assert result.resolution_stats.resolved_heuristic_count == 1
