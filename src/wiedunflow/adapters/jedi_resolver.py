# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path
from typing import Any

import jedi
import structlog

from wiedunflow.adapters.dynamic_import_detector import (
    detect_dynamic_imports,
    detect_strict_uncertainty,
)
from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.resolution_stats import ResolutionStats

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Minimum resolved_pct below which we emit a structured WARNING.
_RESOLVED_WARN_THRESHOLD = 50.0
# Minimum docstring coverage below which we emit a structured WARNING (US-038).
_DOCSTRING_WARN_THRESHOLD = 30.0


def _read_source(path: Path, cache: dict[Path, str]) -> str | None:
    """Return source text for *path*, populating *cache*; None on read error."""
    if path not in cache:
        try:
            cache[path] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return cache[path]


def _resolve_single_edge(
    caller_name: str,
    callee_text: str,
    symbol_by_name: dict[str, CodeSymbol],
    source_cache: dict[Path, str],
    project: Any,
    repo_root: Path,
) -> tuple[str, str] | None:
    """Attempt to resolve one raw edge.

    Returns:
        ``(caller_name, resolved_callee_name)`` when resolved,
        ``None`` for uncertain/unresolved edges (caller is responsible for
        counting in the appropriate bucket).
    """
    caller_sym = symbol_by_name.get(caller_name)
    if caller_sym is None:
        return None

    caller_path = (
        caller_sym.file_path
        if caller_sym.file_path.is_absolute()
        else repo_root / caller_sym.file_path
    )
    source = _read_source(caller_path, source_cache)
    if source is None:
        return None

    try:
        script: Any = jedi.Script(code=source, path=str(caller_path.absolute()), project=project)
        references: list[Any] = script.get_names(
            all_scopes=True, references=True, definitions=False
        )
    except Exception:
        # Jedi can raise on malformed source or edge cases; treat as unresolved.
        return None

    matching = [r for r in references if r.name == callee_text]
    if not matching:
        return None

    return _infer_resolved_target(caller_name, matching, symbol_by_name)


def _match_full_name(full_name: str, symbol_by_name: dict[str, CodeSymbol]) -> str | None:
    """Return the best-matching symbol name for a Jedi-resolved *full_name*.

    Tries in priority order:

    1. Exact match: ``full_name`` itself is a key in *symbol_by_name*.
    2. Last-component match: ``full_name.rsplit(".", 1)[-1]`` is a key
       (handles the common case where the parser stores bare names like ``"g"``
       but Jedi resolves to a qualified name like ``"b.g"``).

    Returns the matched symbol name, or ``None`` if no match is found.
    """
    if full_name in symbol_by_name:
        return full_name
    last = full_name.rsplit(".", 1)[-1]
    if last in symbol_by_name:
        return last
    return None


def _infer_resolved_target(
    caller_name: str,
    matching_refs: list[Any],
    symbol_by_name: dict[str, CodeSymbol],
) -> tuple[str, str] | None:
    """Run ``.infer()`` on *matching_refs* and return a resolved edge or None."""
    for ref in matching_refs:
        try:
            inferred: list[Any] = ref.infer()
        except Exception:
            continue
        for defn in inferred:
            full_name: str | None = defn.full_name
            if full_name is None:
                continue
            matched = _match_full_name(full_name, symbol_by_name)
            if matched is not None:
                return (caller_name, matched)
    return None


class _EdgeCounts:
    """Mutable accumulator for 3-tier resolution counts."""

    __slots__ = ("resolved", "uncertain", "unresolved")

    def __init__(self) -> None:
        self.resolved = 0
        self.uncertain = 0
        self.unresolved = 0


def _classify_edge(
    caller_name: str,
    callee_text: str,
    symbol_by_name: dict[str, CodeSymbol],
    source_cache: dict[Path, str],
    project: Any,
    repo_root: Path,
    counts: _EdgeCounts,
    resolved_edges: list[tuple[str, str]],
) -> None:
    """Classify one edge and mutate *counts* / *resolved_edges* in place."""
    result = _resolve_single_edge(
        caller_name, callee_text, symbol_by_name, source_cache, project, repo_root
    )
    if result is not None:
        resolved_edges.append(result)
        counts.resolved += 1
        return

    # Distinguish uncertain vs unresolved: uncertain means Jedi gave back
    # inferred results but no full_name matched a known symbol.
    caller_sym = symbol_by_name.get(caller_name)
    if caller_sym is None:
        counts.unresolved += 1
        return

    caller_path = (
        caller_sym.file_path
        if caller_sym.file_path.is_absolute()
        else repo_root / caller_sym.file_path
    )
    source = source_cache.get(caller_path)
    if source is None:
        counts.unresolved += 1
        return

    try:
        script: Any = jedi.Script(code=source, path=str(caller_path.absolute()), project=project)
        refs: list[Any] = script.get_names(all_scopes=True, references=True, definitions=False)
    except Exception:
        counts.unresolved += 1
        return

    matching = [r for r in refs if r.name == callee_text]
    any_inferred = False
    for ref in matching:
        try:
            inferred: list[Any] = ref.infer()
        except Exception:
            continue
        if inferred:
            any_inferred = True
            break

    if any_inferred:
        counts.uncertain += 1
    else:
        counts.unresolved += 1


