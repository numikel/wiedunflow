"""Top-level orchestration of the package public API."""

from tests.fixtures.medium_repo.pkg.repositories import OrderRepository, UserRepository
from tests.fixtures.medium_repo.pkg.services import OrderService, UserService


def make_services() -> tuple[UserService, OrderService]:
    """Wire up repositories + services with default in-memory stores."""
    users_repo = UserRepository()
    orders_repo = OrderRepository()
    users = UserService(users_repo)
    orders = OrderService(orders_repo, users_repo)
    return users, orders


def bootstrap() -> dict[str, object]:
    """Return a ready-to-use service container for the CLI."""
    users, orders = make_services()
    return {"users": users, "orders": orders}
