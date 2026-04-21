# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""US-074: 8 CLI color roles exposed as rich.style.Style via make_theme()."""
from __future__ import annotations

from rich.style import Style

from codeguide.cli.output import make_theme

_EXPECTED_ROLES = frozenset(
    {"default", "dim", "good", "warn", "err", "accent", "link", "prompt"}
)


def test_theme_defines_all_eight_roles() -> None:
    theme = make_theme()
    assert set(theme.styles).issuperset(_EXPECTED_ROLES), (
        f"Missing roles: {_EXPECTED_ROLES - set(theme.styles)}"
    )


def test_theme_roles_are_style_instances() -> None:
    theme = make_theme()
    for role in _EXPECTED_ROLES:
        assert isinstance(theme.styles[role], Style), f"{role} is not a rich.Style"


def test_link_role_is_underlined_and_bold() -> None:
    """US-074: only links use bold (plus underline)."""
    theme = make_theme()
    link = theme.styles["link"]
    assert link.underline is True
    assert link.bold is True
