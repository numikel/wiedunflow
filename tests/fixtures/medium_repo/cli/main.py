"""Primary CLI dispatch — picks a command and forwards arguments."""

from tests.fixtures.medium_repo.cli.commands import cmd_place_order, cmd_register_user
from tests.fixtures.medium_repo.cli.output import print_error


def dispatch(command: str, argv: list[str]) -> str:
    """Route *command* to the matching handler, returning its output line."""
    if command == "register-user":
        user_id = int(argv[0])
        return cmd_register_user(user_id, argv[1], argv[2])
    if command == "place-order":
        return cmd_place_order(int(argv[0]), int(argv[1]), float(argv[2]))
    return print_error(f"unknown command: {command}")