def _propagate_dynamic_markers(
    symbols: list[CodeSymbol],
    source_cache: dict[Path, str],
    repo_root: Path,
) -> list[CodeSymbol]:
    """Return a new list with ``is_dynamic_import`` / ``is_uncertain`` set where needed."""
    updated: list[CodeSymbol] = []
    for sym in symbols:
        sym_path = sym.file_path if sym.file_path.is_absolute() else repo_root / sym.file_path
        source = _read_source(sym_path, source_cache)
        if source is not None and detect_dynamic_imports(source):
            # is_uncertain only when the *module itself* is dynamic (importlib/
            # __import__).  Plain getattr() usage keeps is_uncertain=False so
            # the symbol stays in allowed_symbols for the planning grounding set.
            is_uncertain = detect_strict_uncertainty(source)
            updated.append(
                sym.model_copy(update={"is_dynamic_import": True, "is_uncertain": is_uncertain})
            )
        else:
            updated.append(sym)
    return updated


class JediResolver:
    """Real Jedi-powered ``Resolver`` adapter.

    Implements the :class:`~wiedunflow.interfaces.ports.Resolver` Protocol via
    duck typing.  Consumes the raw ``CallGraph`` emitted by the parser and
    returns a refined graph where:

    * Edges are retained only when Jedi can resolve the callee to a known
      ``CodeSymbol``.
    * ``is_dynamic_import`` / ``is_uncertain`` markers are set on symbols
      whose source files contain dynamic-import patterns.
    * A :class:`~wiedunflow.entities.resolution_stats.ResolutionStats` summary
      is attached so the planning stage can gate on coverage quality.

    Resolution is 3-tiered per edge:

    * **resolved**  -- ``infer()`` returned a ``Name`` with a non-None
      ``full_name`` that matches a known symbol.
    * **uncertain** -- ``infer()`` returned results but ``full_name`` is
      ``None`` for all of them.
    * **unresolved** -- ``infer()`` returned an empty list, the caller symbol
      was not found, or Jedi raised an exception for this edge.
    """

    def resolve(
        self,
        symbols: list[CodeSymbol],
        raw_graph: CallGraph,
        repo_root: Path,
    ) -> CallGraph:
        """Resolve raw-graph edges against *symbols* using Jedi.

        For each raw edge ``(caller_name, callee_text)``:

        1. Locate the caller ``CodeSymbol`` by name.
        2. Read the caller source file (cached).
        3. Use ``jedi.Script.get_names(references=True)`` to enumerate all
           references matching ``callee_text`` in that file.

           *Note*: file-level approximation -- column-level narrowing would
           require re-running tree-sitter and is out of scope for Sprint 2.

        4. Call ``.infer()`` on each matching reference; keep the edge only
           when ``full_name`` maps to a known ``CodeSymbol.name``.

        After edge resolution, propagate ``is_dynamic_import`` / ``is_uncertain``
        onto symbols whose source files contain dynamic-import patterns.

        Args:
            symbols: All ``CodeSymbol`` objects from the parser.
            raw_graph: Raw call graph (``resolution_stats`` is ``None``).
            repo_root: Repository root for cross-file Jedi resolution.

        Returns:
            A new ``CallGraph`` with ``resolution_stats`` populated.
        """
        symbol_by_name: dict[str, CodeSymbol] = {s.name: s for s in symbols}
        # One Project per resolve() call -- heavy object, reused across all edges.
        # smart_sys_path=True (default) detects src-layout automatically.
        project: Any = jedi.Project(path=str(repo_root))
        source_cache: dict[Path, str] = {}
        resolved_edges: list[tuple[str, str]] = []
        counts = _EdgeCounts()

        for caller_name, callee_text in raw_graph.edges:
            _classify_edge(
                caller_name,
                callee_text,
                symbol_by_name,
                source_cache,
                project,
                repo_root,
                counts,
                resolved_edges,
            )

        total = len(raw_graph.edges)
        resolved_pct = 100.0 if total == 0 else 100.0 * counts.resolved / total

        stats = ResolutionStats(
            resolved_pct=resolved_pct,
            uncertain_count=counts.uncertain,
            unresolved_count=counts.unresolved,
        )

        if resolved_pct < _RESOLVED_WARN_THRESHOLD:
            logger.warning(
                "low_jedi_resolution",
                resolved_pct=round(resolved_pct, 1),
                uncertain=counts.uncertain,
                unresolved=counts.unresolved,
            )

        updated_symbols = _propagate_dynamic_markers(symbols, source_cache, repo_root)

        # Validator requires all edge endpoints to exist in nodes.
        updated_names = {s.name for s in updated_symbols}
        validated_edges = [
            (c, e) for c, e in resolved_edges if c in updated_names and e in updated_names
        ]

        return CallGraph(
            nodes=tuple(updated_symbols),
            edges=tuple(validated_edges),
            resolution_stats=stats,
        )


def log_docstring_coverage(symbols: list[CodeSymbol]) -> None:
    """Emit a WARNING when docstring coverage falls below threshold (US-038).

    Call this after Jedi resolution completes if docstring coverage reporting
    is desired.

    Args:
        symbols: Resolved symbol list.
    """
    if not symbols:
        return
    covered = sum(1 for s in symbols if s.docstring is not None)
    pct = 100.0 * covered / len(symbols)
    if pct < _DOCSTRING_WARN_THRESHOLD:
        logger.warning(
            "low_docstring_coverage",
            docstring_coverage_pct=round(pct, 1),
            symbols_with_docstring=covered,
            total_symbols=len(symbols),
        )
