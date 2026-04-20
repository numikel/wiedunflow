# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from calculator import add, subtract


def cli() -> None:
    """Entry point: demonstrate calculator functions."""
    print(add(2, 3))
    print(subtract(10, 4))


if __name__ == "__main__":
    cli()
