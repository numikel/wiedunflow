# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import pytest

from wiedunflow.adapters.dynamic_import_detector import detect_dynamic_imports

# ---------------------------------------------------------------------------
# Parametrised positive cases — each pattern that MUST be detected
# ---------------------------------------------------------------------------

_POSITIVE_CASES: list[tuple[str, str]] = [
    (
        "importlib_import_module",
        "import importlib\nx = importlib.import_module('os')\n",
    ),
    (
        "dunder_import",
        "mod = __import__('sys')\n",
    ),
    (
        "dunder_import_dynamic_arg",
        "name = 'os'\nmod = __import__(name)\n",
    ),
    (
        "globals_subscript",
        "fn = globals()['my_func']\nfn()\n",
    ),
    (
        "locals_subscript",
        "fn = locals()['helper']\n",
    ),
    (
        "getattr_call",
        "import os\nfn = getattr(os, 'getcwd')\n",
    ),
    (
        "getattr_with_default",
        "import os\nfn = getattr(os, 'getcwd', None)\n",
    ),
]


@pytest.mark.parametrize("case_id,source", _POSITIVE_CASES, ids=[c[0] for c in _POSITIVE_CASES])
def test_detects_dynamic_pattern(case_id: str, source: str) -> None:
    """Each known dynamic-import pattern must be detected."""
    assert detect_dynamic_imports(source) is True, f"Expected True for case {case_id!r}"


# ---------------------------------------------------------------------------
# Negative cases — static imports and non-dynamic code must NOT be flagged
# ---------------------------------------------------------------------------

_NEGATIVE_CASES: list[tuple[str, str]] = [
    (
        "static_import",
        "import os\nfrom pathlib import Path\n",
    ),
    (
        "empty_string",
        "",
    ),
    (
        "comments_only",
        "# just a comment\n# nothing dynamic here\n",
    ),
    (
        "plain_function_call",
        "def foo():\n    return 42\n\nresult = foo()\n",
    ),
    (
        "string_contains_importlib",
        '# importlib.import_module is mentioned in a comment\ndoc = "importlib.import_module docs"\n',
    ),
]


@pytest.mark.parametrize("case_id,source", _NEGATIVE_CASES, ids=[c[0] for c in _NEGATIVE_CASES])
def test_ignores_static_code(case_id: str, source: str) -> None:
    """Static imports and plain code must not trigger dynamic detection."""
    assert detect_dynamic_imports(source) is False, f"Expected False for case {case_id!r}"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_syntax_error_returns_false() -> None:
    """Unparseable source should return False gracefully."""
    assert detect_dynamic_imports("def (broken syntax:") is False


def test_globals_call_without_subscript_returns_false() -> None:
    """Bare globals() call (e.g. passed as argument) without subscript is not flagged."""
    # globals() as an argument, not subscripted
    source = "d = dict(globals())\n"
    # This is a call to globals() but NOT subscripted — should NOT be flagged.
    assert detect_dynamic_imports(source) is False


def test_multiline_importlib() -> None:
    """Multi-line importlib usage is detected."""
    source = (
        "import importlib\n"
        "module_name = 'json'\n"
        "mod = importlib.import_module(\n"
        "    module_name\n"
        ")\n"
    )
    assert detect_dynamic_imports(source) is True
