# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Pure-function transformers over the domain models."""

from tests.fixtures.medium_repo.pkg.models import Order, User


def user_display(user: User) -> str:
    """Render a user as ``<name> <<email>>``."""
    return f"{user.name} <{user.email}>"


def order_display(order: Order) -> str:
    """Render an order as ``#<order_id> for user <user_id>: $<dollars>``."""
    dollars = order.total_cents / 100
    return f"#{order.order_id} for user {order.user_id}: ${dollars:.2f}"
