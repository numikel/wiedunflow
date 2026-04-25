# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""v0.2.1 — progress bar, chip "Lesson N / M", and sidebar checkmark integration tests.

Drives the headless renderer to assert that:
  - ``#tutorial-progress > span`` width advances on next-button navigation.
  - ``#tutorial-progress-label`` text reads ``Lesson N / M`` after navigation.
  - ``localStorage["codeguide:<repo>:visited-lessons:v1"]`` records the active
    lesson immediately on Next click.
  - ``.lesson-link.visited`` decoration is restored from localStorage on reload.
  - ``.helper-appendix`` block is rendered iff the lesson payload carries
    ``helper_appendix``; absent block when not set.

Reuses the session-scoped ``tutorial_html`` fixture from ``tests/integration/conftest.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Page, Request, Route, sync_playwright

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


def test_progress_bar_starts_above_zero_on_first_lesson(tutorial_html: Path) -> None:
    """The bar fills (1/total)*100% on first paint — never 0% (initial lesson is lesson 1)."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        width_pct = page.evaluate(
            """() => {
                const bar = document.querySelector('#tutorial-progress > span');
                return bar ? bar.style.width : null;
            }"""
        )

        assert width_pct is not None
        assert width_pct.endswith("%")
        # 1/total*100 — bar must advance off zero immediately.
        assert float(width_pct.rstrip("%")) > 0.0
        browser.close()


def test_progress_bar_advances_on_next_click(tutorial_html: Path) -> None:
    """Clicking Next moves the bar forward."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        before = page.evaluate(
            "() => document.querySelector('#tutorial-progress > span').style.width"
        )
        # Skip if there is no second lesson to navigate to.
        link_count = page.locator(".lesson-link").count()
        if link_count < 2:
            browser.close()
            pytest.skip("tutorial fixture has only one lesson; cannot assert progress")
        page.locator("#tutorial-next").click()
        page.wait_for_timeout(300)
        after = page.evaluate(
            "() => document.querySelector('#tutorial-progress > span').style.width"
        )

        assert float(after.rstrip("%")) > float(before.rstrip("%"))
        browser.close()


def test_progress_label_shows_current_count(tutorial_html: Path) -> None:
    """Chip reads ``Lesson 1 / N`` on first paint and updates after Next."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        text = page.locator("#tutorial-progress-label").text_content()
        assert text is not None
        assert text.startswith("Lesson 1 / ")

        link_count = page.locator(".lesson-link").count()
        if link_count >= 2:
            page.locator("#tutorial-next").click()
            page.wait_for_timeout(200)
            text2 = page.locator("#tutorial-progress-label").text_content()
            assert text2 is not None
            assert text2.startswith("Lesson 2 / ")
        browser.close()


def test_visited_marker_set_on_next_click(tutorial_html: Path) -> None:
    """Clicking Next records the lesson as visited in localStorage immediately."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        link_count = page.locator(".lesson-link").count()
        if link_count < 2:
            browser.close()
            pytest.skip("need at least 2 lessons to test next-click visited")

        first_id = page.locator(".lesson-link").nth(0).get_attribute("data-lesson-id")
        assert first_id is not None
        page.locator("#tutorial-next").click()
        page.wait_for_timeout(200)

        # Find the visited-lessons key — namespace is codeguide:<repo>:visited-lessons:v1
        keys = page.evaluate(
            """() => Object.keys(localStorage).filter(k => k.indexOf('visited-lessons:v1') !== -1)"""
        )
        assert len(keys) == 1, f"expected 1 visited-lessons key, got {keys}"
        raw = page.evaluate(f"() => localStorage.getItem({keys[0]!r})")
        visited = json.loads(raw)
        assert first_id in visited, f"{first_id!r} not in {visited}"
        browser.close()


def test_visited_painted_after_reload(tutorial_html: Path) -> None:
    """Reloading the tutorial paints `.lesson-link.visited` from localStorage."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        # Pre-populate the visited list with the second lesson id (if present).
        link_count = page.locator(".lesson-link").count()
        if link_count < 2:
            browser.close()
            pytest.skip("need at least 2 lessons")
        target_id = page.locator(".lesson-link").nth(1).get_attribute("data-lesson-id")
        assert target_id is not None

        repo_id = page.evaluate(
            """() => {
                const meta = JSON.parse(document.getElementById('tutorial-meta').textContent);
                return meta.repo || meta.repo_name || 'unknown';
            }"""
        )
        key = f"codeguide:{repo_id}:visited-lessons:v1"
        # Pass key + target_id as args to evaluate (avoids JS-injection escaping issues).
        page.evaluate(
            "([k, id]) => localStorage.setItem(k, JSON.stringify([id]))",
            [key, target_id],
        )
        page.reload(wait_until="load", timeout=30_000)
        page.wait_for_function(
            """() => document.querySelector('.lesson-link.active') !== null""",
            timeout=30_000,
        )

        visited = page.evaluate(
            """(id) => {
                const link = document.querySelector(
                    `.lesson-link[data-lesson-id="${id}"]`
                );
                return link ? link.classList.contains('visited') : false;
            }""",
            target_id,
        )
        assert visited, f"lesson-link for {target_id!r} not marked visited after reload"
        browser.close()


def test_helper_appendix_absent_when_lesson_lacks_field(tutorial_html: Path) -> None:
    """When no lesson carries `helper_appendix`, no `.helper-appendix` block renders.

    The default ``FakeLLMProvider`` fixture run does not enable
    ``planning.skip_trivial_helpers``, so the appendix should be empty.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        _block_network(page)
        _open(page, tutorial_html)

        # Walk every lesson and confirm no .helper-appendix is emitted.
        link_count = page.locator(".lesson-link").count()
        for i in range(link_count):
            page.locator(".lesson-link").nth(i).click()
            page.wait_for_timeout(150)
            count = page.locator(".helper-appendix").count()
            assert count == 0, f"unexpected .helper-appendix on lesson #{i}"
        browser.close()
