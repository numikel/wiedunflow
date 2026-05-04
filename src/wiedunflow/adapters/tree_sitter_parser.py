# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Real tree-sitter parser adapter — implements the Parser port for Python source."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import tree_sitter_python as _tspy
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from wiedunflow.entities.cache_entry import FileCacheEntry
from wiedunflow.entities.call_graph import CallGraph
from wiedunflow.entities.code_symbol import CodeSymbol, SymbolKind

if TYPE_CHECKING:
    from wiedunflow.interfaces.ports import Cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons — Language and Parser are thread-safe after init.
# ---------------------------------------------------------------------------
_PY_LANGUAGE: Language = Language(_tspy.language())
_PARSER: Parser = Parser(_PY_LANGUAGE)

# Query: capture every function/class definition node and its name.
# Both patterns share the same capture names so a single pass suffices.
# NOTE: in tree-sitter-python>=0.25, async def is a function_definition node
# (async is an inline keyword child), not a separate async_function_definition.
_QUERY_DEFS: Query = Query(
    _PY_LANGUAGE,
    """
    (function_definition name: (identifier) @name) @def
    (class_definition    name: (identifier) @name) @def
    """,
)

# Query: capture callee identifiers from call expressions.
_QUERY_CALLS: Query = Query(
    _PY_LANGUAGE,
    """
    (call function:
      [(identifier) @callee
       (attribute attribute: (identifier) @callee)])
    """,
)

# Node types that introduce a new scope for qualified-name building.
# async def is represented as function_definition in tree-sitter-python>=0.25.
_DEF_TYPES: frozenset[str] = frozenset({"function_definition", "class_definition"})
# Node types whose content belongs to the enclosing definition's body.
_BODY_TYPES: frozenset[str] = frozenset({"block"})

# Minimum length of a single-quoted string: one char + two quote chars.
_MIN_SINGLE_QUOTE_LEN = 2


