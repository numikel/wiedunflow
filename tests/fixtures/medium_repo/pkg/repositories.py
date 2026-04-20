"""In-memory repositories — stand-ins for a real DB layer."""

from tests.fixtures.medium_repo.exceptions import NotFoundError
from tests.fixtures.medium_repo.pkg.models import Order, User


class UserRepository:
    """Store and retrieve :class:`User` objects by id."""

    def __init__(self) -> None:
        self._users: dict[int, User] = {}

    def add(self, user: User) -> None:
        """Insert a user into the repository."""
        self._users[user.user_id] = user

    def get(self, user_id: int) -> User:
        """Return the user with the given id or raise :class:`NotFoundError`."""
        if user_id not in self._users:
            raise NotFoundError(f"user {user_id} not found")
        return self._users[user_id]


class OrderRepository:
    """Store and retrieve :class:`Order` objects by id."""

    def __init__(self) -> None:
        self._orders: dict[int, Order] = {}

    def add(self, order: Order) -> None:
        """Insert an order into the repository."""
        self._orders[order.order_id] = order

    def get(self, order_id: int) -> Order:
        """Return the order with the given id or raise :class:`NotFoundError`."""
        if order_id not in self._orders:
            raise NotFoundError(f"order {order_id} not found")
        return self._orders[order_id]
