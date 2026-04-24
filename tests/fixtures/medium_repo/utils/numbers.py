# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Number helpers."""


def cents_to_dollars(cents: int) -> float:
    """Convert integer cents to a float-dollar amount."""
    return cents / 100


def dollars_to_cents(dollars: float) -> int:
    """Convert a float-dollar amount to integer cents (rounded)."""
    return round(dollars * 100)


def format_currency(cents: int) -> str:
    """Format cents as ``$<dollars>.<cents>``."""
    return f"${cents_to_dollars(cents):.2f}"