class TreeSitterParser:
    """Production parser adapter using tree-sitter 0.25+ Python grammar.

    Implements the :class:`~wiedunflow.interfaces.ports.Parser` Protocol.  Produces
    a raw :class:`~wiedunflow.entities.call_graph.CallGraph` where
    ``resolution_stats`` is ``None`` — the Jedi resolver fills that in.

    Call edges carry the raw callee text (identifier or attribute leaf), *not*
    a fully-qualified name.  Cross-file resolution is Track B's responsibility.
    """

    def parse(
        self,
        files: list[Path],
        repo_root: Path,
        cache: Cache | None = None,
    ) -> tuple[list[CodeSymbol], CallGraph]:
        """Parse *files* relative to *repo_root* and return symbols + raw call graph.

        Args:
            files: Source files to parse.  May be absolute or relative; the
                qualified name is always derived from the path relative to
                *repo_root*.
            repo_root: Repository anchor used to derive module-qualified names
                (``package.module.ClassName.method_name``).
            cache: Optional content-addressed file cache (ADR-0008). When
                supplied, every file's SHA-256 is consulted before parsing;
                cache hits skip the tree-sitter pass entirely. Misses parse
                normally and store the per-file slice for the next run.

        Returns:
            ``(symbols, raw_graph)`` where ``raw_graph.resolution_stats is None``.
        """
        symbols: list[CodeSymbol] = []
        raw_edges: list[tuple[str, str]] = []

        for file_path in files:
            abs_path = file_path if file_path.is_absolute() else repo_root / file_path
            try:
                source = abs_path.read_bytes()
            except OSError:
                logger.warning("tree-sitter: cannot read %s — skipping", abs_path)
                continue

            sha = _sha256_bytes(source) if cache is not None else None
            if cache is not None and sha is not None:
                cached = cache.get_file_cache(sha)
                if cached is not None and cached.ast_json and cached.callgraph_json:
                    file_symbols, file_edges = _decode_cached_payload(cached)
                    symbols.extend(file_symbols)
                    raw_edges.extend(file_edges)
                    continue

            rel_path = abs_path.relative_to(repo_root)
            module_prefix = _path_to_module(rel_path)

            tree = _PARSER.parse(source)
            root = tree.root_node

            file_symbols = _extract_symbols(root, module_prefix, rel_path, source)
            symbols.extend(file_symbols)

            symbol_names = {s.name for s in file_symbols}
            file_edges = _extract_calls(root, module_prefix, symbol_names, source)
            raw_edges.extend(file_edges)

            if cache is not None and sha is not None:
                cache.save_file_cache(
                    FileCacheEntry(
                        sha256=sha,
                        ast_json=_encode_symbols(file_symbols),
                        callgraph_json=_encode_edges(file_edges),
                        created_at=datetime.now(UTC),
                    )
                )

        return symbols, CallGraph(
            nodes=tuple(symbols),
            edges=tuple(raw_edges),
            resolution_stats=None,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _path_to_module(rel_path: Path) -> str:
    """Convert a relative ``.py`` path to a dotted module prefix.

    Examples::

        Path("calculator.py")           -> "calculator"
        Path("pkg/sub/helper.py")       -> "pkg.sub.helper"
        Path("pkg/__init__.py")         -> "pkg.__init__"
    """
    parts = rel_path.with_suffix("").parts
    return ".".join(parts)


def _extract_docstring(def_node: Node, source: bytes) -> str | None:
    """Return the first string literal in *def_node*'s body, or ``None``.

    Handles triple-quoted and single-quoted docstrings.  Strips surrounding
    quote characters from the raw bytes without importing ``ast``.

    Args:
        def_node: A tree-sitter Node of type ``function_definition``,
            ``async_function_definition``, or ``class_definition``.
        source: Raw source bytes of the file (used for ``node.text``).
    """
    _ = source  # kept for API symmetry; node.text already contains the raw bytes
    body = def_node.child_by_field_name("body")
    if body is None or body.named_child_count == 0:
        return None
    first = body.named_child(0)
    if first is None or first.type != "expression_statement":
        return None
    if first.child_count == 0:
        return None
    string_node = first.children[0]
    if string_node.type != "string":
        return None
    raw: bytes = string_node.text or b""
    return _strip_quotes(raw.decode("utf-8", errors="replace"))


def _node_text(node: Node) -> str:
    """Decode a tree-sitter node's text bytes to a UTF-8 string.

    ``node.text`` is typed as ``bytes | None`` in the stubs; we treat ``None``
    (which occurs only for non-leaf / error nodes) as an empty string.
    """
    raw = node.text
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace")


_TRIPLE_QUOTES = ('"""', "'''")
_SINGLE_QUOTES = ('"', "'")


def _strip_quotes(raw: str) -> str | None:
    """Strip surrounding quote characters from a raw string literal."""
    for q in _TRIPLE_QUOTES:
        if raw.startswith(q) and raw.endswith(q) and len(raw) >= len(q) * 2:
            return raw[len(q) : -len(q)].strip()
    for q in _SINGLE_QUOTES:
        if raw.startswith(q) and raw.endswith(q) and len(raw) >= _MIN_SINGLE_QUOTE_LEN:
            return raw[1:-1].strip()
    return raw.strip() if raw.strip() else None


def _node_kind(node_type: str) -> SymbolKind:
    """Map a tree-sitter node type to a :class:`SymbolKind` literal."""
    if node_type == "class_definition":
        return "class"
    return "function"  # covers function_definition (sync and async)


def _walk_defs(
    node: Node,
    module_prefix: str,
    rel_path: Path,
    source: bytes,
    out: list[CodeSymbol],
    scope: str,
) -> None:
    """Recursively walk *node* collecting function and class definitions.

    Args:
        node: Current tree-sitter Node.
        module_prefix: Dotted module path derived from the file location.
        rel_path: File path relative to repo root (stored on each symbol).
        source: Raw source bytes (for docstring extraction).
        out: Accumulator list for discovered :class:`CodeSymbol` objects.
        scope: Current qualified-name prefix (starts as *module_prefix*).
    """
    for child in node.children:
        child_type = child.type

        # Unwrap decorated_definition transparently.
        if child_type == "decorated_definition":
            _walk_defs(child, module_prefix, rel_path, source, out, scope)
            continue

        if child_type in _DEF_TYPES:
            name_node = child.child_by_field_name("name")
            if name_node is None:
                _walk_defs(child, module_prefix, rel_path, source, out, scope)
                continue

            sym_name_str = _node_text(name_node)
            qualified = f"{scope}.{sym_name_str}" if scope else sym_name_str

            docstring = _extract_docstring(child, source)
            kind = _node_kind(child_type)
            row, _ = child.start_point
            end_row, _ = child.end_point

            out.append(
                CodeSymbol(
                    name=qualified,
                    kind=kind,
                    file_path=rel_path,
                    lineno=row + 1,
                    end_lineno=end_row + 1,
                    docstring=docstring,
                    is_dynamic_import=False,
                    is_uncertain=False,
                )
            )
            # Recurse into body with updated scope.
            _walk_defs(child, module_prefix, rel_path, source, out, qualified)

        elif child_type in _BODY_TYPES:
            _walk_defs(child, module_prefix, rel_path, source, out, scope)


def _extract_symbols(
    root: Node,
    module_prefix: str,
    rel_path: Path,
    source: bytes,
) -> list[CodeSymbol]:
    """Return all :class:`CodeSymbol` objects found in *root*."""
    symbols: list[CodeSymbol] = []
    _walk_defs(root, module_prefix, rel_path, source, symbols, module_prefix)
    return symbols


def _extract_calls(
    root: Node,
    module_prefix: str,
    local_symbol_names: set[str],
    source: bytes,
) -> list[tuple[str, str]]:
    """Return raw call edges ``(caller_qualified_name, callee_text)``.

    The *caller* is approximated as the innermost enclosing function/class that
    contains the call site.  If no enclosing definition is found, the edge is
    attributed to the module itself (``module_prefix``).

    Args:
        root: Root tree-sitter Node for the file.
        module_prefix: Dotted module name for the file.
        local_symbol_names: Qualified names of symbols in this file
            (used to associate callee text with a local definition for
            edges within the same module).
        source: Raw source bytes (unused here; kept for API symmetry).
    """
    _ = source  # unused — node.text provides the raw bytes when needed
    edges: list[tuple[str, str]] = []

    cursor = QueryCursor(_QUERY_CALLS)
    for _, captures in cursor.matches(root):
        callee_nodes = captures.get("callee", [])
        for callee_node in callee_nodes:
            callee_text = _node_text(callee_node)
            caller = _find_enclosing_def(callee_node, module_prefix)
            if caller in local_symbol_names:
                edges.append((caller, callee_text))

    return edges


def _find_enclosing_def(node: Node, module_prefix: str) -> str:
    """Walk up the parent chain to find the innermost enclosing definition name.

    Returns the fully-qualified name built from *module_prefix* + all enclosing
    definition names, or *module_prefix* if the call is at module scope.
    """
    scope_parts: list[str] = []

    current = node.parent
    while current is not None:
        if current.type in _DEF_TYPES:
            name_node = current.child_by_field_name("name")
            if name_node is not None:
                scope_parts.append(_node_text(name_node))
        current = current.parent

    scope_parts.reverse()
    if not scope_parts:
        return module_prefix
    return f"{module_prefix}.{'.'.join(scope_parts)}"


# ---------------------------------------------------------------------------
# File-cache payload codec (ADR-0008 file_cache table)
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest of *data*. Used as the file cache key."""
    return hashlib.sha256(data).hexdigest()


def _encode_symbols(symbols: list[CodeSymbol]) -> str:
    """Serialise a per-file ``CodeSymbol`` list to JSON for the file cache.

    ``mode='json'`` converts ``Path`` to ``str`` so the round-trip stays
    portable across operating systems and works even when the cache
    survives a directory move.
    """
    return json.dumps([s.model_dump(mode="json") for s in symbols])


def _decode_symbols(payload: str) -> list[CodeSymbol]:
    """Reconstruct a ``CodeSymbol`` list from the JSON payload."""
    raw = json.loads(payload)
    return [CodeSymbol.model_validate(item) for item in raw]


def _encode_edges(edges: list[tuple[str, str]]) -> str:
    """Serialise raw call-graph edges as a list of ``[caller, callee]`` pairs."""
    return json.dumps([[caller, callee] for caller, callee in edges])


def _decode_edges(payload: str) -> list[tuple[str, str]]:
    """Reconstruct raw edge tuples from the JSON payload."""
    raw = json.loads(payload)
    return [(caller, callee) for caller, callee in raw]


def _decode_cached_payload(entry: FileCacheEntry) -> tuple[list[CodeSymbol], list[tuple[str, str]]]:
    """Convert a stored :class:`FileCacheEntry` back into in-memory parser output.

    The caller has already verified ``ast_json`` and ``callgraph_json`` are
    populated, so the helper assumes both fields are present.
    """
    assert entry.ast_json is not None
    assert entry.callgraph_json is not None
    return _decode_symbols(entry.ast_json), _decode_edges(entry.callgraph_json)
