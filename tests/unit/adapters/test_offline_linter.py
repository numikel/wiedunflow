# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import pytest

from codeguide.use_cases.offline_linter import OfflineLinterError, validate_offline_invariant


@pytest.mark.parametrize(
    "snippet,expected_label",
    [
        ('<script>fetch("https://api.example.com/data")</script>', "fetch() call"),
        ("<script>var img = new Image()</script>", "new Image() constructor"),
        ('<link rel="prefetch" href="/next.js">', "prefetch link"),
        ('<link rel="preconnect" href="https://fonts.googleapis.com">', "preconnect link"),
        ('<a href="https://example.com">link</a>', "external http/https URL"),
    ],
)
def test_detects_violation(snippet: str, expected_label: str) -> None:
    html = f"<html><body>{snippet}</body></html>"
    with pytest.raises(OfflineLinterError) as exc_info:
        validate_offline_invariant(html)
    violations = exc_info.value.violations
    assert any(expected_label.lower() in v.lower() for v in violations), (
        f"Expected '{expected_label}' in violations {violations}"
    )


def test_clean_html_passes() -> None:
    html = "<html><body><p>Hello</p><script>var x = 1;</script></body></html>"
    validate_offline_invariant(html)  # should not raise


def test_localhost_url_allowed() -> None:
    html = '<html><body><a href="http://localhost:8080">local</a></body></html>'
    validate_offline_invariant(html)  # localhost is whitelisted
