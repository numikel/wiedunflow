# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import pytest

from wiedunflow.adapters.dynamic_import_detector import (
    detect_dynamic_imports,
    detect_import_markers,
    detect_strict_uncertainty,
)

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


# ---------------------------------------------------------------------------
# detect_strict_uncertainty — conservative function used for is_uncertain flag
# ---------------------------------------------------------------------------


class TestDetectStrictUncertainty:
    """detect_strict_uncertainty flags only importlib/dunder-import patterns."""

    def test_importlib_import_module_is_strict(self) -> None:
        source = "import importlib\nmod = importlib.import_module('os')\n"
        assert detect_strict_uncertainty(source) is True

    def test_dunder_import_is_strict(self) -> None:
        source = "mod = __import__('sys')\n"
        assert detect_strict_uncertainty(source) is True

    def test_getattr_is_not_strict(self) -> None:
        """getattr detects dynamic dispatch but does not mark is_uncertain."""
        source = "import os\nfn = getattr(os, 'getcwd')\n"
        assert detect_strict_uncertainty(source) is False

    def test_globals_subscript_is_not_strict(self) -> None:
        source = "fn = globals()['my_func']\n"
        assert detect_strict_uncertainty(source) is False

    def test_locals_subscript_is_not_strict(self) -> None:
        source = "fn = locals()['helper']\n"
        assert detect_strict_uncertainty(source) is False

    def test_static_import_is_not_strict(self) -> None:
        source = "import os\nfrom pathlib import Path\n"
        assert detect_strict_uncertainty(source) is False

    def test_empty_string_is_not_strict(self) -> None:
        assert detect_strict_uncertainty("") is False

    def test_syntax_error_is_not_strict(self) -> None:
        assert detect_strict_uncertainty("def (broken:") is False


# ---------------------------------------------------------------------------
# detect_import_markers — combined single-walk helper that returns both flags
# ---------------------------------------------------------------------------


class TestDetectImportMarkers:
    """Combined helper produces the same (dynamic, strict) split as the wrappers."""

    def test_importlib_sets_both_flags(self) -> None:
        source = "import importlib\nmod = importlib.import_module('os')\n"
        assert detect_import_markers(source) == (True, True)

    def test_dunder_import_sets_both_flags(self) -> None:
        source = "mod = __import__('sys')\n"
        assert detect_import_markers(source) == (True, True)

    def test_getattr_sets_only_dynamic(self) -> None:
        source = "import os\nfn = getattr(os, 'getcwd')\n"
        assert detect_import_markers(source) == (True, False)

    def test_globals_subscript_sets_only_dynamic(self) -> None:
        source = "fn = globals()['my_func']\n"
        assert detect_import_markers(source) == (True, False)

    def test_locals_subscript_sets_only_dynamic(self) -> None:
        source = "fn = locals()['helper']\n"
        assert detect_import_markers(source) == (True, False)

    def test_static_code_sets_neither_flag(self) -> None:
        source = "import os\nfrom pathlib import Path\nresult = os.getcwd()\n"
        assert detect_import_markers(source) == (False, False)

    def test_empty_source_returns_double_false(self) -> None:
        assert detect_import_markers("") == (False, False)

    def test_syntax_error_returns_double_false(self) -> None:
        assert detect_import_markers("def (broken:") == (False, False)

    def test_mixed_patterns_short_circuit_when_both_true(self) -> None:
        """Once both flags are True the walk may exit early — verify final result is correct."""
        source = "import importlib\nfn = getattr(os, 'x')\nmod = importlib.import_module('json')\n"
        assert detect_import_markers(source) == (True, True)

    def test_consistency_with_thin_wrappers(self) -> None:
        """Wrappers must agree with the combined helper across positive + negative corpus."""
        for _, src in _POSITIVE_CASES + _NEGATIVE_CASES:
            dyn, strict = detect_import_markers(src)
            assert detect_dynamic_imports(src) is dyn
            assert detect_strict_uncertainty(src) is strict
