# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import platform
from pathlib import Path
from typing import Any, Literal, NamedTuple

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


class _ResolveOutcome(NamedTuple):
    """Result of a single Jedi Script resolution attempt.

    Using a NamedTuple ensures a single ``jedi.Script`` construction covers
    both the infer step and the downstream heuristic classification — the
    callee names list is threaded forward without re-instantiating Script.

    Attributes:
        state: One of ``"resolved"``, ``"resolved_heuristic"``, ``"uncertain"``,
            ``"unresolved"``, or ``"empty"`` (caller sym / source missing).
        names: Jedi Name objects when ``state`` is ``"resolved"``; the resolved
            target symbol name (``str``) for ``"resolved_heuristic"``; the
            matched callee name for ``"resolved"``; ``None`` otherwise.
        resolved_edge: The ``(caller, callee)`` pair when state is
            ``"resolved"`` or ``"resolved_heuristic"``, else ``None``.
    """

    state: Literal["resolved", "resolved_heuristic", "uncertain", "unresolved", "empty"]
    resolved_edge: tuple[str, str] | None


def _detect_python_path(repo_root: Path, override: Path | None = None) -> Path | None:
    """Detect a Python interpreter from common venv locations in the analyzed repo.

    Detection order:
        1. ``override`` — explicit user-provided path (from ``--python-path`` flag).
           If it does not exist, a WARNING is emitted and detection falls through
           to the candidates below.
        2. ``repo_root/.venv/{Scripts/python.exe | bin/python}``
        3. ``repo_root/venv/...``
        4. ``repo_root/env/...``

    Args:
        repo_root: Root of the repository being analyzed.
        override: Optional explicit interpreter path supplied by the caller
            (e.g. from the ``--python-path`` CLI flag).

    Returns:
        Absolute path to a Python interpreter, or ``None`` if nothing matched.
        Callers should pass this as ``environment_path`` to ``jedi.Project()``.
    """
    if override is not None:
        if override.exists():
            return override.resolve()
        logger.warning(
            "python_path_override_not_found",
            path=str(override),
            msg="Override interpreter not found; falling back to auto-detection.",
        )
        # Fall through to default detection.

    is_windows = platform.system() == "Windows"
    interpreter_subpath = Path("Scripts") / "python.exe" if is_windows else Path("bin") / "python"

    candidates = [".venv", "venv", "env"]
    for candidate in candidates:
        venv_python = repo_root / candidate / interpreter_subpath
        if venv_python.exists():
            logger.info(
                "venv_detected",
                path=str(venv_python),
                candidate=candidate,
            )
            return venv_python.resolve()

    logger.warning(
        "no_venv_detected",
        repo_root=str(repo_root),
        msg=(
            "Jedi will use WiedunFlow's own interpreter (may give low resolved_pct "
            "for cold-start repos). Use --python-path PATH or --bootstrap-venv to "
            "point Jedi at the analyzed repo's environment."
        ),
    )
    return None


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


def _resolve_single_edge(  # noqa: PLR0911 — each outcome branch returns a distinct state
    caller_name: str,
    callee_text: str,
    symbol_by_name: dict[str, CodeSymbol],
    source_cache: dict[Path, str],
    project: Any,
    repo_root: Path,
) -> _ResolveOutcome:
    """Attempt to resolve one raw edge using a SINGLE ``jedi.Script`` instantiation.

    Constructing ``jedi.Script`` is expensive (cold-start ~50 ms per unique
    file because Jedi builds its own module cache).  The previous design
    created a second Script inside ``_classify_edge`` when the first one
    returned no match — doubling cold-start cost for ~60% of edges that miss
    Tier 1.  This function folds both steps into one Script call and returns a
    richer ``_ResolveOutcome`` so ``_classify_edge`` only dispatches the result.

    Resolution order (all from one Script):
    1. Tier 1 strict: ``infer()`` returns a Name whose ``full_name`` maps to a
       known symbol → ``"resolved"``.
    2. Tier 1 uncertain: ``infer()`` returned results but none matched a known
       symbol → ``"uncertain"``.
    3. Tier 2 heuristic fallback: ``infer()`` returned ``[]`` → run
       ``_heuristic_name_match``; unique match → ``"resolved_heuristic"``,
       multiple → ``"uncertain"``, none → ``"unresolved"``.
    4. Caller symbol missing or source unreadable → ``"empty"``
       (treated as unresolved by the caller).

    Returns:
        A :class:`_ResolveOutcome` whose ``resolved_edge`` is set for
        ``"resolved"`` and ``"resolved_heuristic"`` states, ``None`` otherwise.
    """
    caller_sym = symbol_by_name.get(caller_name)
    if caller_sym is None:
        return _ResolveOutcome(state="empty", resolved_edge=None)

    caller_path = (
        caller_sym.file_path
        if caller_sym.file_path.is_absolute()
        else repo_root / caller_sym.file_path
    )
    source = _read_source(caller_path, source_cache)
    if source is None:
        return _ResolveOutcome(state="empty", resolved_edge=None)

    try:
        # Single Script construction for this (caller_path, source) pair.
        # The source_cache already deduplicates I/O; Script construction itself
        # is the bottleneck — do it exactly once per edge.
        script: Any = jedi.Script(code=source, path=str(caller_path.absolute()), project=project)
        references: list[Any] = script.get_names(
            all_scopes=True, references=True, definitions=False
        )
    except Exception:
        # Jedi can raise on malformed source or edge cases; treat as unresolved.
        return _ResolveOutcome(state="unresolved", resolved_edge=None)

    matching = [r for r in references if r.name == callee_text]

    # --- Tier 1: try strict infer() resolution ---
    if matching:
        strict_result = _infer_resolved_target(caller_name, matching, symbol_by_name)
        if strict_result is not None:
            return _ResolveOutcome(state="resolved", resolved_edge=strict_result)

        # Tier 1 uncertain: Jedi gave back results but no full_name matched a
        # known symbol.  Check whether infer() returned anything at all.
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
            return _ResolveOutcome(state="uncertain", resolved_edge=None)

    # --- Tier 2: heuristic name-based fallback when infer() returned [] ---
    candidates = _heuristic_name_match(callee_text, symbol_by_name)
    if len(candidates) == 1:
        logger.debug(
            "heuristic_resolved_edge",
            caller=caller_name,
            callee_text=callee_text,
            resolved_to=candidates[0],
        )
        return _ResolveOutcome(
            state="resolved_heuristic",
            resolved_edge=(caller_name, candidates[0]),
        )
    if len(candidates) > 1:
        logger.debug(
            "heuristic_ambiguous_edge",
            caller=caller_name,
            callee_text=callee_text,
            candidates=candidates,
        )
        return _ResolveOutcome(state="uncertain", resolved_edge=None)

    return _ResolveOutcome(state="unresolved", resolved_edge=None)


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
    """Mutable accumulator for 4-tier resolution counts (Tier 2: heuristic added v0.9.0)."""

    __slots__ = ("resolved", "resolved_heuristic", "uncertain", "unresolved")

    def __init__(self) -> None:
        self.resolved = 0
        self.uncertain = 0
        self.unresolved = 0
        self.resolved_heuristic = 0


