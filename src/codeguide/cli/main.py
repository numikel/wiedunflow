# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""CodeGuide CLI entrypoint (scaffold — Sprint 0)."""

from __future__ import annotations

import click

from codeguide import __version__


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="codeguide")
def main() -> None:
    """CodeGuide — generate a tutorial from a Git repository.

    Sprint 0 scaffold: only --version / --help are functional.
    Pipeline wiring lands in Sprint 1.
    """
    click.echo(f"codeguide {__version__} (scaffold — pipeline available from Sprint 1)")


if __name__ == "__main__":  # pragma: no cover
    main()
