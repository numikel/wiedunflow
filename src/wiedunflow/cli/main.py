# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""WiedunFlow CLI entrypoint.

Sprint 6 restructure: the top-level ``wiedunflow`` command is now a click
group with two subcommands:

* ``wiedunflow init`` — interactive wizard (US-002 / Track A).
* ``wiedunflow generate <repo>`` — run the 7-stage tutorial pipeline.

The ``_DefaultToGenerate`` group subclass preserves backward compatibility:
``wiedunflow <repo>`` (pre-Sprint 6 UX) still works — the first positional
that is not a known subcommand is interpreted as a repo path and routed
through ``generate``.
"""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import click

from wiedunflow import __version__
from wiedunflow.adapters import (
    Bm25Store,
    FakeClock,
    FakeLLMProvider,
    JediResolver,
    NetworkxRanker,
    TreeSitterParser,
)
from wiedunflow.adapters.anthropic_provider import AnthropicProvider
from wiedunflow.adapters.openai_provider import OpenAIProvider
from wiedunflow.adapters.sqlite_cache import SQLiteCache
from wiedunflow.cli.config import ConfigError, WiedunflowConfig, load_config, resolve_api_key
from wiedunflow.cli.consent import (
    ConsentDeniedError,
    ConsentRequiredError,
    ensure_consent_granted,
)
from wiedunflow.cli.cost_estimator import CostEstimate
from wiedunflow.cli.cost_gate import prompt_cost_gate
from wiedunflow.cli.history_rotator import write_history_copy
from wiedunflow.cli.init_wizard import run_init_wizard
from wiedunflow.cli.logging import configure as configure_logging
from wiedunflow.cli.logging import get_logger as get_structlog
from wiedunflow.cli.output import (
    init_console,
    print_cost_abort,
    print_done_summary,
    render_banner,
    render_run_report,
)
from wiedunflow.cli.run_report_writer import write_run_report
from wiedunflow.cli.signals import SigintHandler
from wiedunflow.cli.stage_reporter import StageReporter
from wiedunflow.entities.run_report import RunReport, RunStatus
from wiedunflow.interfaces.ports import LLMProvider
from wiedunflow.use_cases.generate_tutorial import (
    CostGateAbortedError,
    GenerationResult,
    MaxCostExceededError,
    Providers,
    generate_tutorial,
)
from wiedunflow.use_cases.plan_lesson_manifest import PlanningFatalError
from wiedunflow.use_cases.spend_meter import SpendMeter

logger = logging.getLogger(__name__)


class _DefaultToGenerate(click.Group):
    """Click group that treats an unknown first positional as a repo path.

    This keeps the pre-Sprint-6 UX alive: ``wiedunflow ./repo`` is rewritten
    to ``wiedunflow generate ./repo`` at parse time. Known subcommands
    (``init``, ``generate``) still resolve normally.
    """

    def resolve_command(
        self,
        ctx: click.Context,
        args: list[str],
    ) -> tuple[str | None, click.Command | None, list[str]]:
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            # First positional is not a registered subcommand — assume repo path.
            if args and not args[0].startswith("-"):
                args.insert(0, "generate")
                return super().resolve_command(ctx, args)
            raise


@click.group(
    cls=_DefaultToGenerate,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(__version__, prog_name="wiedunflow")
def cli() -> None:
    """WiedunFlow — generate interactive HTML tutorials from local Git repositories."""


@cli.command("init")
@click.option(
    "--provider",
    type=click.Choice(["anthropic", "openai", "openai_compatible", "custom"]),
    default=None,
    help="LLM provider (non-interactive: skip the provider prompt).",
)
@click.option(
    "--model-plan",
    default=None,
    metavar="MODEL",
    help="Model for planning stage (non-interactive: skip the model prompt).",
)
@click.option(
    "--model-narrate",
    default=None,
    metavar="MODEL",
    help="Model for narration stage (non-interactive: skip the model prompt).",
)
@click.option(
    "--api-key",
    default=None,
    metavar="KEY",
    help="API key for the provider (non-interactive: skip the api-key prompt).",
)
@click.option(
    "--base-url",
    default=None,
    metavar="URL",
    help="Base URL for openai_compatible / custom providers (optional).",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite an existing user-level config.yaml without prompting.",
)
def init_cmd(
    provider: str | None,
    model_plan: str | None,
    model_narrate: str | None,
    api_key: str | None,
    base_url: str | None,
    force: bool,
) -> None:
    """Interactive wizard — write a user-level ``config.yaml`` (US-002).

    All prompts can be skipped via flags (US-003). Running ``wiedunflow init``
    a second time refuses to overwrite the existing file unless ``--force``
    is passed.
    """
    exit_code = run_init_wizard(
        provider=provider,
        model_plan=model_plan,
        model_narrate=model_narrate,
        api_key=api_key,
        base_url=base_url,
        force=force,
    )
    sys.exit(exit_code)


@cli.command("generate")
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
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help="Run Stages 0..4 and emit a preview HTML without paying for narration (US-015).",
)
@click.option(
    "--review-plan",
    "review_plan",
    is_flag=True,
    default=False,
    help="Pause after Stage 4 and open the lesson manifest in $EDITOR (US-016).",
)
@click.option(
    "--log-format",
    "log_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Structured log output format on stderr (US-022).",
)
@click.option(
    "--no-cost-prompt",
    "no_cost_prompt",
    is_flag=True,
    default=False,
    help="Skip the interactive cost-gate prompt (US-084 — Sprint 8 / v0.2.0).",
)
@click.option(
    "--output",
    "-o",
    "output_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help=(
        "Override the tutorial output path. Default: <repo>/wiedunflow-<repo-name>.html "
        "(written into the analyzed repository). Relative paths resolve against the current "
        "directory; if the path has no extension, .html is appended automatically "
        "(--output my-tour -> my-tour.html). Configurable in tutorial.config.yaml as "
        "`output_path`."
    ),
)
@click.option(
    "--no-log-redaction",
    "no_log_redaction",
    is_flag=True,
    default=False,
    hidden=True,
    help="(dev-only) Disable SecretFilter in logs.",
)
@click.option(
    "--python-path",
    "python_path",
    type=click.Path(exists=True, dir_okay=False, file_okay=True, path_type=Path),
    default=None,
    metavar="PATH",
    help=(
        "Override the Python interpreter used by Jedi for call-graph resolution "
        "(e.g. --python-path /path/to/repo/.venv/bin/python). "
        "Default: auto-detect from repo's .venv/, venv/, or env/."
    ),
)
@click.option(
    "--bootstrap-venv",
    "bootstrap_venv",
    is_flag=True,
    default=False,
    help=(
        "Bootstrap a virtual environment in the analyzed repo via 'uv sync' before "
        "analysis (opt-in, default off). Useful when the repo has pyproject.toml/uv.lock "
        "but no .venv/. Requires 'uv' to be available on PATH."
    ),
)
def generate_cmd(
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
    dry_run: bool,
    review_plan: bool,
    log_format: str,
    no_cost_prompt: bool,
    output_path: Path | None,
    no_log_redaction: bool,
    python_path: Path | None,
    bootstrap_venv: bool,
) -> None:
    """Generate an interactive HTML tutorial from a local Git repository."""
    json_mode = log_format == "json"
    configure_logging(json_mode=json_mode, redact_secrets=not no_log_redaction)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    console = init_console(json_mode=json_mode)
    structlog_logger = get_structlog(stage="cli")

    # Tier 1: venv bootstrap (opt-in via --bootstrap-venv).
    # Must run before JediResolver is instantiated so the detected .venv/ path
    # is available when _detect_python_path() scans the repo root.
    if bootstrap_venv:
        bootstrapped = _bootstrap_venv(repo_path)
        if bootstrapped is not None and python_path is None:
            # Only override when the caller did not supply an explicit --python-path.
            python_path = bootstrapped

    # Sprint 8: startup banner — TTY-only, suppressed for non-interactive output
    # (CI, pipe, redirect) and JSON log mode where the stdout is consumer-readable.
    is_tty = sys.stdin.isatty() and sys.stdout.isatty()
    if is_tty and not json_mode:
        render_banner(console, version=__version__)

    ensure_gitignore_entry(repo_path)

    started_at = datetime.now(UTC)

    if dry_run:
        structlog_logger.info("dry_run_scheduled", msg="dry-run mode: stages 5-7 skipped")
    if review_plan:
        structlog_logger.info(
            "review_plan_scheduled", msg="--review-plan: will pause after Stage 4"
        )

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
                "output_path": output_path,
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
        resolver=JediResolver(python_path=python_path),
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
            excludes=tuple(config.exclude_patterns) + excludes,
            includes=tuple(config.include_patterns) + includes,
            root=root,
            max_lessons=config.max_lessons,
            should_abort=sigint.should_finish.is_set,
            started_at=started_at,
            provider_label=provider_label,
            console=console,
            dry_run=dry_run,
            review_plan=review_plan,
            max_cost_usd=max_cost_usd,
            auto_yes=yes,
            no_cost_prompt=no_cost_prompt,
            is_tty=is_tty,
            json_mode=json_mode,
            output_path=_resolve_output_path(config.output_path, repo_path=repo_path),
        )
    finally:
        sigint.restore()

    rotate_run_report_history(repo_path)
    sys.exit(exit_code)


def main() -> None:
    """Process entrypoint — launches the interactive menu (no args + TTY) or the click group.

    ADR-0013: when ``wiedunflow`` is invoked with no arguments in an interactive
    terminal, the menu-driven TUI launches. All other invocations
    (``wiedunflow generate <repo>``, ``wiedunflow init``, ``wiedunflow --version``,
    non-TTY, ``WIEDUNFLOW_NO_MENU=1``) flow through the existing click group
    bit-exact.
    """
    from wiedunflow.cli.menu import QuestionaryMenuIO, _should_launch_menu, main_menu_loop

    if _should_launch_menu():
        main_menu_loop(QuestionaryMenuIO())
        return
    cli()


def _build_llm_provider(
    config: WiedunflowConfig,
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
            # ADR-0015 (v0.7.0): gpt-5.4 is the project default for OpenAI.
            model_plan=config.llm_model_plan or "gpt-5.4",
            model_narrate=config.llm_model_narrate or "gpt-5.4",
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
            # ADR-0015 (v0.7.0): gpt-5.4 is the project default (Ollama / vLLM
            # endpoints may use any model name; this default matters only when
            # llm.model_plan / model_narrate are unset and the local endpoint
            # accepts gpt-5.4).
            model_plan=config.llm_model_plan or "gpt-5.4",
            model_narrate=config.llm_model_narrate or "gpt-5.4",
            max_retries=config.llm_max_retries,
            max_wait_s=config.llm_max_wait_s,
        )

    # Fallback fake — reachable only when tests inject an invalid provider.
    return FakeLLMProvider()  # pragma: no cover — exhaustive config Literal above


def _resolve_output_path(configured: Path | None, *, repo_path: Path) -> Path:
    """Return an absolute :class:`Path` for the tutorial HTML output.

    v0.9.1+ behaviour (responsive to user feedback after the v0.9.0 push):

    1. **Default location is the analyzed repo, not cwd.** When ``configured``
       is ``None``, return ``<repo>/wiedunflow-<repo-name>.html`` so the
       generated tutorial lives next to the source it describes.
    2. **Relative paths resolve against cwd** (preserved from Sprint 8 /
       v0.2.0): ``--output ./out/tour.html`` lands where the shell points,
       not where the orchestrator's defaults are computed.
    3. **Auto-append ``.html`` extension** when the user-supplied path has no
       suffix. ``--output my-tour`` becomes ``my-tour.html`` — closes the
       common-case of "I forgot the extension and the file did not open in
       the browser." If the user supplies ``.htm`` or any other suffix it is
       preserved verbatim.
    """
    if configured is None:
        return (repo_path.expanduser() / f"wiedunflow-{repo_path.name}.html").resolve()

    expanded = configured.expanduser()
    base = expanded if expanded.is_absolute() else (Path.cwd() / expanded)
    if base.suffix == "":
        base = base.with_suffix(".html")
    return base.resolve()


def _build_pricing_chain() -> object:
    """Build the live-pricing chain (LiteLLM cached → static fallback).

    Extracted as a named function so tests can call it in isolation without
    triggering the full ``_run_pipeline`` machinery.

    Network failures (timeout, 5xx, malformed JSON) inside ``LiteLLMPricingCatalog``
    downgrade to ``None`` per query, so the chain falls through to
    :class:`StaticPricingCatalog` and never raises.
    """
    from wiedunflow.adapters.cached_pricing_catalog import (
        CachedPricingCatalog,
        ChainedPricingCatalog,
    )
    from wiedunflow.adapters.litellm_pricing_catalog import LiteLLMPricingCatalog
    from wiedunflow.adapters.static_pricing_catalog import StaticPricingCatalog

    return ChainedPricingCatalog(
        [
            CachedPricingCatalog(LiteLLMPricingCatalog(), provider_name="litellm"),
            StaticPricingCatalog(),
        ]
    )


def _bootstrap_venv(repo_path: Path) -> Path | None:
    """Run ``uv sync --no-dev`` in the analyzed repo to bootstrap a ``.venv/`` for Jedi.

    This is the implementation for the ``--bootstrap-venv`` flag (Tier 1 opt-in).
    Only attempted when the repo contains a ``pyproject.toml``.  Failure is
    non-fatal — the caller falls back to WiedunFlow's own interpreter.

    Args:
        repo_path: Root of the repository being analyzed.

    Returns:
        Path to the bootstrapped interpreter (from :func:`_detect_python_path`),
        or ``None`` on any failure.
    """
    import subprocess

    from wiedunflow.adapters.jedi_resolver import _detect_python_path

    if not (repo_path / "pyproject.toml").exists():
        logger.warning(
            "bootstrap_venv_no_pyproject repo=%s — no pyproject.toml; skipping bootstrap.",
            repo_path,
        )
        return None

    logger.info("bootstrap_venv_start repo=%s", repo_path)
    try:
        result = subprocess.run(
            ["uv", "sync", "--no-dev"],
            cwd=repo_path,
            timeout=600,
            check=False,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        logger.warning(
            "bootstrap_venv_timeout repo=%s — 'uv sync' timed out after 600 s; skipping.",
            repo_path,
        )
        return None
    except FileNotFoundError:
        logger.warning("bootstrap_venv_uv_not_found — 'uv' not found on PATH; skipping.")
        return None

    if result.returncode != 0:
        logger.warning(
            "bootstrap_venv_failed exit=%d stderr=%s",
            result.returncode,
            result.stderr[:500],
        )
        return None

    detected = _detect_python_path(repo_path)
    if detected is None:
        logger.warning(
            "bootstrap_venv_completed_but_no_interpreter repo=%s"
            " — 'uv sync' succeeded but no interpreter found in .venv/",
            repo_path,
        )
    else:
        logger.info("bootstrap_venv_done python=%s", detected)
    return detected


def _run_pipeline(  # noqa: PLR0911, PLR0912, PLR0915 — CLI dispatcher with many exception paths
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
    console: object,
    dry_run: bool = False,
    review_plan: bool = False,
    max_cost_usd: float | None = None,
    auto_yes: bool = False,
    no_cost_prompt: bool = False,
    is_tty: bool = False,
    json_mode: bool = False,
    output_path: Path | None = None,
) -> int:
    """Run the generation pipeline, write the run report, return an exit code."""
    # Sprint 8: animated stage reporter (suppressed for JSON log mode where
    # stdout is consumer-readable). NoOpReporter takes over headless callers.
    progress: StageReporter | None = StageReporter(console=console) if not json_mode else None

    # Pull live model ids off the LLM provider so the cost-gate panel shows
    # what the user actually configured (gpt-4.1 / claude-opus-4-7 / etc.)
    # instead of the hardcoded haiku/opus labels (ADR-0013 follow-up bug).
    llm_provider_obj = providers.llm
    plan_label = str(getattr(llm_provider_obj, "model_plan", "plan"))
    narrate_label = str(getattr(llm_provider_obj, "model_narrate", "narrate"))

    # ADR-0014: live pricing chain (LiteLLM 24h cache → static fallback)
    # so the cost-gate USD estimate matches the user's actual provider rates.
    pricing_chain = _build_pricing_chain()

    # v0.9.0 cost reporting: create a SpendMeter so providers can charge()
    # token usage and we can report total_cost_usd in the run report.
    # Budget defaults to 100 USD (high soft cap — actual limit is the cost-gate
    # pre-flight check before any API calls are made).
    from wiedunflow.interfaces.pricing_catalog import PricingCatalog

    _budget = max_cost_usd if max_cost_usd is not None else 100.0
    _pricing: PricingCatalog | None = pricing_chain  # type: ignore[assignment]
    spend_meter = SpendMeter(budget_usd=_budget, pricing=_pricing)

    def _cost_gate(estimate: CostEstimate) -> bool:
        """Closure passed to ``generate_tutorial`` — Sprint 8 / US-084 / Q4."""
        return prompt_cost_gate(
            console,
            estimate=estimate,
            auto_yes=auto_yes,
            prompt_disabled=no_cost_prompt,
            is_tty=is_tty,
            plan_model_label=plan_label,
            narrate_model_label=narrate_label,
        )

    try:
        result: GenerationResult = generate_tutorial(
            repo_path,
            providers,
            output_path=output_path,
            excludes=excludes,
            includes=includes,
            root_override=root,
            max_lessons=max_lessons,
            should_abort=should_abort,
            dry_run=dry_run,
            review_plan=review_plan,
            max_cost_usd=max_cost_usd,
            progress=progress,
            cost_gate_callback=_cost_gate,
            pricing_catalog=pricing_chain,
            spend_meter=spend_meter,
        )
    except KeyboardInterrupt:
        _write_final_report(
            repo_path=repo_path,
            provider_label=provider_label,
            started_at=started_at,
            status="interrupted",
        )
        if progress is not None:
            render_run_report(
                console,  # type: ignore[arg-type]
                status="failed",  # render as failed-style frame; status line itself is custom
                lines=[
                    ("status", "interrupted by user"),
                    ("hint", "partial state retained for --resume"),
                ],
            )
        else:
            click.echo("Run interrupted by user. Partial state retained for --resume.", err=True)
        return 130
    except CostGateAbortedError:
        # Clean user abort at cost-gate prompt (Sprint 8 / US-084) — exit 0.
        _write_final_report(
            repo_path=repo_path,
            provider_label=provider_label,
            started_at=started_at,
            status="ok",
        )
        if progress is not None:
            print_cost_abort(console, elapsed=_format_elapsed(started_at))  # type: ignore[arg-type]
        else:
            click.echo("aborted by user. no API calls were made.", err=True)
        return 0
    except MaxCostExceededError as exc:
        _write_final_report(
            repo_path=repo_path,
            provider_label=provider_label,
            started_at=started_at,
            status="failed",
            stack_trace=f"MaxCostExceededError: {exc}",
            failed_at_lesson="<cost-gate>",
        )
        if progress is not None:
            render_run_report(
                console,  # type: ignore[arg-type]
                status="failed",
                lines=[
                    ("failed at", "cost-gate (--max-cost)"),
                    ("estimate", f"${exc.estimate_usd:.2f}"),
                    ("cap", f"${exc.cap_usd:.2f}"),
                    ("lessons", str(exc.lessons)),
                    ("note", "no API calls were made"),
                ],
            )
        else:
            click.echo(
                f"aborted: estimated cost ${exc.estimate_usd:.2f} exceeds --max-cost "
                f"${exc.cap_usd:.2f}. No API calls were made.",
                err=True,
            )
        return 1
    except PlanningFatalError as exc:
        _write_final_report(
            repo_path=repo_path,
            provider_label=provider_label,
            started_at=started_at,
            status="failed",
            stack_trace=f"PlanningFatalError: {exc}",
            failed_at_lesson="<planning>",
        )
        if progress is not None:
            render_run_report(
                console,  # type: ignore[arg-type]
                status="failed",
                lines=[
                    ("failed at", "stage 5 (planning)"),
                    ("reason", str(exc)),
                ],
            )
        else:
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
        if progress is not None:
            render_run_report(
                console,  # type: ignore[arg-type]
                status="failed",
                lines=[
                    ("failed at", "<unknown>"),
                    ("see", ".wiedunflow/run-report.json for stack trace"),
                ],
            )
        else:
            click.echo(
                "error: unhandled exception — see run-report.json for stack trace.", err=True
            )
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
        hallucinated_symbols=result.hallucinated_symbols,
        total_cost_usd=result.total_cost_usd,
    )

    if progress is not None:
        # Sprint 8: render the run-report card in place of the v0.1.0 one-liner.
        elapsed = _format_elapsed(started_at)
        rendered_status: Literal["success", "degraded"] = (
            "degraded" if result.degraded else "success"
        )
        report_lines: list[tuple[str, str]] = [
            (
                "lessons",
                f"{result.total_planned - len(result.skipped_lessons)} of "
                f"{result.total_planned} narrated"
                + (f" · {len(result.skipped_lessons)} skipped" if result.skipped_lessons else ""),
            ),
            ("retries", f"{result.retry_count} grounding retries"),
            ("elapsed", elapsed),
            ("output", str(result.output_path)),
            ("total_cost", f"${result.total_cost_usd:.4f}"),
        ]
        render_run_report(console, status=rendered_status, lines=report_lines)  # type: ignore[arg-type]
        print_done_summary(console, path=result.output_path)  # type: ignore[arg-type]
    else:
        click.echo(f"Tutorial written to: {result.output_path}")
        print_done_summary(console, path=result.output_path)  # type: ignore[arg-type]

    if result.degraded:
        if progress is None:
            click.echo(
                f"warning: tutorial DEGRADED — "
                f"{len(result.skipped_lessons)} of {result.total_planned} lessons skipped.",
                err=True,
            )
        return 2
    return 0


def _format_elapsed(started_at: datetime) -> str:
    """Format ``MM:SS`` elapsed time since ``started_at`` (Sprint 8 helper)."""
    delta = (datetime.now(UTC) - started_at).total_seconds()
    minutes = int(delta) // 60
    seconds = int(delta) % 60
    return f"{minutes}:{seconds:02d}"


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
    hallucinated_symbols: tuple[str, ...] = (),
    total_cost_usd: float = 0.0,
) -> None:
    """Build a ``RunReport`` and write it under ``<repo>/.wiedunflow/``.

    Silently swallows I/O failures -- a crashing run-report writer must never
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
            total_cost_usd=total_cost_usd,
            provider=provider_label,
            stack_trace=stack_trace,
            failed_at_lesson=failed_at_lesson,
            degraded_ratio=degraded_ratio,
            hallucinated_symbols=hallucinated_symbols,
            hallucinated_symbols_count=len(hallucinated_symbols),
        )
        write_run_report(report, repo_path)
    except Exception as exc:
        logger.warning("run_report_write_failed: %s", exc)


