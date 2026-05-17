# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import ast


def detect_import_markers(source: str) -> tuple[bool, bool]:
    """Detect both dynamic-import and strict-uncertainty patterns in one AST walk.

    Returns a ``(has_dynamic, has_strict_uncertainty)`` tuple by walking the
    parsed AST exactly once. The strict-uncertainty flag is a subset of the
    dynamic flag (only ``importlib.import_module(...)`` and ``__import__(...)``).

    Patterns detected (set by which return-tuple slot):

    1. ``importlib.import_module(...)`` — sets both flags.
    2. ``__import__(...)`` — sets both flags.
    3. ``globals()[name]`` — sets only ``has_dynamic``.
    4. ``getattr(module, name)`` — sets only ``has_dynamic``
       (conservative / high-recall: flagged even when first arg is not a module).
    5. ``locals()[name]`` — sets only ``has_dynamic``.

    Args:
        source: Python source code as a string. May be empty or contain only
            comments.

    Returns:
        ``(has_dynamic, has_strict_uncertainty)``. Both are ``False`` for empty
        or syntactically invalid source.
    """
    if not source.strip():
        return False, False

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False, False

    has_dynamic = False
    has_strict = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "import_module":
                has_dynamic = True
                has_strict = True
            elif isinstance(func, ast.Name):
                if func.id == "__import__":
                    has_dynamic = True
                    has_strict = True
                elif func.id == "getattr":
                    has_dynamic = True
        elif isinstance(node, ast.Subscript):
            value = node.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id in ("globals", "locals")
            ):
                has_dynamic = True

        if has_dynamic and has_strict:
            break

    return has_dynamic, has_strict


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

    Thin wrapper over :func:`detect_import_markers`; callers that need both flags
    should call the combined helper directly to avoid a second AST traversal.
    """
    has_dynamic, _ = detect_import_markers(source)
    return has_dynamic


def detect_strict_uncertainty(source: str) -> bool:
    """Return True only for patterns where the *module itself* is dynamically determined.

    More conservative than :func:`detect_dynamic_imports`. Only flags
    ``importlib.import_module(...)`` and ``__import__(...)`` — patterns where
    the entire module resolved at runtime makes static FQN analysis impossible.

    The ``getattr`` pattern and ``globals/locals`` subscripts are intentionally
    excluded: while these affect *values* at runtime, the *symbols defined in
    the file* remain statically discoverable by tree-sitter, so marking them all
    as ``is_uncertain`` would incorrectly exclude them from the planner's
    grounding set.

    Used by :func:`~wiedunflow.adapters.jedi_resolver._propagate_dynamic_markers`
    to decide whether to set ``is_uncertain=True`` on a symbol (which removes it
    from ``allowed_symbols``). Thin wrapper over :func:`detect_import_markers`.
    """
    _, has_strict = detect_import_markers(source)
    return has_strict
