# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Text helpers."""


def slugify(value: str) -> str:
    """Lowercase and hyphen-separate a string."""
    return value.strip().lower().replace(" ", "-")


def truncate(value: str, max_len: int) -> str:
    """Truncate *value* to *max_len* characters, appending an ellipsis if cut."""
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"


def titleize(value: str) -> str:
    """Slug + title-case convenience wrapper."""
    slug = slugify(value)
    return slug.replace("-", " ").title()