_GITIGNORE_ENTRY = ".wiedunflow/\n"


def ensure_gitignore_entry(repo_path: Path) -> None:
    """Append ``.wiedunflow/`` to ``.gitignore`` idempotently (US-057).

    Creates ``.gitignore`` if absent. Preserves any existing content. If the
    ``.wiedunflow/`` entry is already present (with or without trailing newline)
    the file is left untouched.
    """
    gitignore_path = repo_path / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(_GITIGNORE_ENTRY, encoding="utf-8")
        return
    existing = gitignore_path.read_text(encoding="utf-8")
    if any(
        line.strip() == ".wiedunflow/" or line.strip() == ".wiedunflow"
        for line in existing.splitlines()
    ):
        return
    prefix = "" if existing.endswith("\n") else "\n"
    gitignore_path.write_text(existing + prefix + _GITIGNORE_ENTRY, encoding="utf-8")


def rotate_run_report_history(repo_path: Path) -> None:
    """Copy the current run-report into the history folder (US-058).

    Silent-safe: any I/O error is logged via structlog but must not surface to
    the user — failure to rotate is a non-fatal observability concern.
    """
    current = repo_path / ".wiedunflow" / "run-report.json"
    if not current.is_file():
        return
    try:
        write_history_copy(
            current_report=current,
            history_dir=repo_path / ".wiedunflow" / "history",
            keep_latest=10,
        )
    except OSError as exc:
        logger.warning("run_report_history_failed: %s", exc)


if __name__ == "__main__":  # pragma: no cover
    main()
