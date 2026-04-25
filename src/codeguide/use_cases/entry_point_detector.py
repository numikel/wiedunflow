# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Detect user-facing entry-point symbols in a Python repository.

Entry-point detection is a heuristic post-processing step run after Stage 5
(planning) to identify symbols that serve as the "front door" of the repo.
The reorder hook in ``plan_lesson_manifest`` uses the result to move the
entry-point lesson to position 0.

Heuristics (any match qualifies a symbol):
1. Bare top-level ``def`` named exactly ``main``, ``cli``, ``run``, or matching
   the pattern ``r'^run_\\w+$'``.
2. A ``def`` that appears *inside* an ``if __name__ == "__main__":`` block.
3. A function decorated with ``@click.command``, ``@click.group``,
   ``@app.command`` (Typer), or ``@click.option`` (transitive).
4. A function whose body contains an ``argparse.ArgumentParser()`` call.
5. File is ``__main__.py`` and contains ``def main``.

Uses the tree-sitter Python grammar already installed for Stage 2 — no
additional dependencies are introduced.
"""

from __future__ import annotations

import re
from pathlib import Path

import structlog
import tree_sitter_python as _tspy
from tree_sitter import Language, Node, Parser

__all__ = ["detect_entry_points"]

logger = structlog.get_logger(__name__)

_PY_LANGUAGE: Language = Language(_tspy.language())
_PARSER: Parser = Parser(_PY_LANGUAGE)

# Pattern for implicit entry-point function names.
_ENTRY_NAME_RE = re.compile(r"^(main|cli|run|run_\w+)$")

# Decorator names that signal a click/Typer command.
_CLI_DECORATOR_NAMES: frozenset[str] = frozenset(
    {
        "command",
        "group",
        "option",  # transitive: decorated helpers are still entry-point adjacent
    }
)

# Attribute objects whose decorators count as CLI entry-point signals.
_CLI_DECORATOR_OBJECTS: frozenset[str] = frozenset({"click", "app"})


def detect_entry_points(
    repo_root: Path,
    file_paths: tuple[Path, ...],
) -> frozenset[str]:
    """Return qualified symbol names that look like user-facing entry points.

    Applies heuristics to each Python file and returns a ``frozenset`` of
    qualified symbol names (e.g. ``"main.main"``, ``"pkg.cli.run"``) that
    match at least one entry-point heuristic.

    Args:
        repo_root: Absolute path to the repository root.  ``file_paths`` are
            resolved relative to this root.
        file_paths: Relative paths (relative to *repo_root*) of Python files
            to inspect.

    Returns:
        A ``frozenset[str]`` of qualified symbol names.  Empty when no
        entry-point heuristics match any file.
    """
    results: set[str] = set()

    for rel_path in file_paths:
        abs_path = (repo_root / rel_path).resolve()
        try:
            source_bytes = abs_path.read_bytes()
        except OSError as exc:
            logger.debug("entry_point_detector_skip", file=str(rel_path), error=str(exc))
            continue

        module_prefix = _path_to_module(rel_path)
        is_main_module = rel_path.name == "__main__.py"

        tree = _PARSER.parse(source_bytes)
        _walk_file(tree.root_node, source_bytes, module_prefix, is_main_module, results)

    logger.debug("entry_points_detected", count=len(results), symbols=sorted(results))
    return frozenset(results)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _path_to_module(rel_path: Path) -> str:
    """Convert a relative ``.py`` path to a dotted module prefix.

    Examples::

        Path("main.py")              -> "main"
        Path("pkg/cli.py")           -> "pkg.cli"
        Path("pkg/__main__.py")      -> "pkg.__main__"
    """
    parts = rel_path.with_suffix("").parts
    return ".".join(parts)


def _node_text(node: Node, source: bytes) -> str:
    """Return the UTF-8 decoded text of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _walk_file(
    root: Node,
    source: bytes,
    module_prefix: str,
    is_main_module: bool,
    results: set[str],
) -> None:
    """Walk a file's AST and populate *results* with entry-point symbol names."""
    # Pass 1: collect top-level defs inside ``if __name__ == "__main__":`` blocks.
    main_guard_defs: set[str] = _collect_main_guard_calls(root, source)

    # Pass 2: walk top-level function definitions.
    for node in root.children:
        if node.type == "function_definition":
            _check_function(node, source, module_prefix, is_main_module, main_guard_defs, results)
        # Decorated function: (decorated_definition (decorator ...) (function_definition ...))
        elif node.type == "decorated_definition":
            _check_decorated_function(
                node, source, module_prefix, is_main_module, main_guard_defs, results
            )