def _heuristic_name_match(
    callee_text: str,
    symbol_by_name: dict[str, CodeSymbol],
) -> list[str]:
    """Tier 2 fallback: return all symbol full-names whose last component equals *callee_text*.

    Used when Jedi ``infer()`` returns an empty list — i.e. no venv / cold-start scenario.
    The caller decides the outcome:
    - 1 match  → ``resolved_heuristic`` (unique, safe to use)
    - >1 matches → ``uncertain``  (ambiguous — cannot pick one safely)
    - 0 matches → ``unresolved``  (nothing in the AST snapshot matches)

    Args:
        callee_text: The raw callee token from the parser edge (e.g. ``"bar"``).
        symbol_by_name: Mapping of fully-qualified name → CodeSymbol from the AST snapshot.

    Returns:
        List of full-name strings that match (may be empty).
    """
    suffix = "." + callee_text
    matches: list[str] = []
    for full_name in symbol_by_name:
        if full_name == callee_text or full_name.endswith(suffix):
            matches.append(full_name)
    return matches


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
    """Classify one edge and mutate *counts* / *resolved_edges* in place.

    Thin dispatcher: all resolution logic lives in ``_resolve_single_edge``.
    One ``jedi.Script`` is constructed there; this function only routes the
    ``_ResolveOutcome`` to the right counter bucket.
    """
    outcome = _resolve_single_edge(
        caller_name, callee_text, symbol_by_name, source_cache, project, repo_root
    )
    match outcome.state:
        case "resolved":
            assert outcome.resolved_edge is not None
            resolved_edges.append(outcome.resolved_edge)
            counts.resolved += 1
        case "resolved_heuristic":
            assert outcome.resolved_edge is not None
            resolved_edges.append(outcome.resolved_edge)
            counts.resolved_heuristic += 1
        case "uncertain":
            counts.uncertain += 1
        case "unresolved" | "empty":
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

    Args:
        python_path: Optional explicit path to a Python interpreter in the
            *analyzed* repo's virtual environment.  When ``None`` (default),
            :func:`_detect_python_path` auto-discovers ``.venv/``, ``venv/``,
            or ``env/`` in the repo root.  Corresponds to the
            ``--python-path`` CLI flag.
    """

    def __init__(self, *, python_path: Path | None = None) -> None:
        self._python_path_override: Path | None = python_path

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
        # Tier 1: pass environment_path when a venv is detected so Jedi can
        # resolve third-party symbols from the analyzed repo's site-packages.
        detected_python = _detect_python_path(repo_root, override=self._python_path_override)
        project_kwargs: dict[str, Any] = {"path": str(repo_root)}
        if detected_python is not None:
            project_kwargs["environment_path"] = str(detected_python)
        project: Any = jedi.Project(**project_kwargs)
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
            resolved_heuristic_count=counts.resolved_heuristic,
        )

        if resolved_pct < _RESOLVED_WARN_THRESHOLD:
            logger.warning(
                "low_jedi_resolution",
                resolved_pct=round(resolved_pct, 1),
                uncertain=counts.uncertain,
                unresolved=counts.unresolved,
                resolved_heuristic=counts.resolved_heuristic,
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
