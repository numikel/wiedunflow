# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Entry point for ``python -m codeguide``.

Mirrors the ``codeguide`` console script defined in ``pyproject.toml``
(``[project.scripts]``) so eval tests and release workflows that prefer
``sys.executable -m codeguide`` over PATH lookups work identically.
"""

from __future__ import annotations

from codeguide.cli.main import cli

if __name__ == "__main__":
    cli()
