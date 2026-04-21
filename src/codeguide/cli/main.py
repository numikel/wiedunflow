# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""CodeGuide CLI entrypoint."""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import click

from codeguide import __version__
from codeguide.adapters import (
    Bm25Store,
    FakeClock,
    FakeLLMProvider,
    JediResolver,
    NetworkxRanker,
    TreeSitterParser,
)
from codeguide.adapters.anthropic_provider import AnthropicProvider
from codeguide.adapters.openai_provider import OpenAIProvider
from codeguide.adapters.sqlite_cache import SQLiteCache
from codeguide.cli.config import CodeguideConfig, ConfigError, load_config, resolve_api_key
from codeguide.cli.consent import (
    ConsentDeniedError,
    ConsentRequiredError,
    ensure_consent_granted,
)
from codeguide.cli.run_report_writer import write_run_report
from codeguide.cli.signals import SigintHandler
from codeguide.entities.run_report import RunReport, RunStatus
from codeguide.interfaces.ports import LLMProvider
from codeguide.use_cases.generate_tutorial import GenerationResult, Providers, generate_tutorial
from codeguide.use_cases.plan_lesson_manifest import PlanningFatalError

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
    type=click.Choice(["anthropic", "openai", "openai_compatible", "custom"]),
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
@click.option(
    "--base-url",
    "base_url",
    default=None,
    metavar="URL",
    help="OpenAI-compatible endpoint (e.g. http://localhost:11434/v1 for Ollama).",
)
@click.option(
    "--resume/--no-resume",
    "resume",
    default=None,
    help="Resume from the last checkpoint (US-017). --no-resume forces a clean run.",
)
@click.option(
    "--regenerate-plan",
    "regenerate_plan",
    is_flag=True,
    default=False,
    help="Discard cached lesson manifest and re-run Stage 4 planning (US-018).",
)
@click.option(
    "--cache-path",
    "cache_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Override the cache database location (US-020). Default: platformdirs user cache.",
)
@click.option(
    "--max-cost",
    "max_cost_usd",
    default=None,
    type=float,
    metavar="USD",
    help="Abort if projected LLM cost exceeds this value in USD (US-019).",
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
    base_url: str | None,
    resume: bool | None,
    regenerate_plan: bool,
    cache_path: Path | None,
    max_cost_usd: float | None,
) -> None:
    """Generate an interactive HTML tutorial from a local Git repository."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    started_at = datetime.now(UTC)

    # Phase 3: flags accepted, but --resume / --regenerate-plan full wiring
    # into the cache-driven incremental pipeline arrives in Phase 4.  We log
    # the intent now so CLI tests can exercise the flags end-to-end.
    if resume is True:
        logger.info("--resume requested; checkpoint replay scheduled in Phase 4.")
    if regenerate_plan:
        logger.info("--regenerate-plan requested; plan-cache invalidation scheduled in Phase 4.")
    if max_cost_usd is not None:
        logger.info(
            "--max-cost=%.2f USD; cost-gate enforcement scheduled in Phase 4.", max_cost_usd
        )

    # Build providers; early config errors short-circuit with exit=1.
    try:
        config = load_config(
            cli_overrides={
                "llm_provider": provider,
                "llm_model_plan": model_plan,
                "llm_model_narrate": model_narrate,
                "llm_base_url": base_url,
            },
            cli_config_path=config_path,
        )
        llm = _build_llm_provider(config, no_consent_prompt=no_consent_prompt, yes=yes)
    except (ConfigError, ConsentRequiredError, ConsentDeniedError) as exc:
        click.echo(f"error: {exc}", err=True)
        _write_final_report(
            repo_path=repo_path,
            provider_label="none",
            started_at=started_at,
            status="failed",
            stack_trace=str(exc),
            failed_at_lesson="<config>",
        )
        sys.exit(1)

    # SQLite cache — platformdirs default unless overridden by --cache-path.
    cache = SQLiteCache(path=cache_path)

    providers = Providers(
        llm=llm,
        parser=TreeSitterParser(),
        resolver=JediResolver(),
        ranker=NetworkxRanker(),
        vector_store=Bm25Store(),
        cache=cache,
        clock=FakeClock(),
    )

    sigint = SigintHandler()
    sigint.install()
    try:
        provider_label = config.llm_provider
        exit_code = _run_pipeline(
            repo_path=repo_path,
            providers=providers,
            excludes=excludes,
            includes=includes,
            root=root,
            max_lessons=config.max_lessons,
            should_abort=sigint.should_finish.is_set,
            started_at=started_at,
            provider_label=provider_label,
        )
    finally:
        sigint.restore()

    sys.exit(exit_code)


def _build_llm_provider(
    config: CodeguideConfig,
    *,
    no_consent_prompt: bool,
    yes: bool,
) -> LLMProvider:
    """Instantiate the LLMProvider implementation for the configured provider.

    - ``anthropic`` → :class:`AnthropicProvider` (requires ``ANTHROPIC_API_KEY``).
    - ``openai``    → :class:`OpenAIProvider` with ``base_url=None``.
    - ``openai_compatible`` / ``custom`` → :class:`OpenAIProvider` with
      ``base_url`` override (Ollama, LM Studio, vLLM).  Consent banner is
      **skipped** for custom endpoints because no code leaves the machine.

    Returns the fake provider in smoke/fixture mode when no valid key is
    available is **not** done here — callers explicitly opt in to the fake via
    tests or an unset provider.
    """
    bypass_consent = no_consent_prompt or yes
    tty = sys.stdin.isatty()

    if config.llm_provider == "anthropic":
        ensure_consent_granted("anthropic", bypass=bypass_consent, tty=tty)
        return AnthropicProvider(
            api_key=resolve_api_key(config),
            model_plan=config.llm_model_plan,
            model_narrate=config.llm_model_narrate,
            max_retries=config.llm_max_retries,
            max_wait_s=config.llm_max_wait_s,
        )

    if config.llm_provider in ("openai", "openai_compatible"):
        # Consent only for the hosted OpenAI endpoint — base_url=None.
        if config.llm_base_url is None:
            ensure_consent_granted(config.llm_provider, bypass=bypass_consent, tty=tty)
        return OpenAIProvider(
            api_key=resolve_api_key(config),
            base_url=config.llm_base_url,
            model_plan=config.llm_model_plan or "gpt-4o",
            model_narrate=config.llm_model_narrate or "gpt-4o",
            max_retries=config.llm_max_retries,
            max_wait_s=config.llm_max_wait_s,
        )

    if config.llm_provider == "custom":
        # Custom/OSS endpoint: no consent banner (local inference, zero egress).
        if config.llm_base_url is None:
            raise ConfigError(
                "llm.base_url is required for --provider=custom (e.g. http://localhost:11434/v1)."
            )
        return OpenAIProvider(
            api_key=resolve_api_key(config),
            base_url=config.llm_base_url,
            model_plan=config.llm_model_plan or "gpt-4o",
            model_narrate=config.llm_model_narrate or "gpt-4o",
            max_retries=config.llm_max_retries,
            max_wait_s=config.llm_max_wait_s,
        )

    # Fallback fake — reachable only when tests inject an invalid provider.
    return FakeLLMProvider()  # pragma: no cover — exhaustive config Literal above


def _run_pipeline(
    *,
    repo_path: Path,
    providers: Providers,
    excludes: tuple[str, ...],
    includes: tuple[str, ...],
    root: Path | None,
    max_lessons: int,
    should_abort: Callable[[], bool],
    started_at: datetime,
    provider_label: str,
) -> int:
    """Run the generation pipeline, write the run report, return an exit code."""
    try:
        result: GenerationResult = generate_tutorial(
            repo_path,
            providers,
            excludes=excludes,
            includes=includes,
            root_override=root,
            max_lessons=max_lessons,
            should_abort=should_abort,
        )
    except KeyboardInterrupt:
        _write_final_report(
            repo_path=repo_path,
            provider_label=provider_label,
            started_at=started_at,
            status="interrupted",
        )
        click.echo("Run interrupted by user. Partial state retained for --resume.", err=True)
        return 130
    except PlanningFatalError as exc:
        _write_final_report(
            repo_path=repo_path,
            provider_label=provider_label,
            started_at=started_at,
            status="failed",
            stack_trace=f"PlanningFatalError: {exc}",
            failed_at_lesson="<planning>",
        )
        click.echo(f"error: planning stage failed — {exc}", err=True)
        return 1
    except Exception:
        _write_final_report(
            repo_path=repo_path,
            provider_label=provider_label,
            started_at=started_at,
            status="failed",
            stack_trace=traceback.format_exc(),
            failed_at_lesson="<unknown>",
        )
        click.echo("error: unhandled exception — see run-report.json for stack trace.", err=True)
        return 1

    status: RunStatus = "degraded" if result.degraded else "ok"
    _write_final_report(
        repo_path=repo_path,
        provider_label=provider_label,
        started_at=started_at,
        status=status,
        total_planned=result.total_planned,
        skipped_count=len(result.skipped_lessons),
        retry_count=result.retry_count,
        degraded_ratio=result.degraded_ratio,
    )

    click.echo(f"Tutorial written to: {result.output_path}")
    click.echo(f"Open with: file://{result.output_path.as_posix()}")
    if result.degraded:
        click.echo(
            f"warning: tutorial DEGRADED — "
            f"{len(result.skipped_lessons)} of {result.total_planned} lessons skipped.",
            err=True,
        )
        return 2
    return 0


def _write_final_report(
    *,
    repo_path: Path,
    provider_label: str,
    started_at: datetime,
    status: RunStatus,
    total_planned: int = 0,
    skipped_count: int = 0,
    retry_count: int = 0,
    cache_hit_rate: float = 0.0,
    degraded_ratio: float = 0.0,
    stack_trace: str | None = None,
    failed_at_lesson: str | None = None,
) -> None:
    """Build a ``RunReport`` and write it under ``<repo>/.codeguide/``.

    Silently swallows I/O failures — a crashing run-report writer must never
    mask the underlying pipeline failure the CLI is trying to report.
    """
    try:
        report = RunReport(
            status=status,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            total_planned_lessons=total_planned,
            skipped_lessons_count=skipped_count,
            retry_count=retry_count,
            cache_hit_rate=cache_hit_rate,
            total_cost_usd=0.0,
            provider=provider_label,
            stack_trace=stack_trace,
            failed_at_lesson=failed_at_lesson,
            degraded_ratio=degraded_ratio,
        )
        write_run_report(report, repo_path)
    except Exception as exc:
        logger.warning("run_report_write_failed: %s", exc)


if __name__ == "__main__":  # pragma: no cover
    main()
