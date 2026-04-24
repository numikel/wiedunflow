# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import ConsoleMessage, Request, Route, sync_playwright

pytestmark = [pytest.mark.integration, pytest.mark.playwright]


def _block_network(page: object) -> None:
    """Route handler: allow only file:// and about: schemes — aborts any external request."""

    def handle_route(route: Route, request: Request) -> None:
        scheme = urlparse(request.url).scheme.lower()
        if scheme in ("file", "about", "data"):
            route.continue_()
        else:
            route.abort()

    page.route("**/*", handle_route)  # type: ignore[attr-defined]


def test_tutorial_opens_in_browser_no_console_errors(tutorial_html: Path) -> None:
    """US-040: tutorial.html opens via file:// with no external deps and no console.error."""
    console_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)

        def on_console(msg: ConsoleMessage) -> None:
            if msg.type == "error":
                console_errors.append(msg.text)

        page.on("console", on_console)

        page.goto(tutorial_html.as_uri(), wait_until="load", timeout=30_000)

        # Wait until the structured narration body has been populated by tutorial.js.
        page.wait_for_function(
            """() => {
                const el = document.getElementById('tutorial-narration-body');
                return Boolean(el && el.children.length > 0);
            }""",
            timeout=30_000,
        )

        # First lesson should have rendered into the active link.
        active_link = page.locator(".lesson-link.active")
        first_title = active_link.text_content()
        assert first_title, "Expected an active lesson link with a title"

        # US-045: arrow-right navigation moves to the next lesson.
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(200)
        second_title = page.locator(".lesson-link.active").text_content()
        assert second_title != first_title, (
            f"Expected arrow-right to change active lesson, got: {second_title!r}"
        )

        # US-044: hash updates to match the active lesson id.
        hash_after = page.evaluate("() => location.hash")
        assert hash_after.startswith("#/lesson/"), f"Expected hash routing, got: {hash_after!r}"

        assert console_errors == [], f"Browser console errors: {console_errors}"

        browser.close()


def test_tutorial_first_lesson_left_arrow_is_boundary_noop(tutorial_html: Path) -> None:
    """US-045: on the first lesson, ArrowLeft must be a no-op (no error, stays on lesson)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)

        page.goto(tutorial_html.as_uri(), wait_until="load", timeout=30_000)
        page.wait_for_function(
            """() => document.querySelector('.lesson-link.active') !== null""",
            timeout=30_000,
        )

        first_title = page.locator(".lesson-link.active").text_content()
        page.keyboard.press("ArrowLeft")
        page.wait_for_timeout(150)
        after_title = page.locator(".lesson-link.active").text_content()
        assert after_title == first_title, "Boundary ArrowLeft should be a no-op on first lesson"

        browser.close()
