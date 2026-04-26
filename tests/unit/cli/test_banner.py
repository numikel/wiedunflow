# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 8 US-086: startup banner renders version and tagline."""

from __future__ import annotations

import io

from rich.console import Console

from wiedunflow.cli.output import make_theme, render_banner


def _capture() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    console = Console(
        theme=make_theme(),
        file=buffer,
        force_terminal=False,
        no_color=True,
        width=80,
        legacy_windows=False,
    )
    return console, buffer


def test_banner_includes_codeguide_name() -> None:
    console, buffer = _capture()
    render_banner(console, version="0.2.0")
    assert "CodeGuide" in buffer.getvalue()


def test_banner_includes_version() -> None:
    console, buffer = _capture()
    render_banner(console, version="0.2.0")
    assert "v0.2.0" in buffer.getvalue()


def test_banner_includes_tagline() -> None:
    console, buffer = _capture()
    render_banner(console, version="0.2.0")
    assert "offline" in buffer.getvalue().lower() or "tutorial" in buffer.getvalue().lower()


def test_banner_renders_non_empty() -> None:
    console, buffer = _capture()
    render_banner(console, version="9.9.9")
    out = buffer.getvalue()
    assert len(out.strip()) > 0
