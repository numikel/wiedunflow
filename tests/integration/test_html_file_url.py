# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import ConsoleMessage, Request, Route, sync_playwright

pytestmark = [pytest.mark.integration, pytest.mark.playwright]


def test_tutorial_opens_in_browser_no_console_errors(tutorial_html: Path) -> None:
    """US-040: tutorial.html opens via file:// with no external deps and no console.error."""
    console_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Block all external network; allow only file:// and about: protocols
        def handle_route(route: Route, request: Request) -> None:
            url: str = request.url
            if url.startswith("file://") or url.startswith("about:"):
                route.continue_()
            else:
                route.abort()

        page.route("**/*", handle_route)

        def on_console(msg: ConsoleMessage) -> None:
            if msg.type == "error":
                console_errors.append(msg.text)

        page.on("console", on_console)

        file_url = tutorial_html.as_uri()
        page.goto(file_url, wait_until="domcontentloaded", timeout=10_000)

        # Assert first lesson is visible
        page.wait_for_selector("#lesson-title", timeout=5_000)
        title = page.locator("#lesson-title").text_content()
        assert title is not None and len(title) > 0, "Lesson title should not be empty"

        # Click Next button and verify second lesson loads
        next_btn = page.locator("#btn-next")
        assert next_btn.is_enabled(), "Next button should be enabled (more than 1 lesson)"
        next_btn.click()

        # Wait for lesson content to update (JS is synchronous so near-immediate)
        page.wait_for_timeout(200)
        second_title = page.locator("#lesson-title").text_content()
        assert second_title != title, (
            f"Expected second lesson title to differ from first, got: {second_title!r}"
        )

        # Assert no console errors
        assert console_errors == [], f"Browser console errors: {console_errors}"

        browser.close()


def test_tutorial_prev_button_disabled_on_first_lesson(tutorial_html: Path) -> None:
    """Prev button should be disabled on the first lesson."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(tutorial_html.as_uri(), wait_until="domcontentloaded", timeout=10_000)
        page.wait_for_selector("#btn-prev", timeout=5_000)

        prev_btn = page.locator("#btn-prev")
        assert not prev_btn.is_enabled(), "Prev button should be disabled on first lesson"

        browser.close()
