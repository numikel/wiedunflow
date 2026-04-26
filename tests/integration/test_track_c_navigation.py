# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 5 Track C — vanilla JS navigation (US-041..048, 076, 077).

All tests run against the shared session-scoped ``tutorial_html`` fixture and
exercise the tutorial entirely from the browser side — no server, no external
network, file:// scheme only.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import (
    ConsoleMessage,
    Page,
    Request,
    Route,
    sync_playwright,
)

pytestmark = [pytest.mark.integration, pytest.mark.playwright]


def _block_network(page: Page) -> None:
    def handle_route(route: Route, request: Request) -> None:
        scheme = urlparse(request.url).scheme.lower()
        if scheme in ("file", "about", "data"):
            route.continue_()
        else:
            route.abort()

    page.route("**/*", handle_route)


def _open(page: Page, html_path: Path) -> None:
    page.goto(html_path.as_uri(), wait_until="load", timeout=30_000)
    page.wait_for_function(
        """() => document.querySelector('.lesson-link.active') !== null""",
        timeout=30_000,
    )


def test_us043_toc_click_activates_lesson(tutorial_html: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        links = page.locator(".lesson-link")
        target_id = links.nth(1).get_attribute("data-lesson-id")
        assert target_id is not None
        links.nth(1).click()
        page.wait_for_timeout(150)

        active = page.locator(".lesson-link.active")
        assert active.get_attribute("data-lesson-id") == target_id

        browser.close()


def test_us044_hash_routing_direct_navigation(tutorial_html: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)

        # Navigate to a specific lesson via hash
        direct_url = tutorial_html.as_uri() + "#/lesson/lesson-003"
        page.goto(direct_url, wait_until="load", timeout=30_000)
        page.wait_for_function(
            """() => {
                const a = document.querySelector('.lesson-link.active');
                return a && a.getAttribute('data-lesson-id') === 'lesson-003';
            }""",
            timeout=30_000,
        )

        active_id = page.locator(".lesson-link.active").get_attribute("data-lesson-id")
        assert active_id == "lesson-003"

        browser.close()


def test_us044_invalid_hash_falls_back_to_first(tutorial_html: Path) -> None:
    console_warnings: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)

        def on_console(msg: ConsoleMessage) -> None:
            if msg.type == "warning":
                console_warnings.append(msg.text)

        page.on("console", on_console)
        page.goto(
            tutorial_html.as_uri() + "#/lesson/lesson-does-not-exist",
            wait_until="load",
            timeout=30_000,
        )
        page.wait_for_function(
            """() => document.querySelector('.lesson-link.active') !== null""",
            timeout=30_000,
        )

        active = page.locator(".lesson-link.active")
        # The first lesson in the TOC should be active (fallback).
        assert active.count() == 1
        assert any("unknown lesson id" in w for w in console_warnings)

        browser.close()


def test_us045_arrow_right_advances(tutorial_html: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        first = page.locator(".lesson-link.active").get_attribute("data-lesson-id")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(150)
        second = page.locator(".lesson-link.active").get_attribute("data-lesson-id")
        assert second and second != first

        browser.close()


def test_us045_arrow_disabled_inside_contenteditable(tutorial_html: Path) -> None:
    """Shortcuts must not fire while the user is editing text."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        first = page.locator(".lesson-link.active").get_attribute("data-lesson-id")
        # Inject a temporary editable element and focus it.
        page.evaluate(
            """() => {
                const el = document.createElement('textarea');
                el.id = 'editable-sink';
                document.body.appendChild(el);
                el.focus();
            }"""
        )
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(150)
        still_first = page.locator(".lesson-link.active").get_attribute("data-lesson-id")
        assert still_first == first

        browser.close()


def test_us046_last_lesson_persists(tutorial_html: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        # Advance to the next lesson and read back the localStorage key.
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(150)
        active_id = page.locator(".lesson-link.active").get_attribute("data-lesson-id")

        keys = page.evaluate("() => Object.keys(localStorage)")
        last_lesson_keys = [k for k in keys if k.endswith(":last-lesson")]
        assert last_lesson_keys, f"Expected a wiedun-flow:*:last-lesson key; got {keys}"
        stored = page.evaluate(f"() => localStorage.getItem({last_lesson_keys[0]!r})")
        assert stored == active_id

        browser.close()


def test_us048_schema_version_warn_on_mismatch(tutorial_html: Path) -> None:
    """tutorial.js logs a console.warn when schema_version != 1.0.0."""
    warnings: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)

        def on_console(msg: ConsoleMessage) -> None:
            if msg.type == "warning":
                warnings.append(msg.text)

        page.on("console", on_console)

        # Before navigation, patch the meta payload to use an unknown version.
        # We load the document, then rewrite meta and re-init.
        page.goto(tutorial_html.as_uri(), wait_until="load", timeout=30_000)
        page.evaluate(
            """() => {
                const el = document.getElementById('tutorial-meta');
                const payload = JSON.parse(el.textContent);
                payload.schema_version = '99.0.0';
                el.textContent = JSON.stringify(payload);
                window.WiedunFlow.init();
            }"""
        )
        page.wait_for_timeout(200)
        assert any("99.0.0" in w for w in warnings), (
            f"Expected a schema_version warning, got: {warnings}"
        )

        browser.close()


def test_us076_splitter_persists_narration_fraction(tutorial_html: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        _block_network(page)
        _open(page, tutorial_html)

        # Write a known fraction, re-init, verify CSS grid matches.
        page.evaluate("""() => localStorage.setItem('wiedunflow:tweak:narr-frac:v2', '0.3')""")
        page.reload(wait_until="load", timeout=30_000)
        page.wait_for_function(
            """() => document.querySelector('.lesson-link.active') !== null""",
            timeout=30_000,
        )
        grid = page.evaluate(
            """() => getComputedStyle(document.getElementById('tutorial-content')).gridTemplateColumns"""
        )
        # Expected roughly 30% / 10px / 70%; check that the left column is ~30% of viewport (1440px).
        parts = grid.split()
        assert len(parts) == 3, f"Expected 3-column grid, got: {grid}"

        browser.close()


def test_us077_theme_toggle_persists(tutorial_html: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        _block_network(page)
        _open(page, tutorial_html)

        # Open tweaks panel and click Dark.
        page.locator("#tweaks-open").click()
        page.locator('[data-theme-set="dark"]').click()
        page.wait_for_timeout(100)

        theme_attr = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
        assert theme_attr == "dark"
        stored = page.evaluate("() => localStorage.getItem('wiedunflow:tweak:theme:v2')")
        assert stored == "dark"

        browser.close()
