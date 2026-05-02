# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wiedunflow.adapters.jedi_resolver import (
    JediResolver,
    _detect_python_path,
    _heuristic_name_match,
)
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
# Test: getattr-only file → is_dynamic_import=True, is_uncertain=False
# ---------------------------------------------------------------------------


def test_getattr_only_marks_dynamic_but_not_uncertain(
    tmp_path: Path,
    resolver: JediResolver,
) -> None:
    """A file using getattr (but no importlib) gets is_dynamic_import=True, is_uncertain=False.

    This ensures symbols in files with normal getattr usage are not excluded
    from the planning grounding set (allowed_symbols).
    """
    getattr_py = tmp_path / "dispatch.py"
    getattr_py.write_text(
        "def lookup(obj, attr: str):\n    return getattr(obj, attr)\n",
        encoding="utf-8",
    )

    sym = _sym("lookup", getattr_py, lineno=1)
    raw = _raw_graph([sym], [])

    result = resolver.resolve([sym], raw, tmp_path)

    output_sym = next(s for s in result.nodes if s.name == "lookup")
    assert output_sym.is_dynamic_import is True
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


# ---------------------------------------------------------------------------
# Tier 1 — _detect_python_path unit tests
# ---------------------------------------------------------------------------


class TestDetectPythonPath:
    """Unit tests for _detect_python_path() — Tier 1 venv auto-detection."""

    def _make_unix_venv(self, base: Path, name: str) -> Path:
        """Create a fake Unix-style venv interpreter under *base/<name>/bin/python*."""
        interp = base / name / "bin" / "python"
        interp.parent.mkdir(parents=True, exist_ok=True)
        interp.touch()
        return interp

    def _make_windows_venv(self, base: Path, name: str) -> Path:
        """Create a fake Windows-style venv interpreter under *base/<name>/Scripts/python.exe*."""
        interp = base / name / "Scripts" / "python.exe"
        interp.parent.mkdir(parents=True, exist_ok=True)
        interp.touch()
        return interp

    def test_finds_dot_venv_unix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        interp = self._make_unix_venv(tmp_path, ".venv")
        result = _detect_python_path(tmp_path)
        assert result == interp.resolve()

    def test_finds_dot_venv_windows(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("platform.system", lambda: "Windows")
        interp = self._make_windows_venv(tmp_path, ".venv")
        result = _detect_python_path(tmp_path)
        assert result == interp.resolve()

    def test_falls_back_to_venv_when_dot_venv_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        interp = self._make_unix_venv(tmp_path, "venv")
        result = _detect_python_path(tmp_path)
        assert result == interp.resolve()

    def test_falls_back_to_env_when_venv_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        interp = self._make_unix_venv(tmp_path, "env")
        result = _detect_python_path(tmp_path)
        assert result == interp.resolve()

    def test_dot_venv_preferred_over_venv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both .venv/ and venv/ exist, .venv/ must win (priority order)."""
        monkeypatch.setattr("platform.system", lambda: "Linux")
        dot_venv_interp = self._make_unix_venv(tmp_path, ".venv")
        self._make_unix_venv(tmp_path, "venv")
        result = _detect_python_path(tmp_path)
        assert result == dot_venv_interp.resolve()

    def test_returns_none_when_no_venv_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        result = _detect_python_path(tmp_path)
        assert result is None

    def test_returns_none_emits_no_venv_detected_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Warning event key 'no_venv_detected' must be emitted when no venv found."""
        monkeypatch.setattr("platform.system", lambda: "Linux")
        import wiedunflow.adapters.jedi_resolver as _mod

        warning_events: list[str] = []
        original_logger = _mod.logger

        class _CapturingLogger:
            def warning(self, event: str, **kw: object) -> None:  # type: ignore[override]
                warning_events.append(event)

            def info(self, event: str, **kw: object) -> None:  # type: ignore[override]
                pass

        monkeypatch.setattr(_mod, "logger", _CapturingLogger())
        try:
            _detect_python_path(tmp_path)
        finally:
            monkeypatch.setattr(_mod, "logger", original_logger)

        assert "no_venv_detected" in warning_events

    def test_override_wins_over_candidates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        override = tmp_path / "custom" / "python"
        override.parent.mkdir(parents=True)
        override.touch()
        # .venv/ also exists — override must still win.
        self._make_unix_venv(tmp_path, ".venv")
        result = _detect_python_path(tmp_path, override=override)
        assert result == override.resolve()

    def test_override_not_found_falls_back_with_warning(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        missing_override = tmp_path / "nonexistent" / "python"
        dot_venv_interp = self._make_unix_venv(tmp_path, ".venv")
        result = _detect_python_path(tmp_path, override=missing_override)
        assert result == dot_venv_interp.resolve()

    def test_override_not_found_emits_warning_event(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Warning event key 'python_path_override_not_found' emitted for bad override."""
        monkeypatch.setattr("platform.system", lambda: "Linux")
        self._make_unix_venv(tmp_path, ".venv")
        missing_override = tmp_path / "nonexistent" / "python"
        import wiedunflow.adapters.jedi_resolver as _mod

        warning_events: list[str] = []
        original_logger = _mod.logger

        class _CapturingLogger:
            def warning(self, event: str, **kw: object) -> None:  # type: ignore[override]
                warning_events.append(event)

            def info(self, event: str, **kw: object) -> None:  # type: ignore[override]
                pass

        monkeypatch.setattr(_mod, "logger", _CapturingLogger())
        try:
            _detect_python_path(tmp_path, override=missing_override)
        finally:
            monkeypatch.setattr(_mod, "logger", original_logger)

        assert "python_path_override_not_found" in warning_events


# ---------------------------------------------------------------------------
# Tier 1 — JediResolver.__init__ python_path + jedi.Project wiring
# ---------------------------------------------------------------------------


class TestJediResolverPythonPathWiring:
    """Verify JediResolver passes environment_path to jedi.Project() when a venv is found."""

    def _minimal_resolve(
        self,
        resolver: JediResolver,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> dict[str, object]:
        """Run resolve() with a trivial one-symbol no-edge graph; return captured jedi.Project kwargs."""
        captured: dict[str, object] = {}

        class _FakeProject:
            pass

        def fake_project(**kwargs: object) -> _FakeProject:
            captured.update(kwargs)
            return _FakeProject()

        monkeypatch.setattr("jedi.Project", fake_project)
        # Also patch jedi.Script to avoid running real Jedi.
        monkeypatch.setattr(
            "jedi.Script", MagicMock(return_value=MagicMock(get_names=lambda **_: []))
        )

        py = tmp_path / "mod.py"
        py.write_text("def f(): pass\n", encoding="utf-8")
        sym = _sym("f", py)
        raw = _raw_graph([sym], [])
        resolver.resolve([sym], raw, tmp_path)
        return captured

    def test_environment_path_present_when_venv_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        venv_python = tmp_path / ".venv" / "bin" / "python"
        venv_python.parent.mkdir(parents=True)
        venv_python.touch()

        resolver = JediResolver()
        kwargs = self._minimal_resolve(resolver, tmp_path, monkeypatch)

        assert kwargs.get("path") == str(tmp_path)
        assert "environment_path" in kwargs
        assert kwargs["environment_path"] == str(venv_python.resolve())

    def test_no_environment_path_when_no_venv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        # No venv directories created.
        resolver = JediResolver()
        kwargs = self._minimal_resolve(resolver, tmp_path, monkeypatch)

        assert kwargs.get("path") == str(tmp_path)
        assert "environment_path" not in kwargs

    def test_explicit_python_path_override_passed_to_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("platform.system", lambda: "Linux")
        override = tmp_path / "special" / "python"
        override.parent.mkdir(parents=True)
        override.touch()

        resolver = JediResolver(python_path=override)
        kwargs = self._minimal_resolve(resolver, tmp_path, monkeypatch)

        assert "environment_path" in kwargs
        assert kwargs["environment_path"] == str(override.resolve())


# ---------------------------------------------------------------------------
# Tier 2: _heuristic_name_match unit tests
# ---------------------------------------------------------------------------


class TestHeuristicNameMatch:
    """Unit tests for the _heuristic_name_match() helper (pure function)."""

    def _sym(self, name: str, tmp_path: Path) -> CodeSymbol:
        p = tmp_path / "x.py"
        p.touch()
        return CodeSymbol(name=name, kind="function", file_path=p, lineno=1)

    def test_exact_match_returned(self, tmp_path: Path) -> None:
        sym = self._sym("bar", tmp_path)
        result = _heuristic_name_match("bar", {"bar": sym})
        assert result == ["bar"]

    def test_last_component_match(self, tmp_path: Path) -> None:
        sym = self._sym("foo.bar", tmp_path)
        result = _heuristic_name_match("bar", {"foo.bar": sym})
        assert result == ["foo.bar"]

    def test_multiple_candidates_returned(self, tmp_path: Path) -> None:
        sym_a = self._sym("a.bar", tmp_path)
        sym_b = self._sym("b.bar", tmp_path)
        result = _heuristic_name_match("bar", {"a.bar": sym_a, "b.bar": sym_b})
        assert sorted(result) == ["a.bar", "b.bar"]

    def test_no_match_returns_empty(self, tmp_path: Path) -> None:
        sym = self._sym("foo.qux", tmp_path)
        result = _heuristic_name_match("bar", {"foo.qux": sym})
        assert result == []

    def test_partial_suffix_not_matched(self, tmp_path: Path) -> None:
        """'foobar' should NOT match callee_text='bar' (suffix must be '.bar')."""
        sym = self._sym("foobar", tmp_path)
        result = _heuristic_name_match("bar", {"foobar": sym})
        assert result == []

    def test_empty_symbol_map_returns_empty(self) -> None:
        result = _heuristic_name_match("bar", {})
        assert result == []


# ---------------------------------------------------------------------------
# Tier 2: JediResolver heuristic integration tests
# ---------------------------------------------------------------------------


class TestHeuristicFallback:
    """Tier 2 regression: name-based fallback when Jedi infer() returns empty.

    Strategy: monkeypatch jedi.Script so that infer() always returns [] for the
    call site, forcing _classify_edge to fall through to the heuristic path.
    """

    def _make_resolver_with_empty_infer(self, monkeypatch: pytest.MonkeyPatch) -> JediResolver:
        """Patch jedi.Script so that infer() always returns []."""
        mock_ref = MagicMock()
        mock_ref.name = None  # overridden per-test
        mock_ref.infer.return_value = []

        def fake_script(**kwargs: object) -> MagicMock:
            script_mock = MagicMock()
            # get_names returns a reference named after the requested callee.
            # We set name dynamically in the test via the fixture mechanism.
            script_mock.get_names.return_value = [mock_ref]
            return script_mock

        monkeypatch.setattr("jedi.Script", fake_script)
        monkeypatch.setattr("jedi.Project", MagicMock())
        return JediResolver()

    def _write_py(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def test_unique_name_match_is_resolved_heuristic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Single matching symbol → resolved_heuristic_count == 1."""
        caller_py = tmp_path / "caller.py"
        callee_py = tmp_path / "callee.py"
        self._write_py(caller_py, "def f():\n    bar()\n")
        self._write_py(callee_py, "def bar():\n    pass\n")

        sym_f = _sym("f", caller_py, lineno=1)
        sym_bar = _sym("bar", callee_py, lineno=1)

        # Patch get_names to return a ref named "bar" with empty infer().
        mock_ref = MagicMock()
        mock_ref.name = "bar"
        mock_ref.infer.return_value = []
        mock_script = MagicMock()
        mock_script.get_names.return_value = [mock_ref]
        monkeypatch.setattr("jedi.Script", MagicMock(return_value=mock_script))
        monkeypatch.setattr("jedi.Project", MagicMock())

        symbols = [sym_f, sym_bar]
        raw = _raw_graph(symbols, [("f", "bar")])
        result = JediResolver().resolve(symbols, raw, tmp_path)

        assert result.resolution_stats is not None
        assert result.resolution_stats.resolved_heuristic_count == 1
        assert result.resolution_stats.unresolved_count == 0
        # Heuristically resolved edge must appear in the output graph.
        assert ("f", "bar") in result.edges

    def test_ambiguous_name_is_uncertain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two symbols sharing 'bar' as last component → uncertain, NOT heuristic."""
        caller_py = tmp_path / "caller.py"
        self._write_py(caller_py, "def f():\n    bar()\n")
        mod_a = tmp_path / "mod_a.py"
        mod_b = tmp_path / "mod_b.py"
        self._write_py(mod_a, "def bar(): pass\n")
        self._write_py(mod_b, "def bar(): pass\n")

        sym_f = _sym("f", caller_py, lineno=1)
        # Two different full-names, both ending with "bar"
        sym_a_bar = _sym("mod_a.bar", mod_a, lineno=1)
        sym_b_bar = _sym("mod_b.bar", mod_b, lineno=1)

        mock_ref = MagicMock()
        mock_ref.name = "bar"
        mock_ref.infer.return_value = []
        mock_script = MagicMock()
        mock_script.get_names.return_value = [mock_ref]
        monkeypatch.setattr("jedi.Script", MagicMock(return_value=mock_script))
        monkeypatch.setattr("jedi.Project", MagicMock())

        symbols = [sym_f, sym_a_bar, sym_b_bar]
        raw = _raw_graph(symbols, [("f", "bar")])
        result = JediResolver().resolve(symbols, raw, tmp_path)

        assert result.resolution_stats is not None
        assert result.resolution_stats.uncertain_count == 1
        assert result.resolution_stats.resolved_heuristic_count == 0

    def test_zero_matches_stays_unresolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No name match → unresolved (Tier 2 does not conjure a target)."""
        caller_py = tmp_path / "caller.py"
        self._write_py(caller_py, "def f():\n    totally_unknown()\n")
        callee_py = tmp_path / "callee.py"
        self._write_py(callee_py, "def something_else(): pass\n")

        sym_f = _sym("f", caller_py, lineno=1)
        sym_other = _sym("something_else", callee_py, lineno=1)

        mock_ref = MagicMock()
        mock_ref.name = "totally_unknown"
        mock_ref.infer.return_value = []
        mock_script = MagicMock()
        mock_script.get_names.return_value = [mock_ref]
        monkeypatch.setattr("jedi.Script", MagicMock(return_value=mock_script))
        monkeypatch.setattr("jedi.Project", MagicMock())

        symbols = [sym_f, sym_other]
        raw = _raw_graph(symbols, [("f", "totally_unknown")])
        result = JediResolver().resolve(symbols, raw, tmp_path)

        assert result.resolution_stats is not None
        assert result.resolution_stats.unresolved_count == 1
        assert result.resolution_stats.resolved_heuristic_count == 0

    def test_strict_jedi_not_overridden_by_heuristic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tier 1 strict resolution must NOT be replaced by Tier 2 heuristic."""
        # Use real Jedi on the repo_ab fixture pattern (f → g, cross-file import).
        a_py = tmp_path / "a.py"
        b_py = tmp_path / "b.py"
        a_py.write_text("from b import g\n\ndef f():\n    g()\n", encoding="utf-8")
        b_py.write_text("def g():\n    pass\n", encoding="utf-8")

        sym_f = _sym("f", a_py, lineno=3)
        sym_g = _sym("g", b_py, lineno=1)
        symbols = [sym_f, sym_g]
        raw = _raw_graph(symbols, [("f", "g")])

        result = JediResolver().resolve(symbols, raw, tmp_path)

        assert result.resolution_stats is not None
        # Strict resolution handles this — heuristic count must be 0.
        assert result.resolution_stats.resolved_heuristic_count == 0
        assert result.resolution_stats.resolved_pct == pytest.approx(100.0, abs=0.1)

    def test_resolved_pct_remains_strict_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolved_pct counts only Tier 1 resolutions (backward compat).

        With 3 edges: 0 strict, 1 heuristic, 1 uncertain, 1 unresolved:
          - resolved_pct must be 0.0  (no strict resolutions)
          - resolved_heuristic_count must be 1
        """
        caller_py = tmp_path / "caller.py"
        self._write_py(caller_py, "def f():\n    bar()\n    unknown()\n    ambig()\n")
        mod_a = tmp_path / "mod_a.py"
        mod_b = tmp_path / "mod_b.py"
        self._write_py(mod_a, "def bar(): pass\ndef ambig(): pass\n")
        self._write_py(mod_b, "def ambig(): pass\n")

        sym_f = _sym("f", caller_py, lineno=1)
        sym_bar = _sym("bar", mod_a, lineno=1)
        sym_ambig_a = _sym("mod_a.ambig", mod_a, lineno=2)
        sym_ambig_b = _sym("mod_b.ambig", mod_b, lineno=1)

        def make_mock_ref(name: str) -> MagicMock:
            ref = MagicMock()
            ref.name = name
            ref.infer.return_value = []
            return ref

        call_count = 0

        def fake_script(**kwargs: object) -> MagicMock:
            nonlocal call_count
            script_mock = MagicMock()
            if call_count == 0:
                script_mock.get_names.return_value = [make_mock_ref("bar")]
            elif call_count == 1:
                script_mock.get_names.return_value = [make_mock_ref("unknown")]
            else:
                script_mock.get_names.return_value = [make_mock_ref("ambig")]
            call_count += 1
            return script_mock

        monkeypatch.setattr("jedi.Script", fake_script)
        monkeypatch.setattr("jedi.Project", MagicMock())

        symbols = [sym_f, sym_bar, sym_ambig_a, sym_ambig_b]
        # 3 edges: bar (unique heuristic match), unknown (no match), ambig (2 matches)
        raw = _raw_graph(symbols, [("f", "bar"), ("f", "unknown"), ("f", "ambig")])
        result = JediResolver().resolve(symbols, raw, tmp_path)

        assert result.resolution_stats is not None
        assert result.resolution_stats.resolved_pct == pytest.approx(0.0, abs=0.1)
        assert result.resolution_stats.resolved_heuristic_count == 1
        assert result.resolution_stats.unresolved_count == 1  # "unknown"
        assert result.resolution_stats.uncertain_count == 1  # "ambig" (2 candidates)

    def test_resolution_stats_resolved_pct_with_heuristic_populated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """resolved_pct_with_heuristic > resolved_pct when heuristic resolved some edges."""
        caller_py = tmp_path / "caller.py"
        self._write_py(caller_py, "def f():\n    bar()\n    unknown()\n")
        callee_py = tmp_path / "callee.py"
        self._write_py(callee_py, "def bar(): pass\n")

        sym_f = _sym("f", caller_py, lineno=1)
        sym_bar = _sym("bar", callee_py, lineno=1)

        call_count = 0

        def fake_script(**kwargs: object) -> MagicMock:
            nonlocal call_count
            script_mock = MagicMock()
            name = "bar" if call_count == 0 else "unknown"
            ref = MagicMock()
            ref.name = name
            ref.infer.return_value = []
            script_mock.get_names.return_value = [ref]
            call_count += 1
            return script_mock

        monkeypatch.setattr("jedi.Script", fake_script)
        monkeypatch.setattr("jedi.Project", MagicMock())

        symbols = [sym_f, sym_bar]
        raw = _raw_graph(symbols, [("f", "bar"), ("f", "unknown")])
        result = JediResolver().resolve(symbols, raw, tmp_path)

        stats = result.resolution_stats
        assert stats is not None
        # 2 edges: 0 strict, 1 heuristic, 0 uncertain, 1 unresolved
        assert stats.resolved_pct == pytest.approx(0.0, abs=0.1)
        assert stats.resolved_heuristic_count == 1
        assert stats.resolved_pct_with_heuristic == pytest.approx(50.0, abs=0.5)
