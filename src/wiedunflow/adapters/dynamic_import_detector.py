# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import ast


def detect_dynamic_imports(source: str) -> bool:
    """Return True if *source* contains any recognised dynamic-import pattern.

    The following five patterns are detected via ``ast.walk`` (stdlib AST, no
    regex):

    1. ``importlib.import_module(...)`` — any call whose ``.attr == "import_module"``.
    2. ``__import__(...)`` — any call to the built-in, regardless of argument type
       (conservative: flag all usages).
    3. ``globals()[name]`` — subscript access on a ``globals()`` call result.
    4. ``getattr(module, name)`` — any call to ``getattr``.  Conservative /
       high-recall: we flag *any* ``getattr`` call because determining whether the
       first argument is a module object requires full type inference (out of scope).
       Documented trade-off: expect false positives on non-import ``getattr`` usage.
    5. ``locals()[name]`` — mirror of pattern 3 for ``locals()``.

    Args:
        source: Python source code as a string.  May be empty or contain only
            comments.

    Returns:
        ``True`` if at least one dynamic-import pattern is detected; ``False``
        otherwise, including for empty or syntactically invalid source.
    """
    if not source.strip():
        return False

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    found = _has_dynamic_call(tree) or _has_subscript_on_scope_call(tree)
    return found


def _has_dynamic_call(tree: ast.AST) -> bool:
    """Return True if *tree* contains patterns 1-4 (Call-node patterns)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Pattern 1: importlib.import_module(...)
        if isinstance(func, ast.Attribute) and func.attr == "import_module":
            return True
        if isinstance(func, ast.Name):
            # Pattern 2: __import__(...)
            if func.id == "__import__":
                return True
            # Pattern 4: getattr(...)
            if func.id == "getattr":
                return True
    return False


def _has_subscript_on_scope_call(tree: ast.AST) -> bool:
    """Return True if *tree* has ``globals()[...]`` or ``locals()[...]`` (patterns 3 & 5)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        value = node.value
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id in ("globals", "locals")
        ):
            return True
    return False
