# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""CLI command handlers that delegate to the service layer."""

from tests.fixtures.medium_repo.cli.output import print_error, print_info
from tests.fixtures.medium_repo.exceptions import DomainError
from tests.fixtures.medium_repo.pkg.core import bootstrap
from tests.fixtures.medium_repo.pkg.services import OrderService, UserService
from tests.fixtures.medium_repo.pkg.transformers import order_display, user_display
from tests.fixtures.medium_repo.utils.numbers import dollars_to_cents


def cmd_register_user(user_id: int, name: str, email: str) -> str:
    """Handle the ``register-user`` command."""
    services = bootstrap()
    users = services["users"]
    assert isinstance(users, UserService)
    try:
        user = users.register(user_id, name, email)
    except DomainError as exc:
        return print_error(str(exc))
    return print_info(user_display(user))


def cmd_place_order(order_id: int, user_id: int, total_dollars: float) -> str:
    """Handle the ``place-order`` command."""
    services = bootstrap()
    orders = services["orders"]
    users = services["users"]
    assert isinstance(orders, OrderService)
    assert isinstance(users, UserService)
    try:
        users.register(user_id, f"user-{user_id}", f"u{user_id}@example.com")
        order = orders.place(order_id, user_id, dollars_to_cents(total_dollars))
    except DomainError as exc:
        return print_error(str(exc))
    return print_info(order_display(order))
