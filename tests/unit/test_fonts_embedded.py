# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 0 T-000.14 — fonts and design tokens shipping test."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest

FONTS_DIR = files("wiedunflow.renderer").joinpath("fonts")
TOKENS_CSS = files("wiedunflow.renderer").joinpath("templates/tokens.css")

REQUIRED_FONTS = [
    "Inter-Regular.woff2",
    "Inter-Medium.woff2",
    "Inter-SemiBold.woff2",
    "Inter-Bold.woff2",
    "JetBrainsMono-Regular.woff2",
    "JetBrainsMono-Medium.woff2",
    "JetBrainsMono-SemiBold.woff2",
]

REQUIRED_LIGHT_TOKENS = [
    "--bg",
    "--panel",
    "--surface",
    "--topbar",
    "--ink",
    "--ink-2",
    "--ink-dim",
    "--accent",
    "--warn",
    "--border",
    "--border-2",
    "--code-bg",
    "--hl",
    "--hl-line",
]


@pytest.mark.parametrize("font_name", REQUIRED_FONTS)
def test_font_woff2_magic_bytes(font_name: str) -> None:
    """Every required font file exists and has a valid WOFF2 magic header."""
    font_path = Path(str(FONTS_DIR.joinpath(font_name)))
    assert font_path.is_file(), f"Missing font: {font_name}"
    header = font_path.read_bytes()[:4]
    assert header == b"wOF2", (
        f"{font_name} is not a valid WOFF2 file — header={header!r} "
        "(expected b'wOF2'; WOFF1 b'wOFF' not accepted)."
    )


def test_ofl_license_files_present() -> None:
    assert Path(str(FONTS_DIR.joinpath("OFL-Inter.txt"))).is_file()
    assert Path(str(FONTS_DIR.joinpath("OFL-JetBrainsMono.txt"))).is_file()


def test_tokens_css_has_light_palette() -> None:
    css = Path(str(TOKENS_CSS)).read_text(encoding="utf-8")
    for token in REQUIRED_LIGHT_TOKENS:
        assert f"{token}:" in css, f"tokens.css missing {token} declaration"


def test_tokens_css_has_dark_palette() -> None:
    css = Path(str(TOKENS_CSS)).read_text(encoding="utf-8")
    assert '[data-theme="dark"]' in css, "tokens.css missing dark theme selector"
    total_oklch = css.count("oklch(")
    assert total_oklch >= 28, f"Expected ≥28 oklch declarations, found {total_oklch}"


def test_notice_references_fonts() -> None:
    notice = Path("NOTICE").read_text(encoding="utf-8")
    assert "Inter" in notice and "SIL OFL" in notice
    assert "JetBrains Mono" in notice


def test_tokens_css_inlined_constant_pre_encodes_fonts() -> None:
    """Module-level _TOKENS_CSS_INLINED must hold the fully base64-encoded CSS.

    Renderer is hot-path on Stage 7; the fonts (~164 KB) should be base64-encoded
    exactly once per process at import time, not per render call.
    """
    from wiedunflow.adapters.jinja_renderer import _TOKENS_CSS_INLINED

    assert isinstance(_TOKENS_CSS_INLINED, str)
    assert 'url("data:font/woff2;base64,' in _TOKENS_CSS_INLINED
    # All 7 WOFF2 inline-references must be substituted (none of the original
    # ``url("../fonts/X.woff2")`` references should leak through).
    assert "../fonts/" not in _TOKENS_CSS_INLINED


def test_jinja_renderer_tokens_css_returns_pre_inlined_constant() -> None:
    """JinjaRenderer._tokens_css() must reuse the module-level constant.

    Guarantees that calling _tokens_css() twice returns the identical string
    object (same id) — confirming the cache short-circuit and that production
    flows never re-encode fonts.
    """
    from wiedunflow.adapters.jinja_renderer import _TOKENS_CSS_INLINED, JinjaRenderer

    first = JinjaRenderer._tokens_css()
    second = JinjaRenderer._tokens_css()
    assert first is second
    assert first is _TOKENS_CSS_INLINED


def test_jinja_renderer_tokens_css_test_injection_override() -> None:
    """Setting JinjaRenderer._tokens_css_cache shadows the module-level constant.

    Documented escape hatch for tests that need to inject custom CSS without
    rebuilding the renderer module.
    """
    from wiedunflow.adapters.jinja_renderer import JinjaRenderer

    sentinel = "/* test-injected tokens */"
    try:
        JinjaRenderer._tokens_css_cache = sentinel
        assert JinjaRenderer._tokens_css() == sentinel
    finally:
        JinjaRenderer._tokens_css_cache = None
