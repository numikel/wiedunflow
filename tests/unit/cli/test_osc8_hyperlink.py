# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-055: OSC 8 hyperlink escape sequences for clickable terminal output."""
from __future__ import annotations

from pathlib import Path

from codeguide.cli.output import osc8_hyperlink


def test_osc8_hyperlink_wraps_path_with_escape_sequences(tmp_path: Path) -> None:
    target = tmp_path / "tutorial.html"
    target.write_text("<html></html>", encoding="utf-8")
    link = osc8_hyperlink(target)
    assert link.startswith("\x1b]8;;"), f"Expected OSC 8 open prefix, got: {link!r}"
    assert link.endswith("\x1b]8;;\x1b\\"), f"Expected OSC 8 close suffix, got: {link!r}"
    assert target.as_uri() in link


def test_osc8_hyperlink_respects_custom_label(tmp_path: Path) -> None:
    target = tmp_path / "tutorial.html"
    target.write_text("x", encoding="utf-8")
    link = osc8_hyperlink(target, label="Open tutorial")
    assert "Open tutorial" in link
