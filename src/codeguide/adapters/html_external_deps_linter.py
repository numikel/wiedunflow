# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Template-time linter — rejects any rendered HTML that references external resources.

Used to enforce US-040 (file:// zero external deps). Called from both Track A unit
tests and the T-005.EVAL smoke to catch regressions where a partial or the JS
accidentally introduces ``fetch(``, ``<link href="http...`` or a CDN URL.
"""

from __future__ import annotations

import re

# Forbidden patterns. Data URIs are allowed because they are inline.
_FORBIDDEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"""<script\s+[^>]*\bsrc\s*=\s*["']https?://""", re.IGNORECASE),
        "external <script src=>",
    ),
    (
        re.compile(r"""<link\s+[^>]*\bhref\s*=\s*["']https?://""", re.IGNORECASE),
        "external <link href=>",
    ),
    (
        re.compile(r"""<img\s+[^>]*\bsrc\s*=\s*["'](?!data:)https?://""", re.IGNORECASE),
        "external <img src=>",
    ),
    (re.compile(r"""@import\s+url\(["']?https?://""", re.IGNORECASE), "@import url(http...)"),
    (re.compile(r"""\bfetch\s*\(""", re.IGNORECASE), "fetch() call"),
    (re.compile(r"""\bXMLHttpRequest\s*\("""), "XMLHttpRequest"),
    (
        re.compile(
            r"""<link\s+[^>]*\brel\s*=\s*["'](prefetch|preconnect|dns-prefetch)""", re.IGNORECASE
        ),
        "prefetch/preconnect link",
    ),
    (re.compile(r"""\bimport\s*\(\s*["']https?://"""), "dynamic import('http...')"),
)


class ExternalDependencyError(RuntimeError):
    """Raised when an external dependency is detected in rendered HTML."""


def assert_no_external_refs(html: str) -> None:
    """Raise ``ExternalDependencyError`` if the HTML contains an external reference.

    Args:
        html: The fully rendered HTML document string.

    Raises:
        ExternalDependencyError: If any forbidden pattern matches the HTML.
    """
    violations: list[str] = []
    for pattern, description in _FORBIDDEN_PATTERNS:
        if pattern.search(html):
            violations.append(description)
    if violations:
        raise ExternalDependencyError(
            "rendered HTML contains external references: " + ", ".join(violations)
        )
