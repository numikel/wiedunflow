# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""CodeGuide CLI entrypoint."""

from __future__ import annotations

import logging
from pathlib import Path

import click

from codeguide import __version__
from codeguide.adapters import (
    FakeClock,
    FakeLLMProvider,
    InMemoryCache,
    StubBm25Store,
    StubJediResolver,
    StubRanker,
    StubTreeSitterParser,
)
from codeguide.use_cases.generate_tutorial import Providers, generate_tutorial

logger = logging.getLogger(__name__)


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="codeguide")
@click.argument(
    "repo_path",
    type=click.Path(
        exists=True,
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
        path_type=Path,
    ),
)
def main(repo_path: Path) -> None:
    """Generate an interactive HTML tutorial from a local Git repository."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    providers = Providers(
        llm=FakeLLMProvider(),
        parser=StubTreeSitterParser(),
        resolver=StubJediResolver(),
        ranker=StubRanker(),
        vector_store=StubBm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )

    output = generate_tutorial(repo_path, providers)
    click.echo(f"Tutorial written to: {output}")
    click.echo(f"Open with: file://{output.as_posix()}")


if __name__ == "__main__":  # pragma: no cover
    main()
