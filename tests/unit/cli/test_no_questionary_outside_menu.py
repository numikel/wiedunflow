# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Lint rule (ADR-0013 decision 3): questionary imports confined to cli/menu.py.

The three-sink architecture (rich → output.py, questionary → menu.py, plain
print → menu_banner.py) keeps pipeline code UI-agnostic and the TUI layer
swappable. A ``from questionary`` import anywhere outside ``cli/menu.py`` is a
regression: cost gate, init wizard, and pipeline orchestration must receive
prompts via the ``MenuIO`` Protocol injection, never import questionary
directly.
"""

from __future__ import annotations

from pathlib import Path

_SRC_ROOT = Path(__file__).parent.parent.parent.parent / "src" / "codeguide"
_ALLOWLIST = {
    "src/codeguide/cli/menu.py",
}


def test_no_questionary_outside_cli_menu() -> None:
    offenders: list[str] = []
    for py_file in _SRC_ROOT.rglob("*.py"):
        rel = py_file.relative_to(_SRC_ROOT.parent.parent).as_posix()
        if rel in _ALLOWLIST:
            continue
        text = py_file.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("from questionary") or stripped.startswith("import questionary"):
                offenders.append(f"{rel}: {stripped}")
    assert offenders == [], (
        "questionary imports must live in src/codeguide/cli/menu.py only; offenders:\n"
        + "\n".join(offenders)
    )
