# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Regression: production CLI must wire SystemClock, not FakeClock (F-006)."""

from __future__ import annotations

import inspect


def test_main_uses_system_clock_in_production() -> None:
    from wiedunflow.cli import main as main_mod

    src = inspect.getsource(main_mod)
    assert "FakeClock" not in src, "FakeClock leaked into production CLI (cli/main.py)"
    assert "SystemClock" in src, "SystemClock not wired into production CLI (cli/main.py)"


def test_menu_uses_system_clock_in_production() -> None:
    from wiedunflow.cli import menu as menu_mod

    src = inspect.getsource(menu_mod)
    assert "FakeClock" not in src, "FakeClock leaked into production CLI (cli/menu.py)"
    assert "SystemClock" in src, "SystemClock not wired into production CLI (cli/menu.py)"