def _check_function(
    func_node: Node,
    source: bytes,
    module_prefix: str,
    is_main_module: bool,
    main_guard_defs: set[str],
    results: set[str],
) -> None:
    """Check an undecorated function definition for entry-point heuristics."""
    name_node = func_node.child_by_field_name("name")
    if name_node is None:
        return
    func_name = _node_text(name_node, source)
    qualified = f"{module_prefix}.{func_name}" if module_prefix else func_name

    # Heuristic 1: name pattern.
    if _ENTRY_NAME_RE.match(func_name):
        results.add(qualified)
        return

    # Heuristic 2: inside __name__ == "__main__" block.
    if func_name in main_guard_defs:
        results.add(qualified)
        return

    # Heuristic 5: __main__.py + def main.
    if is_main_module and func_name == "main":
        results.add(qualified)
        return

    # Heuristic 4: argparse in body.
    if _has_argparse_in_body(func_node, source):
        results.add(qualified)


def _check_decorated_function(
    decorated_node: Node,
    source: bytes,
    module_prefix: str,
    is_main_module: bool,
    main_guard_defs: set[str],
    results: set[str],
) -> None:
    """Check a decorated function definition for click/Typer decorator heuristics."""
    # Find the inner function_definition.
    func_node: Node | None = None
    decorators: list[Node] = []
    for child in decorated_node.children:
        if child.type == "decorator":
            decorators.append(child)
        elif child.type == "function_definition":
            func_node = child

    if func_node is None:
        return

    name_node = func_node.child_by_field_name("name")
    if name_node is None:
        return
    func_name = _node_text(name_node, source)
    qualified = f"{module_prefix}.{func_name}" if module_prefix else func_name

    # Heuristic 3: CLI decorator present.
    for decorator in decorators:
        if _is_cli_decorator(decorator, source):
            results.add(qualified)
            return

    # Fall through to other heuristics (name pattern, main guard, argparse).
    _check_function(func_node, source, module_prefix, is_main_module, main_guard_defs, results)


def _is_cli_decorator(decorator_node: Node, source: bytes) -> bool:
    """Return True if *decorator_node* looks like a click/Typer command decorator."""
    # @click.command, @click.group, @app.command, etc.
    # The decorator body is everything after the '@'.
    for child in decorator_node.children:
        if child.type == "attribute":
            # attribute: (object) '.' (attribute) → e.g. click.command
            obj_node = child.child_by_field_name("object")
            attr_node = child.child_by_field_name("attribute")
            if obj_node is not None and attr_node is not None:
                obj_name = _node_text(obj_node, source)
                attr_name = _node_text(attr_node, source)
                if obj_name in _CLI_DECORATOR_OBJECTS and attr_name in _CLI_DECORATOR_NAMES:
                    return True
        elif child.type == "call":
            # @click.command(...) — the call wraps an attribute.
            func_child = child.child_by_field_name("function")
            if func_child is not None and func_child.type == "attribute":
                obj_node = func_child.child_by_field_name("object")
                attr_node = func_child.child_by_field_name("attribute")
                if obj_node is not None and attr_node is not None:
                    obj_name = _node_text(obj_node, source)
                    attr_name = _node_text(attr_node, source)
                    if obj_name in _CLI_DECORATOR_OBJECTS and attr_name in _CLI_DECORATOR_NAMES:
                        return True
    return False


def _has_argparse_in_body(func_node: Node, source: bytes) -> bool:
    """Return True if the function body contains an ``ArgumentParser()`` call."""
    body = func_node.child_by_field_name("body")
    if body is None:
        return False
    body_text = _node_text(body, source)
    return "ArgumentParser" in body_text


def _collect_main_guard_calls(root: Node, source: bytes) -> set[str]:
    """Return function names called inside ``if __name__ == "__main__":`` blocks.

    We collect *bare call names* (identifiers) from the body of the main guard
    so that any function called directly from the guard is also a candidate.
    """
    called: set[str] = set()
    for node in root.children:
        if node.type != "if_statement":
            continue
        condition = node.child_by_field_name("condition")
        if condition is None:
            continue
        cond_text = _node_text(condition, source)
        # Match: __name__ == "__main__" or "__main__" == __name__
        if "__name__" not in cond_text or "__main__" not in cond_text:
            continue
        # Walk the if body collecting bare function calls.
        body = node.child_by_field_name("consequence")
        if body is not None:
            _collect_calls_in_block(body, source, called)
    return called


def _collect_calls_in_block(block: Node, source: bytes, names: set[str]) -> None:
    """Recursively collect bare ``identifier`` call targets from *block*."""
    for child in block.children:
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type == "call":
                    func = sub.child_by_field_name("function")
                    if func is not None and func.type == "identifier":
                        names.add(_node_text(func, source))
        _collect_calls_in_block(child, source, names)
