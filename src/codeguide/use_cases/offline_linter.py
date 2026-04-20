# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import re


class OfflineLinterError(Exception):
    """Raised when the rendered HTML contains disallowed external references."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__(
            f"Offline invariant violated ({len(violations)} issue(s)): " + "; ".join(violations)
        )


_DISALLOWED_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("fetch() call", re.compile(r"fetch\s*\(")),
    ("new Image() constructor", re.compile(r"new\s+Image\s*\(")),
    ("prefetch link", re.compile(r'<link[^>]+rel=["\']prefetch["\']')),
    ("preconnect link", re.compile(r'<link[^>]+rel=["\']preconnect["\']')),
    ("external http/https URL", re.compile(r"https?://(?!localhost)(?!127\.0\.0\.1)")),
]


def validate_offline_invariant(html: str) -> None:
    """Raise OfflineLinterError if html contains disallowed external references.

    Called after rendering but before writing tutorial.html to disk.
    The ``file://`` constraint forbids any runtime network calls or external
    resource links that would silently fail when opened without a server.

    Args:
        html: Rendered HTML string to validate.

    Raises:
        OfflineLinterError: When one or more disallowed patterns are found,
            with a ``violations`` attribute listing every infraction.
    """
    violations: list[str] = []
    for label, pattern in _DISALLOWED_PATTERNS:
        matches = pattern.findall(html)
        if matches:
            violations.append(f"{label} (found {len(matches)} occurrence(s))")
    if violations:
        raise OfflineLinterError(violations)
