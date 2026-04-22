# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 5 visual regression — 4 golden screenshots per ADR-0011 surface.

Per Sprint 5 plan decision #2:
- 1 % pixel tolerance (anti-aliasing across fonts is inherently fuzzy)
- Golden baselines captured on **Ubuntu only** (`tests/visual/baselines/linux/`)
  so antialiasing differences across OSes don't trip the diff.
- The matrix/Windows/macOS functional tests still run the Playwright suite in
  ``tests/integration/test_track_c_navigation.py`` — visual fidelity is an
  Ubuntu-only concern.

Baselines are stored as PNG under ``tests/visual/baselines/linux/``. The first
run on a given host calls ``pytest.skip`` after writing the baseline so
developers have a record to inspect. Set ``CODEGUIDE_VISUAL_UPDATE=1`` to
regenerate baselines intentionally.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
from PIL import Image, ImageChops
from playwright.sync_api import Page, Request, Route, sync_playwright

pytestmark = [pytest.mark.integration, pytest.mark.playwright]

_TOLERANCE = 0.01  # 1 % per plan decision #2
_BASELINE_DIR = Path(__file__).parent / "baselines" / "linux"
_VIEWPORTS: dict[str, dict[str, int]] = {
    "desktop_1440w_900h": {"width": 1440, "height": 900},
    "mobile_375w_812h": {"width": 375, "height": 812},
}
_THEMES: tuple[str, ...] = ("light", "dark")


def _is_linux_ci() -> bool:
    """Only run the comparison on Linux CI — other OSes skip with reason."""
    if os.environ.get("CODEGUIDE_VISUAL_UPDATE") == "1":
        return True
    return sys.platform.startswith("linux")


def _block_network(page: Page) -> None:
    def handle_route(route: Route, request: Request) -> None:
        scheme = urlparse(request.url).scheme.lower()
        if scheme in ("file", "about", "data"):
            route.continue_()
        else:
            route.abort()

    page.route("**/*", handle_route)


def _compare_pngs(actual_bytes: bytes, baseline_path: Path) -> float:
    """Return the ratio of differing pixels in [0, 1]."""
    baseline = Image.open(baseline_path).convert("RGBA")
    current = Image.open(io.BytesIO(actual_bytes)).convert("RGBA")
    if baseline.size != current.size:
        raise AssertionError(f"Baseline size {baseline.size} differs from current {current.size}")
    diff = ImageChops.difference(baseline, current)
    bbox = diff.getbbox()
    if bbox is None:
        return 0.0
    total_pixels = baseline.size[0] * baseline.size[1]
    diff_pixels = sum(1 for pix in diff.getdata() if any(channel != 0 for channel in pix))
    return diff_pixels / total_pixels


def _capture_and_compare(html_path: Path, viewport_name: str, theme: str) -> None:
    baseline_path = _BASELINE_DIR / f"{viewport_name}_{theme}.png"
    viewport = _VIEWPORTS[viewport_name]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=viewport)
        _block_network(page)

        page.goto(html_path.as_uri(), wait_until="load", timeout=30_000)
        page.wait_for_function(
            """() => document.querySelector('.lesson-link.active') !== null""",
            timeout=30_000,
        )
        # Apply theme via localStorage + reload so the reader boots with the
        # correct data-theme attribute before the first paint.
        page.evaluate(f"() => localStorage.setItem('codeguide:tweak:theme:v2', {theme!r})")
        page.reload(wait_until="load", timeout=30_000)
        page.wait_for_function(
            """() => document.querySelector('.lesson-link.active') !== null""",
            timeout=30_000,
        )
        actual = page.screenshot(full_page=False, type="png")
        browser.close()

    should_update = os.environ.get("CODEGUIDE_VISUAL_UPDATE") == "1"
    if not baseline_path.exists() or should_update:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_bytes(actual)
        pytest.skip(
            f"baseline {'updated' if should_update else 'captured'} at "
            f"{baseline_path.relative_to(Path(__file__).parent.parent.parent)}"
        )

    ratio = _compare_pngs(actual, baseline_path)
    assert ratio <= _TOLERANCE, (
        f"Visual diff {ratio:.2%} exceeds {_TOLERANCE:.0%} tolerance for {viewport_name} @ {theme}"
    )


@pytest.mark.skipif(
    not _is_linux_ci(),
    reason="Visual regression baselines are Linux-only (plan decision #2)",
)
@pytest.mark.parametrize("viewport_name", list(_VIEWPORTS.keys()))
@pytest.mark.parametrize("theme", _THEMES)
def test_visual_regression(visual_tutorial_html: Path, viewport_name: str, theme: str) -> None:
    """Golden-snapshot check: 4 combinations (2 viewports by 2 themes)."""
    _capture_and_compare(visual_tutorial_html, viewport_name, theme)
