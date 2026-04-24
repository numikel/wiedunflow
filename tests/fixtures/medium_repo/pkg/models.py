# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Data models shared across the service layer."""

from dataclasses import dataclass


@dataclass
class User:
    """A user of the system."""

    user_id: int
    name: str
    email: str


@dataclass
class Order:
    """An order placed by a user."""

    order_id: int
    user_id: int
    total_cents: int


def build_user(user_id: int, name: str, email: str) -> User:
    """Factory: construct a :class:`User` from primitive fields."""
    return User(user_id=user_id, name=name, email=email)


def build_order(order_id: int, user_id: int, total_cents: int) -> Order:
    """Factory: construct an :class:`Order` from primitive fields."""
    return Order(order_id=order_id, user_id=user_id, total_cents=total_cents)
