# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""CodeGuide CLI entrypoint."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click

from codeguide import __version__
from codeguide.adapters import (
    Bm25Store,
    FakeClock,
    FakeLLMProvider,
    InMemoryCache,
    JediResolver,
    NetworkxRanker,
    TreeSitterParser,
)
from codeguide.adapters.anthropic_provider import AnthropicProvider
from codeguide.cli.config import ConfigError, load_config, resolve_api_key
from codeguide.cli.consent import (
    ConsentDeniedError,
    ConsentRequiredError,
    ensure_consent_granted,
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
@click.option(
    "--exclude",
    "excludes",
    multiple=True,
    metavar="PATTERN",
    help="Additional .gitignore-style pattern to exclude (may repeat).",
)
@click.option(
    "--include",
    "includes",
    multiple=True,
    metavar="PATTERN",
    help="Pattern to re-include despite .gitignore (may repeat).",
)
@click.option(
    "--root",
    "root",
    default=None,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Override detected repo root (monorepo subtree).",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a YAML config file (default: ./tutorial.config.yaml).",
)
@click.option(
    "--no-consent-prompt",
    "no_consent_prompt",
    is_flag=True,
    default=False,
    help="Skip the privacy consent banner (non-interactive environments).",
)
@click.option(
    "--yes",
    "yes",
    is_flag=True,
    default=False,
    help="Auto-confirm all prompts including the consent banner.",
)
@click.option(
    "--provider",
    "provider",
    type=click.Choice(["anthropic", "openai", "openai_compatible"]),
    default=None,
    help="LLM provider to use (overrides config file).",
)
@click.option(
    "--model-plan",
    "model_plan",
    default=None,
    metavar="MODEL",
    help="Model name for the planning stage (overrides config file).",
)
@click.option(
    "--model-narrate",
    "model_narrate",
    default=None,
    metavar="MODEL",
    help="Model name for the narration stage (overrides config file).",
)
def main(
    repo_path: Path,
    excludes: tuple[str, ...],
    includes: tuple[str, ...],
    root: Path | None,
    config_path: Path | None,
    no_consent_prompt: bool,
    yes: bool,
    provider: str | None,
    model_plan: str | None,
    model_narrate: str | None,
) -> None:
    """Generate an interactive HTML tutorial from a local Git repository."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        config = load_config(
            cli_overrides={
                "llm_provider": provider,
                "llm_model_plan": model_plan,
                "llm_model_narrate": model_narrate,
            },
            cli_config_path=config_path,
        )

        if config.llm_provider == "anthropic":
            bypass = no_consent_prompt or yes
            ensure_consent_granted(
                "anthropic",
                bypass=bypass,
                tty=sys.stdin.isatty(),
            )
            llm: FakeLLMProvider | AnthropicProvider = AnthropicProvider(
                api_key=resolve_api_key(config),
                model_plan=config.llm_model_plan,
                model_narrate=config.llm_model_narrate,
                max_retries=config.llm_max_retries,
                max_wait_s=config.llm_max_wait_s,
            )
        else:
            # openai / openai_compatible arrive in Sprint 4.
            llm = FakeLLMProvider()

    except (ConfigError, ConsentRequiredError, ConsentDeniedError) as exc:
        click.echo(f"error: {exc}", err=True)
        sys.exit(1)

    providers = Providers(
        llm=llm,
        parser=TreeSitterParser(),
        resolver=JediResolver(),
        ranker=NetworkxRanker(),
        vector_store=Bm25Store(),
        cache=InMemoryCache(),
        clock=FakeClock(),
    )

    output = generate_tutorial(
        repo_path,
        providers,
        excludes=excludes,
        includes=includes,
        root_override=root,
    )
    click.echo(f"Tutorial written to: {output}")
    click.echo(f"Open with: file://{output.as_posix()}")


if __name__ == "__main__":  # pragma: no cover
    main()
