"""Application services coordinating validators, models, and repositories."""

from tests.fixtures.medium_repo.pkg.models import Order, User, build_order, build_user
from tests.fixtures.medium_repo.pkg.repositories import OrderRepository, UserRepository
from tests.fixtures.medium_repo.pkg.validators import (
    validate_amount,
    validate_email,
    validate_name,
)


class UserService:
    """Create and fetch users through the repository."""

    def __init__(self, repo: UserRepository) -> None:
        self._repo = repo

    def register(self, user_id: int, name: str, email: str) -> User:
        """Validate inputs and persist a new user."""
        validate_name(name)
        validate_email(email)
        user = build_user(user_id, name, email)
        self._repo.add(user)
        return user

    def lookup(self, user_id: int) -> User:
        """Return the user or re-raise :class:`NotFoundError`."""
        return self._repo.get(user_id)


class OrderService:
    """Create and fetch orders through the repository."""

    def __init__(self, orders: OrderRepository, users: UserRepository) -> None:
        self._orders = orders
        self._users = users

    def place(self, order_id: int, user_id: int, total_cents: int) -> Order:
        """Validate inputs, confirm user exists, and persist the order."""
        validate_amount(total_cents)
        self._users.get(user_id)
        order = build_order(order_id, user_id, total_cents)
        self._orders.add(order)
        return order
