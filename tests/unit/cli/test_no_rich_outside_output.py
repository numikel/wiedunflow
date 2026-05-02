# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Lint rule (Sprint 5 decision #6): rich imports confined to cli/output.py.

The two-sink architecture keeps pipeline code UI-agnostic. A ``from rich``
import anywhere outside ``cli/output.py`` is a regression.
"""

from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).parent.parent.parent.parent / "src" / "wiedunflow"
_ALLOWLIST = {
    "src/wiedunflow/cli/output.py",
}


def test_no_rich_outside_cli_output() -> None:
    offenders: list[str] = []
    for py_file in _SRC_ROOT.rglob("*.py"):
        rel = py_file.relative_to(_SRC_ROOT.parent.parent).as_posix()
        if rel in _ALLOWLIST:
            continue
        text = py_file.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("from rich") or stripped.startswith("import rich"):
                offenders.append(f"{rel}: {stripped}")
    assert offenders == [], (
        "rich imports must live in src/wiedunflow/cli/output.py only; offenders:\n"
        + "\n".join(offenders)
    )
