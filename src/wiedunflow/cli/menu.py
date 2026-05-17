# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Interactive menu-driven TUI ("centrum dowodzenia") — ADR-0013.

This module is the **single sink** for ``import questionary`` (three-sink
rule: rich → output.py, questionary → menu.py, plain print → menu_banner.py).
``cost_gate.py``, ``init_wizard.py``, and pipeline orchestration receive
prompts via the ``MenuIO`` Protocol injection — never import questionary
directly.

The menu activates only when ``wiedunflow`` is invoked with no arguments in
a TTY. ``wiedunflow generate <repo>`` and ``wiedunflow init`` keep their
existing one-shot CLI behavior bit-exact (Sprint 7 eval CI workflow contract).

Step 3 (current): MenuIO Protocol + QuestionaryMenuIO + main_menu_loop with
the 7-item top-level menu. Sub-wizards (`_run_*_from_menu`) are stubs that
print "not yet implemented" — wired in Steps 4b through 8.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

import questionary
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings

from wiedunflow.adapters.anthropic_model_catalog import AnthropicModelCatalog
from wiedunflow.adapters.cached_model_catalog import CachedModelCatalog
from wiedunflow.adapters.openai_model_catalog import OpenAIModelCatalog
from wiedunflow.cli.config import (
    ConfigError,
    WiedunflowConfig,
    load_config,
    user_config_path,
    validate_base_url,
)
from wiedunflow.cli.menu_banner import print_banner
from wiedunflow.cli.picker_sources import discover_git_repos, load_recent_runs
from wiedunflow.interfaces.model_catalog import ModelCatalog

# Top-level menu items. Order is meaningful — most-used first.
# v0.4.0 (post-launch UX iteration): "Initialize config" + "Show config" merged
# into a single "Configuration" item — Show-config now bootstraps init when
# no saved config exists, so two menu entries pointed at the same surface.
MENU_GENERATE = "Generate tutorial"
MENU_RECENT = "Recent runs"
MENU_CONFIG = "Configuration"
MENU_ESTIMATE = "Estimate cost"
MENU_HELP = "Help"
MENU_EXIT = "Exit"

_MENU_CHOICES: list[str] = [
    MENU_GENERATE,
    MENU_RECENT,
    MENU_CONFIG,
    MENU_ESTIMATE,
    MENU_HELP,
    MENU_EXIT,
]

# Resume is now folded into Recent runs — kept as alias so external callers /
# legacy tests that imported the constant still resolve to the new entrypoint.
MENU_RESUME = MENU_RECENT  # deprecated alias

# Backwards compat for tests / external callers that imported the old names.
MENU_INITIALIZE = MENU_CONFIG  # deprecated alias
MENU_SHOW_CONFIG = MENU_CONFIG  # deprecated alias


@runtime_checkable
class MenuIO(Protocol):
    """Abstract IO Protocol for the interactive menu (ADR-0013 decision 5).

    All TUI prompts in ``menu.py`` go through this Protocol, never through
    ``questionary`` directly. This decouples menu logic from the library —
    ``QuestionaryMenuIO`` is the production impl, ``FakeMenuIO`` (in
    ``tests/unit/cli/_fake_menu_io.py``) is the deterministic test double.

    Every method returns ``None`` when the user aborts (Esc / Ctrl+C). Callers
    must check for ``None`` at every prompt boundary and treat it as "user
    cancelled this step" — usually returning to the parent screen.
    """

    def select(self, message: str, choices: list[str], default: str | None = None) -> str | None:
        """Render a single-select picker with arrow navigation. ``None`` = aborted."""
        ...

    def text(self, message: str, default: str = "") -> str | None:
        """Render a free-text input prompt. ``None`` = aborted."""
        ...

    def path(self, message: str, only_directories: bool = False, default: str = "") -> str | None:
        """Render a path picker with native PathCompleter (tab completion)."""
        ...

    def password(self, message: str) -> str | None:
        """Render a masked password input."""
        ...

    def confirm(self, message: str, default: bool = False) -> bool | None:
        """Render a yes/no prompt. ``None`` = aborted (Esc/Ctrl+C)."""
        ...


def _bind_esc_to_abort(question: Any) -> Any:
    """Patch a questionary ``Question`` so Esc exits with ``None`` (= back/abort).

    questionary 2.x maps Ctrl+C to abort in every prompt but **does not** map
    Esc on ``text`` / ``password`` / ``path`` prompts (only on ``select``).
    To make Esc the universal "back" key in our TUI we attach an extra key
    binding to the underlying prompt_toolkit application.

    questionary's existing bindings live in a ``MergedKeyBindings`` container
    which is immutable, so we build a fresh ``KeyBindings`` with our Esc
    handler and merge the two via ``merge_key_bindings`` — replacing the
    application's ``key_bindings`` attribute with the merged result.

    Returns the same question (call site chains ``.ask()``).
    """
    app = getattr(question, "application", None)
    if app is None:
        return question  # questionary internals changed — fall back to Ctrl+C only

    extra = KeyBindings()

    @extra.add("escape", eager=True)
    def _(event: Any) -> None:
        event.app.exit(result=None)

    existing = getattr(app, "key_bindings", None)
    app.key_bindings = merge_key_bindings([existing, extra]) if existing is not None else extra
    return question


class QuestionaryMenuIO:
    """Production ``MenuIO`` impl backed by questionary 2.x.

    ``questionary.<prompt>().ask()`` returns the selected value on Enter and
    ``None`` on Ctrl+C — perfect for our abort-as-None protocol. We never
    use ``unsafe_ask()`` because it propagates KeyboardInterrupt past the
    menu loop, killing the process when the user only meant to cancel a
    sub-wizard step. ``_bind_esc_to_abort`` adds Esc as a synonym for
    Ctrl+C on ``text`` / ``password`` / ``path`` prompts (questionary maps
    Esc itself only on ``select`` and ``confirm``).
    """

    def select(self, message: str, choices: list[str], default: str | None = None) -> str | None:
        return cast(
            "str | None",
            questionary.select(message, choices=choices, default=default).ask(),
        )

    def text(self, message: str, default: str = "") -> str | None:
        q = _bind_esc_to_abort(questionary.text(message, default=default))
        return cast("str | None", q.ask())

    def path(self, message: str, only_directories: bool = False, default: str = "") -> str | None:
        q = _bind_esc_to_abort(
            questionary.path(message, only_directories=only_directories, default=default)
        )
        return cast("str | None", q.ask())

    def password(self, message: str) -> str | None:
        q = _bind_esc_to_abort(questionary.password(message))
        return cast("str | None", q.ask())

    def confirm(self, message: str, default: bool = False) -> bool | None:
        return cast("bool | None", questionary.confirm(message, default=default).ask())


def _clear_screen() -> None:
    """Best-effort ANSI clear: clears the visible viewport AND scrollback buffer.

    Used between top-level menu iterations and on sub-wizard entry so the TUI
    feels like a real "centrum dowodzenia" — each screen overwrites the last
    instead of accumulating in scrollback. Inside sub-wizards we do NOT clear
    between consecutive prompts; validation errors must stay visible until
    the user acts on them.

    Modern terminals (Windows Terminal, VS Code, iTerm2, kitty, WezTerm,
    PowerShell 7+) interpret these escapes natively. Legacy ``cmd.exe``
    (without VT enabled) renders them as garbage glyphs; the
    ``WIEDUNFLOW_NO_CLEAR=1`` env var disables clearing for that case.
    """
    if os.environ.get("WIEDUNFLOW_NO_CLEAR"):
        return
    # \033[2J = clear screen, \033[3J = clear scrollback, \033[H = cursor home.
    print("\033[2J\033[3J\033[H", end="", flush=True)


def _redraw_chrome(breadcrumb: str | None = None) -> None:
    """Clear screen and re-paint the persistent ASCII banner + breadcrumb.

    Called before every screen the user sees so the banner stays visible at
    the top throughout the whole TUI session — the menu, every sub-wizard,
    every section. Optional ``breadcrumb`` shows where the user is
    ("Generate · Section 1/5 · Repo & Output", "Initialize config", etc.).

    Tests set ``WIEDUNFLOW_NO_CLEAR=1`` to suppress the entire chrome (clear
    AND banner) so ``capsys`` assertions stay focused on the wizard text.
    """
    if os.environ.get("WIEDUNFLOW_NO_CLEAR"):
        return
    _clear_screen()
    print_banner()
    if breadcrumb:
        print(f"  {breadcrumb}")
        print()


def _should_launch_menu() -> bool:
    """Return ``True`` when ``wiedunflow`` should launch the interactive menu.

    Activation conditions (all must be true):
    - ``sys.argv[1:]`` is empty (no subcommand or positional args).
    - ``sys.stdin.isatty()`` AND ``sys.stdout.isatty()`` (real interactive
      terminal — both directions must be a TTY so a CI job with stdout
      hooked to a log file does not accidentally launch the menu).
    - ``WIEDUNFLOW_NO_MENU`` env var is **not** set (emergency escape hatch
      for scripts that want to invoke ``wiedunflow`` with no args without
      entering interactive mode).

    Returns:
        ``True`` if the menu should launch; ``False`` for all other cases
        (subcommands, --version/--help, non-TTY, env override).
    """
    if sys.argv[1:]:
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    return not os.environ.get("WIEDUNFLOW_NO_MENU")


def main_menu_loop(
    io: MenuIO,
    *,
    anthropic_catalog: ModelCatalog | None = None,
    openai_catalog: ModelCatalog | None = None,
) -> None:
    """Run the interactive top-level menu loop.

    Renders the welcome banner once on entry, then loops on the 7-item
    selector. Each choice dispatches to its ``_run_*_from_menu`` helper;
    after the helper returns, the loop redraws the menu. Loop exits on
    explicit ``Exit`` or on Esc/Ctrl+C followed by a confirm-exit prompt.

    Args:
        io: ``MenuIO`` impl — usually ``QuestionaryMenuIO`` in production,
            ``FakeMenuIO`` in tests.
        anthropic_catalog: Optional override for the Anthropic model picker
            (tests inject a stub; production uses cached SDK fetch).
        openai_catalog: Optional override for the OpenAI model picker.
    """
    if anthropic_catalog is None:
        anthropic_catalog = CachedModelCatalog(AnthropicModelCatalog(), provider_name="anthropic")
    if openai_catalog is None:
        openai_catalog = CachedModelCatalog(OpenAIModelCatalog(), provider_name="openai")

    while True:
        _redraw_chrome()
        choice = io.select("What would you like to do?", choices=_MENU_CHOICES)

        if choice is None:
            # Esc / Ctrl+C from the top-level menu — confirm exit.
            if io.confirm("Exit WiedunFlow?", default=True):
                return
            continue

        if choice == MENU_EXIT:
            return

        _dispatch_action(
            choice,
            io,
            anthropic_catalog=anthropic_catalog,
            openai_catalog=openai_catalog,
        )


def _dispatch_action(
    choice: str,
    io: MenuIO,
    *,
    anthropic_catalog: ModelCatalog,
    openai_catalog: ModelCatalog,
) -> None:
    """Route a top-level menu choice to its sub-wizard helper.

    Each helper is responsible for its own internal Esc/abort handling and
    must return cleanly so the main loop can redraw the menu.
    """
    if choice == MENU_GENERATE:
        _run_generate_from_menu(
            io,
            anthropic_catalog=anthropic_catalog,
            openai_catalog=openai_catalog,
        )
    elif choice == MENU_CONFIG:
        _run_config_from_menu(
            io,
            anthropic_catalog=anthropic_catalog,
            openai_catalog=openai_catalog,
        )
    elif choice == MENU_RECENT:
        _run_recent_from_menu(io)
    elif choice == MENU_ESTIMATE:
        _run_estimate_from_menu(io)
    elif choice == MENU_HELP:
        _run_help_from_menu(io)
    # MENU_EXIT is handled in the loop directly — never reaches here.


# ---------------------------------------------------------------------------
# Sub-wizard stubs — wired in Steps 4b through 8 of the v0.4.0 sprint plan.
# Each prints a placeholder and returns; the main loop redraws the menu.
# ---------------------------------------------------------------------------


_INIT_DEFAULTS: dict[str, str] = {
    "provider": "anthropic",
    "model_plan": "",
    "model_narrate": "",
    "api_key": "",
    "base_url": "",
    "http_read_timeout_s": "",
}

# Mirrors the Pydantic range on ``WiedunflowConfig.llm_http_read_timeout_s``
# so the interactive wizard rejects out-of-range values before they reach
# config validation (avoids surfacing Pydantic stack traces to end users).
_HTTP_TIMEOUT_MIN_S = 1
_HTTP_TIMEOUT_MAX_S = 3600


def _init_step_default(step: str, state: dict[str, str]) -> str:
    """Return the prompt default for ``step`` given current ``state``.

    For model fields the default depends on the chosen provider so the user
    sees a sensible suggestion the first time and the previously-entered
    value when navigating back.
    """
    if step == "model_plan":
        return state["model_plan"] or (
            "claude-sonnet-4-6" if state["provider"] == "anthropic" else "gpt-4.1"
        )
    if step == "model_narrate":
        return state["model_narrate"] or (
            "claude-opus-4-7" if state["provider"] == "anthropic" else "gpt-4.1"
        )
    return state.get(step, "")


def _init_step_prompt(
    step: str,
    io: MenuIO,
    state: dict[str, str],
    *,
    anthropic_catalog: ModelCatalog,
    openai_catalog: ModelCatalog,
) -> str | None:
    """Render the prompt for one init step. Returns the new value or ``None`` on Esc.

    For ``model_plan`` / ``model_narrate`` and a hosted provider (anthropic /
    openai) the prompt is a ``select`` picker fed from the dynamic
    ``ModelCatalog`` (matches the Generate sub-wizard §2 UX). For
    openai_compatible / custom we fall back to free text because the
    endpoint may host any model id.
    """
    if step == "provider":
        return io.select("Provider:", choices=_PROVIDERS, default=state["provider"])
    if step in ("model_plan", "model_narrate"):
        label = "Planning model:" if step == "model_plan" else "Narration model:"
        if state["provider"] == "anthropic":
            return _pick_hosted_model(io, catalog=anthropic_catalog, label=label)
        if state["provider"] == "openai":
            return _pick_hosted_model(io, catalog=openai_catalog, label=label)
        return io.text(label, default=_init_step_default(step, state))
    if step == "api_key":
        return io.password("API key:")
    if step == "base_url":
        return io.text(
            "Base URL (e.g. http://localhost:11434/v1):",
            default=state["base_url"],
        )
    if step == "http_read_timeout_s":
        return io.text(
            "HTTP read timeout in seconds (Ollama/vLLM may need minutes on CPU):",
            default=state["http_read_timeout_s"] or "600",
        )
    return None  # pragma: no cover — unknown step name is a programming bug


def _init_steps_for(provider: str) -> list[str]:
    """Return the ordered step list for a given provider.

    base_url is collected only for ``openai_compatible`` / ``custom`` — the
    list is rebuilt every iteration so changing the provider mid-wizard
    inserts/removes the base_url step without losing other state.
    """
    base = ["provider", "model_plan", "model_narrate", "api_key"]
    if provider in ("openai_compatible", "custom"):
        base.append("base_url")
        base.append("http_read_timeout_s")
    return base


def _run_init_from_menu(
    io: MenuIO,
    *,
    anthropic_catalog: ModelCatalog | None = None,
    openai_catalog: ModelCatalog | None = None,
) -> None:
    """Interactive provider/model/key wizard reachable from the main menu.

    Implemented as a step machine so Esc behaves like **back** rather than
    **abort**: pressing Esc on any step except the first returns to the
    previous step with the prior value pre-filled. Esc on the first step
    aborts the wizard back to the menu (ADR-0013 D#6).

    Mirrors ``init_wizard.run_init_wizard`` (which still backs ``wiedunflow
    init`` via Click prompts) but uses the ``MenuIO`` Protocol so the menu's
    look and feel stays consistent. Writes the same nested YAML structure
    to ``user_config_path()``.
    """
    import os
    import sys

    import yaml

    if anthropic_catalog is None:
        anthropic_catalog = CachedModelCatalog(AnthropicModelCatalog(), provider_name="anthropic")
    if openai_catalog is None:
        openai_catalog = CachedModelCatalog(OpenAIModelCatalog(), provider_name="openai")

    _redraw_chrome("Initialize config")

    config_path = user_config_path()

    if config_path.exists():
        overwrite = io.confirm(f"{config_path} already exists. Overwrite?", default=False)
        if overwrite is None or not overwrite:
            print("  Init cancelled · existing config preserved.")
            return

    state: dict[str, str] = dict(_INIT_DEFAULTS)
    cursor = 0

    while True:
        steps = _init_steps_for(state["provider"])
        if cursor >= len(steps):
            break
        step = steps[cursor]
        result = _init_step_prompt(
            step,
            io,
            state,
            anthropic_catalog=anthropic_catalog,
            openai_catalog=openai_catalog,
        )
        if result is None:
            if cursor == 0:
                print("  Init cancelled.")
                return
            cursor -= 1
            continue

        # Validate base_url immediately after user input so users can correct
        # the value without losing other wizard state (re-prompt, not abort).
        if step == "base_url" and result.strip():
            try:
                validate_base_url(result.strip(), provider=state["provider"])
            except ConfigError as exc:
                print(f"  ! {exc}")
                continue  # stay on same step (cursor unchanged)

        # Same re-prompt pattern for the timeout field: surface Pydantic's
        # range/type error without dropping the user back to the menu.
        if step == "http_read_timeout_s" and result.strip():
            try:
                parsed = int(result.strip())
            except ValueError:
                print(f"  ! HTTP read timeout must be an integer, got {result!r}")
                continue
            if not _HTTP_TIMEOUT_MIN_S <= parsed <= _HTTP_TIMEOUT_MAX_S:
                print(
                    f"  ! HTTP read timeout must be between "
                    f"{_HTTP_TIMEOUT_MIN_S} and {_HTTP_TIMEOUT_MAX_S} seconds, got {parsed}"
                )
                continue

        state[step] = result
        cursor += 1

    # Defense-in-depth — validate again before writing to disk even if the
    # step machine somehow delivered an invalid value.
    raw_base_url = state["base_url"].strip() or None
    base_url = validate_base_url(raw_base_url, provider=state["provider"])
    llm_block: dict[str, Any] = {
        "provider": state["provider"],
        "model_plan": state["model_plan"],
        "model_narrate": state["model_narrate"],
        "api_key": state["api_key"],
    }
    if base_url:
        llm_block["base_url"] = base_url
    timeout_raw = state["http_read_timeout_s"].strip()
    if timeout_raw:
        # Step machine guarantees range; this is defense-in-depth.
        try:
            timeout_val = int(timeout_raw)
        except ValueError:
            timeout_val = 0
        if _HTTP_TIMEOUT_MIN_S <= timeout_val <= _HTTP_TIMEOUT_MAX_S:
            llm_block["http_read_timeout_s"] = timeout_val

    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump({"llm": llm_block}, fh, default_flow_style=False, allow_unicode=True)
        if sys.platform != "win32":
            os.chmod(config_path, 0o600)
    except OSError as exc:
        print(f"  ! failed to write {config_path}: {exc}")
        return

    print(f"  ✓ Configuration written to {config_path}")


def _run_generate_from_menu(
    io: MenuIO,
    *,
    anthropic_catalog: ModelCatalog,
    openai_catalog: ModelCatalog,
) -> None:
    """Generate-tutorial 5-section sub-wizard orchestrator (Step 7 — full flow).

    Sections:
      1. Repo + Output
      2. Provider + Models (express path skips §3-§4 when saved config used)
      3. File Filters (optional, default skip)
      4. Limits + Audience (optional, default skip)
      5. Summary + Launch / Cancel

    Each section returns a dict on success or ``None`` on user abort. Abort
    at any boundary returns to the main menu loop without launching the
    pipeline.
    """
    saved = _try_load_saved_config()

    s1 = _subwizard_repo_output(io)
    if s1 is None:
        return

    s2 = _subwizard_provider_models(
        io,
        saved=saved,
        anthropic_catalog=anthropic_catalog,
        openai_catalog=openai_catalog,
    )
    if s2 is None:
        return

    express = bool(s2.pop("_express", False))

    if express:
        s3: dict[str, Any] = {
            "exclude_patterns": list(saved.exclude_patterns) if saved is not None else [],
            "include_patterns": list(saved.include_patterns) if saved is not None else [],
        }
        s4: dict[str, Any] = {
            "llm_concurrency": saved.llm_concurrency if saved is not None else 10,
            "llm_max_retries": saved.llm_max_retries if saved is not None else 5,
            "llm_max_wait_s": saved.llm_max_wait_s if saved is not None else 60,
            "max_lessons": saved.max_lessons if saved is not None else 30,
            "target_audience": saved.target_audience if saved is not None else "mid",
        }
    else:
        filters = _subwizard_filters(
            io,
            saved_excludes=list(saved.exclude_patterns) if saved is not None else None,
            saved_includes=list(saved.include_patterns) if saved is not None else None,
        )
        if filters is None:
            return
        s3 = filters

        limits = _subwizard_limits(io, saved=saved)
        if limits is None:
            return
        s4 = limits

    payload: dict[str, Any] = {**s1, **s2, **s3, **s4}
    _subwizard_summary_and_launch(io, payload)


# ---------------------------------------------------------------------------
# Show config — view + per-field editor (Step 8 + post-launch UX request).
# Each field maps to a (yaml-path, prompt-fn) tuple so the dispatcher stays
# data-driven. Edits persist immediately to user_config_path() so the panel
# re-renders with the new value on the next loop iteration.
# ---------------------------------------------------------------------------


_EDIT_PROVIDER = "Provider"
_EDIT_PLAN = "Plan model"
_EDIT_NARRATE = "Narrate model"
_EDIT_API_KEY = "API key"
_EDIT_BASE_URL = "Base URL"
_EDIT_CONCURRENCY = "Concurrency"
_EDIT_RETRIES = "Max retries"
_EDIT_WAIT = "Max wait (s)"
_EDIT_LESSONS = "Max lessons"
_EDIT_AUDIENCE = "Audience"
_EDIT_EXCLUDES = "Exclude patterns"
_EDIT_INCLUDES = "Include patterns"
_EDIT_DONE = "[Done]"

_EDIT_CHOICES: list[str] = [
    _EDIT_PROVIDER,
    _EDIT_PLAN,
    _EDIT_NARRATE,
    _EDIT_API_KEY,
    _EDIT_BASE_URL,
    _EDIT_CONCURRENCY,
    _EDIT_RETRIES,
    _EDIT_WAIT,
    _EDIT_LESSONS,
    _EDIT_AUDIENCE,
    _EDIT_EXCLUDES,
    _EDIT_INCLUDES,
    _EDIT_DONE,
]


def _load_user_yaml() -> dict[str, Any]:
    """Load ``user_config_path()`` as a raw dict, or empty dict if missing."""
    import yaml

    path = user_config_path()
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(data) if isinstance(data, dict) else {}


def _save_user_yaml(data: dict[str, Any]) -> None:
    """Persist ``data`` to ``user_config_path()`` with chmod 0o600 on POSIX."""
    import os
    import sys

    import yaml

    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )
    if sys.platform != "win32":
        os.chmod(path, 0o600)


def _llm_block(data: dict[str, Any]) -> dict[str, Any]:
    """Get-or-create the ``llm:`` sub-block in the YAML dict."""
    block = data.setdefault("llm", {})
    return block if isinstance(block, dict) else data.setdefault("llm", {})


def _edit_provider(io: MenuIO, saved: WiedunflowConfig) -> str | None:
    return io.select("Provider:", choices=_PROVIDERS, default=saved.llm_provider)


def _edit_model(
    io: MenuIO,
    saved: WiedunflowConfig,
    *,
    label: str,
    current: str,
    anthropic_catalog: ModelCatalog,
    openai_catalog: ModelCatalog,
) -> str | None:
    """Use ModelCatalog picker for hosted providers; free text for OSS endpoints."""
    if saved.llm_provider == "anthropic":
        return _pick_hosted_model(io, catalog=anthropic_catalog, label=label)
    if saved.llm_provider == "openai":
        return _pick_hosted_model(io, catalog=openai_catalog, label=label)
    return io.text(label, default=current)


def _edit_audience(io: MenuIO, saved: WiedunflowConfig) -> str | None:
    return io.select("Target audience:", choices=_AUDIENCE_LEVELS, default=saved.target_audience)


def _apply_edit(
    field: str,
    new_value: Any,
    saved: WiedunflowConfig,
    raw_yaml: dict[str, Any],
) -> bool:
    """Mutate ``raw_yaml`` in place. Returns True on save, False on no-op (None value)."""
    if new_value is None:
        return False
    llm = _llm_block(raw_yaml)
    if field == _EDIT_PROVIDER:
        llm["provider"] = new_value
    elif field == _EDIT_PLAN:
        llm["model_plan"] = new_value
    elif field == _EDIT_NARRATE:
        llm["model_narrate"] = new_value
    elif field == _EDIT_API_KEY:
        llm["api_key"] = new_value
    elif field == _EDIT_BASE_URL:
        # Empty string clears the base_url to use the provider default.
        if isinstance(new_value, str) and new_value.strip() == "":
            llm.pop("base_url", None)
        else:
            llm["base_url"] = new_value
    elif field == _EDIT_CONCURRENCY:
        llm["concurrency"] = new_value
    elif field == _EDIT_RETRIES:
        llm["max_retries"] = new_value
    elif field == _EDIT_WAIT:
        llm["max_wait_s"] = new_value
    elif field == _EDIT_LESSONS:
        raw_yaml["max_lessons"] = new_value
    elif field == _EDIT_AUDIENCE:
        raw_yaml["target_audience"] = new_value
    elif field == _EDIT_EXCLUDES:
        raw_yaml["exclude_patterns"] = new_value
    elif field == _EDIT_INCLUDES:
        raw_yaml["include_patterns"] = new_value
    else:  # pragma: no cover — unknown field is a programming bug
        return False
    return True


def _render_config_panel(saved: WiedunflowConfig) -> None:
    """Render the read-only config panel (also used as the editor's header)."""
    from wiedunflow.cli.output import init_console, render_info_panel

    console = init_console()
    lines: list[tuple[str, str]] = [
        (_EDIT_PROVIDER, saved.llm_provider),
        (_EDIT_PLAN, saved.llm_model_plan),
        (_EDIT_NARRATE, saved.llm_model_narrate),
        (_EDIT_API_KEY, "(set)" if saved.llm_api_key is not None else "(env / unset)"),
        (_EDIT_BASE_URL, saved.llm_base_url or "(default)"),
        (_EDIT_CONCURRENCY, str(saved.llm_concurrency)),
        (_EDIT_RETRIES, str(saved.llm_max_retries)),
        (_EDIT_WAIT, str(saved.llm_max_wait_s)),
        (_EDIT_LESSONS, str(saved.max_lessons)),
        (_EDIT_AUDIENCE, saved.target_audience),
        (_EDIT_EXCLUDES, f"{len(saved.exclude_patterns)} pattern(s)"),
        (_EDIT_INCLUDES, f"{len(saved.include_patterns)} pattern(s)"),
        ("Output", str(saved.output_path) if saved.output_path else "./tutorial.html (default)"),
        ("Config path", str(user_config_path())),
    ]
    render_info_panel(console, title="CURRENT CONFIG", lines=lines)


def _run_config_from_menu(
    io: MenuIO,
    *,
    anthropic_catalog: ModelCatalog | None = None,
    openai_catalog: ModelCatalog | None = None,
) -> None:
    """View + edit (or initialize) the saved user config.

    Single entry point for everything config-related. If no saved config
    exists, prompts the user to run the init wizard. Once a config is
    present, renders the panel + per-field edit selector in a loop. Esc
    on the field selector or ``[Done]`` exits to the main menu; Esc on a
    per-field prompt cancels just that edit and re-renders the selector.
    """
    if anthropic_catalog is None:
        anthropic_catalog = CachedModelCatalog(AnthropicModelCatalog(), provider_name="anthropic")
    if openai_catalog is None:
        openai_catalog = CachedModelCatalog(OpenAIModelCatalog(), provider_name="openai")

    # Bootstrap path — no saved config yet → offer to run the init wizard.
    if not user_config_path().is_file():
        _redraw_chrome("Configuration")
        print("  No saved config found.")
        run_init = io.confirm("Initialize one now?", default=True)
        if not run_init:
            return
        _run_init_from_menu(io, anthropic_catalog=anthropic_catalog, openai_catalog=openai_catalog)
        if not user_config_path().is_file():
            return  # init was cancelled or failed

    while True:
        _redraw_chrome("Configuration")
        saved = _try_load_saved_config()
        if saved is None:
            # Defensive — config existed at start but failed to parse.
            print("  ! saved config could not be parsed.")
            _wait_for_return_to_menu(io)
            return

        _render_config_panel(saved)

        choice = io.select("Edit field (or Done):", choices=_EDIT_CHOICES)
        if choice is None or choice == _EDIT_DONE:
            return

        new_value: Any
        if choice == _EDIT_PROVIDER:
            new_value = _edit_provider(io, saved)
        elif choice == _EDIT_PLAN:
            new_value = _edit_model(
                io,
                saved,
                label="Planning model:",
                current=saved.llm_model_plan,
                anthropic_catalog=anthropic_catalog,
                openai_catalog=openai_catalog,
            )
        elif choice == _EDIT_NARRATE:
            new_value = _edit_model(
                io,
                saved,
                label="Narration model:",
                current=saved.llm_model_narrate,
                anthropic_catalog=anthropic_catalog,
                openai_catalog=openai_catalog,
            )
        elif choice == _EDIT_API_KEY:
            new_value = io.password("API key:")
        elif choice == _EDIT_BASE_URL:
            new_value = io.text(
                "Base URL (empty clears to default):",
                default=saved.llm_base_url or "",
            )
        elif choice == _EDIT_CONCURRENCY:
            new_value = _ask_int(io, "Concurrency:", default=saved.llm_concurrency, low=1, high=20)
        elif choice == _EDIT_RETRIES:
            new_value = _ask_int(io, "Max retries:", default=saved.llm_max_retries, low=1, high=10)
        elif choice == _EDIT_WAIT:
            new_value = _ask_int(
                io, "Max wait seconds:", default=saved.llm_max_wait_s, low=1, high=600
            )
        elif choice == _EDIT_LESSONS:
            new_value = _ask_int(io, "Max lessons:", default=saved.max_lessons, low=1, high=30)
        elif choice == _EDIT_AUDIENCE:
            new_value = _edit_audience(io, saved)
        elif choice == _EDIT_EXCLUDES:
            new_value = _list_manager(io, "Exclude patterns", list(saved.exclude_patterns))
        elif choice == _EDIT_INCLUDES:
            new_value = _list_manager(io, "Include patterns", list(saved.include_patterns))
        else:  # pragma: no cover — Done handled above
            new_value = None

        raw_yaml = _load_user_yaml()
        if _apply_edit(choice, new_value, saved, raw_yaml):
            _save_user_yaml(raw_yaml)
            print(f"  ✓ Updated {choice.lower()}.")
        else:
            print(f"  Edit of {choice.lower()} cancelled.")


def _run_estimate_from_menu(io: MenuIO) -> None:
    """Estimate cost for a repo without launching the pipeline (file-count heuristic)."""
    from wiedunflow.cli.output import init_console, render_info_panel

    _redraw_chrome("Estimate cost")
    raw = io.text("Repo path (paste or type):", default="")
    if raw is None:
        return
    error = _validate_repo_path(raw)
    if error is not None:
        print(f"  ! {error}")
        return

    repo_path = Path(raw).expanduser()
    saved = _try_load_saved_config()
    max_lessons = saved.max_lessons if saved is not None else 30
    plan_model = saved.llm_model_plan if saved is not None else None
    narrate_model = saved.llm_model_narrate if saved is not None else None
    provider = saved.llm_provider if saved is not None else "(no saved config)"
    pricing = _default_pricing_catalog()
    estimate_obj = _heuristic_estimate(
        repo_path,
        max_lessons=max_lessons,
        plan_model=plan_model,
        pricing_catalog=pricing,
    )

    from wiedunflow.cli.cost_estimator import blended_from_prices

    plan_prices = pricing.prices_per_mtok(plan_model) if plan_model else None
    narrate_prices = pricing.prices_per_mtok(narrate_model) if narrate_model else None
    plan_blended = blended_from_prices(plan_prices) if plan_prices is not None else None
    narrate_blended = blended_from_prices(narrate_prices) if narrate_prices is not None else None
    plan_label = plan_model or "(default)"
    narrate_label = narrate_model or "(default)"
    plan_price_str = (
        f"${plan_blended:.2f}/MTok" if plan_blended is not None else "(unknown — fallback)"
    )
    narrate_price_str = (
        f"${narrate_blended:.2f}/MTok" if narrate_blended is not None else "(unknown — fallback)"
    )

    console = init_console()
    # v0.10.0 — multi-agent narration breakdown (Planning + Orchestrator + Researcher
    # + Writer + Reviewer). The legacy ``llm_model_narrate`` config field maps onto
    # the Writer role (primary narration model in the multi-agent pipeline) and is
    # used as the representative ``narrate_label`` for the panel header row.
    planning_total = estimate_obj.planning.input_tokens + estimate_obj.planning.output_tokens
    orchestrator_total = (
        estimate_obj.orchestrator.input_tokens + estimate_obj.orchestrator.output_tokens
    )
    researcher_total = estimate_obj.researcher.input_tokens + estimate_obj.researcher.output_tokens
    writer_total = estimate_obj.writer.input_tokens + estimate_obj.writer.output_tokens
    reviewer_total = estimate_obj.reviewer.input_tokens + estimate_obj.reviewer.output_tokens
    lines = [
        ("Provider", provider),
        ("Plan model", f"{plan_label} · {plan_price_str}"),
        ("Writer model", f"{narrate_label} · {narrate_price_str}"),
        ("Files (.py)", str(_count_python_files(repo_path))),
        ("Estimated symbols", str(estimate_obj.symbols)),
        ("Estimated lessons", str(estimate_obj.lessons)),
        ("Planning tokens", f"~{planning_total:,}"),
        ("Planning cost", f"${estimate_obj.planning.cost_usd:.2f}"),
        ("Orchestrator tokens", f"~{orchestrator_total:,}"),
        ("Orchestrator cost", f"${estimate_obj.orchestrator.cost_usd:.2f}"),
        ("Researcher tokens", f"~{researcher_total:,}"),
        ("Researcher cost", f"${estimate_obj.researcher.cost_usd:.2f}"),
        ("Writer tokens", f"~{writer_total:,}"),
        ("Writer cost", f"${estimate_obj.writer.cost_usd:.2f}"),
        ("Reviewer tokens", f"~{reviewer_total:,}"),
        ("Reviewer cost", f"${estimate_obj.reviewer.cost_usd:.2f}"),
        ("TOTAL cost", f"${estimate_obj.total_cost_usd:.2f}"),
        (
            "Runtime",
            f"{estimate_obj.runtime_min_minutes}-{estimate_obj.runtime_max_minutes} min",
        ),
    ]
    render_info_panel(console, title="COST ESTIMATE (LiteLLM-priced)", lines=lines)
    _wait_for_return_to_menu(io)


def _run_resume_from_menu(io: MenuIO) -> None:
    """Resume an interrupted run by replaying the cached checkpoint."""
    from wiedunflow.adapters.sqlite_cache import SQLiteCache

    _redraw_chrome("Resume last run")
    raw = io.text("Repo path of the run to resume:", default="")
    if raw is None:
        return
    error = _validate_repo_path(raw)
    if error is not None:
        print(f"  ! {error}")
        return

    repo_path = Path(raw).expanduser()
    cache = SQLiteCache()
    if not cache.has_checkpoint(repo_path):
        print(f"  No checkpoint found for {repo_path} · nothing to resume.")
        return

    saved = _try_load_saved_config()
    if saved is None:
        print("  ! no saved config found — run 'Initialize config' first.")
        return

    payload: dict[str, Any] = {
        "repo_path": repo_path,
        "output_path": None,
        "llm_provider": saved.llm_provider,
        "llm_model_plan": saved.llm_model_plan,
        "llm_model_narrate": saved.llm_model_narrate,
        "llm_api_key": (
            saved.llm_api_key.get_secret_value() if saved.llm_api_key is not None else None
        ),
        "llm_base_url": saved.llm_base_url,
        "llm_concurrency": saved.llm_concurrency,
        "llm_max_retries": saved.llm_max_retries,
        "llm_max_wait_s": saved.llm_max_wait_s,
        "max_lessons": saved.max_lessons,
        "target_audience": saved.target_audience,
        "exclude_patterns": list(saved.exclude_patterns),
        "include_patterns": list(saved.include_patterns),
    }
    print("  Resuming with saved config + cached checkpoints…")
    _launch_pipeline(payload)


def _wait_for_return_to_menu(io: MenuIO) -> None:
    """Pause until the user acknowledges, so panels stay readable.

    Without this pause the menu loop's redraw fires immediately after the
    helper returns and wipes the panel before the user can read it.

    After a real LLM pipeline run the prompt_toolkit terminal state can be
    in a degraded shape (rich.Live left it in "alternate screen" mode on
    some Windows terminals), which makes ``questionary.text`` raise. Fall
    back to the stdlib ``input()`` in that case so the user always gets
    a chance to read the result before the menu redraws.
    """
    print()
    try:
        io.text("(Press Enter to return to menu)", default="")
    except (KeyboardInterrupt, EOFError):
        return
    except Exception:
        try:
            input("(Press Enter to return to menu) ")
        except (KeyboardInterrupt, EOFError):
            return


# ---------------------------------------------------------------------------
# Recent runs — JSON-backed history of past pipeline launches.
# Stored as a small list of dicts in ``~/.cache/wiedunflow/recent-runs.json``.
# Each entry: timestamp, repo_path, output_path, provider, models, exit_code.
# ---------------------------------------------------------------------------


_RECENT_RUNS_FILE = "recent-runs.json"
_RECENT_RUNS_MAX = 20


def _recent_runs_path() -> Path:
    """Return the path to the recent-runs JSON history file."""
    import platformdirs

    return Path(platformdirs.user_cache_dir("wiedunflow")) / _RECENT_RUNS_FILE


def _load_recent_runs() -> list[dict[str, Any]]:
    """Load the recent-runs list, newest first. Empty list on any read error."""
    import json

    path = _recent_runs_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def _save_recent_runs(runs: list[dict[str, Any]]) -> None:
    import json

    path = _recent_runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runs[:_RECENT_RUNS_MAX], indent=2), encoding="utf-8")


def _append_to_recent_runs(payload: dict[str, Any], *, exit_code: int) -> None:
    """Prepend a new entry to the recent-runs file (de-duplicated by repo+timestamp)."""
    from datetime import UTC, datetime

    entry = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "repo_path": str(payload.get("repo_path", "")),
        "output_path": (
            str(payload["output_path"]) if payload.get("output_path") else "./tutorial.html"
        ),
        "provider": payload.get("llm_provider", ""),
        "model_plan": payload.get("llm_model_plan", ""),
        "model_narrate": payload.get("llm_model_narrate", ""),
        "exit_code": int(exit_code),
        "status": "success" if exit_code == 0 else f"failed ({exit_code})",
    }
    runs = _load_recent_runs()
    runs.insert(0, entry)
    _save_recent_runs(runs)


def _format_recent_choice(entry: dict[str, Any]) -> str:
    """One-line label for the recent-runs picker."""
    ts = str(entry.get("timestamp", "?"))[:19].replace("T", " ")
    repo = str(entry.get("repo_path", "?"))
    status = str(entry.get("status", "?"))
    return f"{ts}  {status:<14}  {repo}"


_RECENT_CLEAR = "[Clear history]"
_RECENT_DONE = "[Done]"

# Picker source labels for _subwizard_pick_repo.
_PICKER_SOURCE_RECENT = "Recent runs"
_PICKER_SOURCE_DISCOVER = "Discover in cwd"
_PICKER_SOURCE_MANUAL = "Type path manually"
_PICKER_BACK = "Back"


def _run_recent_from_menu(io: MenuIO) -> None:
    """Show recent pipeline runs; selection re-renders the entry's details."""
    from wiedunflow.cli.output import init_console, render_info_panel

    while True:
        _redraw_chrome("Recent runs")
        runs = _load_recent_runs()
        if not runs:
            print("  No recent runs yet · launch a Generate first.")
            _wait_for_return_to_menu(io)
            return

        choices = [_format_recent_choice(entry) for entry in runs]
        choices.append(_RECENT_CLEAR)
        choices.append(_RECENT_DONE)

        pick = io.select("Select a run for details:", choices=choices)
        if pick is None or pick == _RECENT_DONE:
            return
        if pick == _RECENT_CLEAR:
            confirmed = io.confirm("Clear all recent-runs history?", default=False)
            if confirmed:
                _save_recent_runs([])
            continue

        # Find the chosen entry by index and render its details.
        idx = choices.index(pick)
        if idx >= len(runs):
            continue
        entry = runs[idx]
        console = init_console()
        lines = [
            ("Timestamp", str(entry.get("timestamp", "?"))),
            ("Repo path", str(entry.get("repo_path", "?"))),
            ("Output path", str(entry.get("output_path", "?"))),
            ("Provider", str(entry.get("provider", "?"))),
            ("Plan model", str(entry.get("model_plan", "?"))),
            ("Narrate model", str(entry.get("model_narrate", "?"))),
            ("Status", str(entry.get("status", "?"))),
            ("Exit code", str(entry.get("exit_code", "?"))),
        ]
        render_info_panel(console, title="RECENT RUN · DETAILS", lines=lines)
        out_path = entry.get("output_path", "")
        if out_path:
            try:
                from wiedunflow.cli.output import osc8_hyperlink as _osc8

                console.print(
                    f"  open  [link={Path(out_path).resolve().as_uri()}]{out_path}[/link]"
                )
                _ = _osc8  # silence unused-import linter — import gated for OSC8 fallback parity
            except Exception:
                print(f"  open  {out_path}")
        _wait_for_return_to_menu(io)


def _run_help_from_menu(io: MenuIO) -> None:
    """Render a quick-reference help panel covering the 7 menu items."""
    from wiedunflow.cli.output import init_console, render_info_panel

    _redraw_chrome("Help")
    console = init_console()
    lines = [
        ("Generate tutorial", "5-section sub-wizard → 7-stage pipeline → tutorial.html"),
        ("Recent runs", "Re-open a previous run's tutorial.html (history of last 20)"),
        ("Configuration", "Initialize or edit ~/.config/wiedunflow/config.yaml"),
        ("Estimate cost", "File-count heuristic estimate before launching"),
        ("Resume last run", "Re-launch with cached checkpoints (if any)"),
        ("Help", "This panel"),
        ("Exit", "Esc + confirm"),
    ]
    render_info_panel(console, title="WIEDUNFLOW MENU · QUICK REFERENCE", lines=lines)
    print()
    print("  Tip: invoke `wiedunflow generate <repo>` for one-shot CLI mode (CI-friendly).")
    print("       Set WIEDUNFLOW_NO_MENU=1 to disable this menu globally.")
    print("       Set WIEDUNFLOW_NO_CLEAR=1 if your terminal mangles the screen-clear escapes.")
    _wait_for_return_to_menu(io)


# ---------------------------------------------------------------------------
# Generate sub-wizard sections — §1 (Repo+Output) and §2 (Provider+Models).
# §3 (filters) lands in Step 6; §4 (limits+audience) and §5 (summary+launch)
# land in Step 7. The orchestrator (`_run_generate_from_menu`) glues them
# together and is the only function that knows the section order.
# ---------------------------------------------------------------------------


# Provider enum mirrors `WiedunflowConfig.llm_provider` Literal exactly.
_PROVIDERS: list[str] = ["anthropic", "openai", "openai_compatible", "custom"]

# Providers whose plan/narrate model can be picked from a dynamic catalog.
# openai_compatible/custom take free-text model names because the endpoint
# may host any model id (Ollama llama3, vLLM internal names, etc.).
_HOSTED_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai"})


def _try_load_saved_config() -> WiedunflowConfig | None:
    """Load the user's saved ``~/.config/wiedunflow/config.yaml`` if present.

    Used to power the §2 express path ("Use saved config? Y/n"). Failures
    (missing file, invalid YAML, validation error) silently return ``None``
    so the wizard falls through to the full provider/model flow.
    """
    if not user_config_path().is_file():
        return None
    try:
        return load_config()
    except Exception:
        return None


def _validate_repo_path(raw: str) -> str | None:
    """Return ``None`` if the path is a valid Git repo, else an error string."""
    if not raw:
        return "path is required"
    candidate = Path(raw).expanduser()
    if not candidate.exists():
        return f"path {str(candidate)!r} does not exist"
    if not candidate.is_dir():
        return f"{str(candidate)!r} is not a directory"
    git_marker = candidate / ".git"
    if not git_marker.exists():
        return f"no .git found in {str(candidate)!r} (is this a git repo?)"
    return None


def _subwizard_pick_repo(io: MenuIO, *, cwd: Path | None = None) -> Path | None:
    """Interactive 3-source repo picker for §1 of the Generate sub-wizard.

    Presents a top-level source selector ("Recent runs", "Discover in cwd",
    "Type path manually", "Back") and drills into the chosen branch.  Each
    branch has its own "Back" option to return to the source selector.

    Returns the selected ``Path`` (not yet validated as a git repo — that
    happens in ``_subwizard_repo_output`` via ``_validate_repo_path``), or
    ``None`` when the user aborts at any level (Esc or "Back" on the
    top-level selector).

    Args:
        io: The ``MenuIO`` implementation driving the prompts.
        cwd: Directory used for git-repo discovery (defaults to
            ``Path.cwd()`` when ``None``).
    """
    from datetime import datetime

    effective_cwd = cwd if cwd is not None else Path.cwd()

    source_choices = [
        _PICKER_SOURCE_RECENT,
        _PICKER_SOURCE_DISCOVER,
        _PICKER_SOURCE_MANUAL,
        _PICKER_BACK,
    ]

    while True:
        source = io.select("How do you want to provide the repo?", source_choices)
        if source is None or source == _PICKER_BACK:
            return None

        # ------------------------------------------------------------------ #
        # Branch A — Recent runs
        # ------------------------------------------------------------------ #
        if source == _PICKER_SOURCE_RECENT:
            entries = load_recent_runs(limit=10)
            if not entries:
                print("  No recent runs found. Choose another source.")
                continue
            choices = [*[str(p) for p in entries], _PICKER_BACK]
            pick = io.select("Recent runs:", choices)
            if pick is None:
                return None
            if pick == _PICKER_BACK:
                continue
            return Path(pick)

        # ------------------------------------------------------------------ #
        # Branch B — Discover in cwd
        # ------------------------------------------------------------------ #
        if source == _PICKER_SOURCE_DISCOVER:
            repos = discover_git_repos(effective_cwd)
            if not repos:
                print(f"  No git repos found in {effective_cwd}. Choose another source.")
                continue

            def _repo_label(p: Path) -> str:
                try:
                    mtime = (p / ".git" / "HEAD").stat().st_mtime
                    date_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
                except OSError:
                    date_str = "????-??-??"
                return f"[{date_str}] {p}"

            labels = [_repo_label(r) for r in repos]
            choices_discover = [*labels, _PICKER_BACK]
            pick_label = io.select(f"Git repos in {effective_cwd}:", choices_discover)
            if pick_label is None:
                return None
            if pick_label == _PICKER_BACK:
                continue
            # Recover the path by stripping the "[YYYY-MM-DD] " prefix.
            # Format is "[DATE] /absolute/path" — split on "] " once.
            _, _, path_part = pick_label.partition("] ")
            return Path(path_part)

        # ------------------------------------------------------------------ #
        # Branch C — Type path manually
        # ------------------------------------------------------------------ #
        if source == _PICKER_SOURCE_MANUAL:
            path_str = io.path("Repo path:", only_directories=True)
            if path_str is None:
                return None
            if not path_str.strip():
                print("  Path cannot be empty. Try again.")
                continue
            return Path(path_str)

        # Unreachable — all choices handled above.
        return None  # pragma: no cover


def _subwizard_repo_output(io: MenuIO) -> dict[str, Any] | None:
    """§1 — collect repo path and optional output path. Returns dict or None.

    Delegates repo selection to ``_subwizard_pick_repo`` which presents a
    3-source picker (recent runs / discover / manual).  ``_validate_repo_path``
    then guards against stale or non-git selections before proceeding to the
    output-path prompt.
    """
    _redraw_chrome("Generate · Section 1/5 · Repo & Output")

    while True:
        picked = _subwizard_pick_repo(io)
        if picked is None:
            return None  # Esc / Back → abort wizard
        repo_raw = str(picked)
        error = _validate_repo_path(repo_raw)
        if error is None:
            break
        print(f"  ! {error}")

    repo_path = Path(repo_raw).expanduser()
    default_label = f"<repo>/wiedunflow-{repo_path.name}.html"
    output_raw = io.text(
        f"Output path (Enter for default: {default_label}):",
        default="",
    )
    if output_raw is None:
        return None
    # Leave normalization (cwd resolution + missing-extension fix) to
    # _resolve_output_path so CLI and menu paths share a single contract.
    output_path: Path | None = Path(output_raw).expanduser() if output_raw.strip() else None

    return {
        "repo_path": repo_path,
        "output_path": output_path,
    }


def _format_saved_summary(saved: WiedunflowConfig) -> str:
    """One-line summary of the saved config used in the express-path prompt."""
    return (
        f"{saved.llm_provider} / {saved.llm_model_plan} (plan) + "
        f"{saved.llm_model_narrate} (narrate)"
    )


def _saved_section_payload(saved: WiedunflowConfig) -> dict[str, Any]:
    """Materialize §2 fields from a ``WiedunflowConfig`` for the express path."""
    return {
        "llm_provider": saved.llm_provider,
        "llm_model_plan": saved.llm_model_plan,
        "llm_model_narrate": saved.llm_model_narrate,
        "llm_api_key": (
            saved.llm_api_key.get_secret_value() if saved.llm_api_key is not None else None
        ),
        "llm_base_url": saved.llm_base_url,
        "_express": True,
    }


def _pick_hosted_model(io: MenuIO, *, catalog: ModelCatalog, label: str) -> str | None:
    """Render a model picker with a sentinel ``[r] Refresh now`` option."""
    refresh_choice = "[r] Refresh now (re-fetch from provider API)"
    while True:
        models = catalog.list_models()
        choices = [*models, refresh_choice]
        picked = io.select(label, choices=choices)
        if picked is None:
            return None
        if picked == refresh_choice:
            # Bypass the cache when the catalog supports it; fall through to
            # the next iteration so the caller sees the refreshed list.
            refresh = getattr(catalog, "refresh", None)
            if callable(refresh):
                refresh()
            continue
        return picked


def _subwizard_provider_models(
    io: MenuIO,
    *,
    saved: WiedunflowConfig | None,
    anthropic_catalog: ModelCatalog,
    openai_catalog: ModelCatalog,
) -> dict[str, Any] | None:
    """§2 — collect provider + plan/narrate models + key + base URL.

    When a saved config exists, prompts the express path: "Use saved config?
    (Y/n)". Yes returns the saved values plus ``_express: True`` so the
    orchestrator skips §3 and §4. No falls through to the full form.
    """
    _redraw_chrome("Generate · Section 2/5 · Provider & Models")

    if saved is not None:
        print(f"  Saved config detected: {_format_saved_summary(saved)}")
        use_saved = io.confirm("Use saved provider settings?", default=True)
        if use_saved is None:
            return None
        if use_saved:
            return _saved_section_payload(saved)

    provider = io.select(
        "Provider:",
        choices=_PROVIDERS,
        default=(saved.llm_provider if saved is not None else "anthropic"),
    )
    if provider is None:
        return None

    if provider in _HOSTED_PROVIDERS:
        catalog = anthropic_catalog if provider == "anthropic" else openai_catalog
        model_plan = _pick_hosted_model(io, catalog=catalog, label="Planning model:")
        if model_plan is None:
            return None
        model_narrate = _pick_hosted_model(io, catalog=catalog, label="Narration model:")
        if model_narrate is None:
            return None
    else:
        # openai_compatible / custom — free text, endpoint may use any id.
        plan_default = saved.llm_model_plan if saved is not None else ""
        narrate_default = saved.llm_model_narrate if saved is not None else ""
        text_plan = io.text("Planning model id:", default=plan_default)
        if text_plan is None:
            return None
        text_narrate = io.text("Narration model id:", default=narrate_default)
        if text_narrate is None:
            return None
        model_plan = text_plan
        model_narrate = text_narrate

    # API key — skip when the appropriate env var is already set.
    env_var = _provider_key_env_var(provider)
    if env_var is not None and os.environ.get(env_var):
        api_key: str | None = None
        print(f"  ✓ API key: from {env_var}")
    elif provider == "custom":
        api_key = io.text(
            "API key (leave empty if endpoint needs no auth):",
            default="",
        )
        if api_key is None:
            return None
        api_key = api_key or None
    else:
        api_key = io.password("API key:")
        if api_key is None:
            return None

    # Base URL — required for openai_compatible / custom; hidden otherwise.
    base_url: str | None = None
    if provider in ("openai_compatible", "custom"):
        url_default = (saved.llm_base_url if saved is not None else "") or ""
        while True:
            url = io.text(
                "Base URL (e.g. http://localhost:11434/v1):",
                default=url_default,
            )
            if url is None:
                return None
            if url and (url.startswith("http://") or url.startswith("https://")):
                base_url = url
                break
            print("  ! base URL must start with http:// or https://")

    return {
        "llm_provider": provider,
        "llm_model_plan": model_plan,
        "llm_model_narrate": model_narrate,
        "llm_api_key": api_key,
        "llm_base_url": base_url,
    }


def _provider_key_env_var(provider: str) -> str | None:
    """Return the env var name conventionally used for a provider's API key."""
    if provider == "anthropic":
        return "ANTHROPIC_API_KEY"
    if provider in ("openai", "openai_compatible"):
        return "OPENAI_API_KEY"
    return None  # custom uses llm_api_key_env from YAML, not a fixed name


# ---------------------------------------------------------------------------
# §3 — File Filters (Step 6). Dynamic list manager for exclude/include globs.
# questionary has no native list-editor widget, so this is a select-driven
# state machine: empty → [Add | Done]; with items → [Add | Edit | Remove | Done].
# ---------------------------------------------------------------------------


_LIST_ADD = "[+ Add pattern]"
_LIST_EDIT = "[~ Edit existing]"
_LIST_REMOVE = "[x Remove existing]"
_LIST_DONE = "[✓ Done]"


def _validate_pattern(raw: str) -> str | None:
    """Return ``None`` for valid patterns, an error string otherwise."""
    if not raw or not raw.strip():
        return "pattern cannot be empty"
    if "\x00" in raw:
        return "pattern contains a null byte"
    if "../" in raw or raw.startswith(".."):
        return "patterns cannot traverse parent directories"
    return None


def _format_items_summary(label: str, items: list[str]) -> None:
    """Pretty-print the current list for context above the action picker."""
    if not items:
        print(f"  {label} · (no patterns yet)")
        return
    print(f"  {label} · {len(items)} item{'s' if len(items) != 1 else ''}")
    for idx, item in enumerate(items, start=1):
        print(f"    [{idx}] {item}")


def _list_manager_add(io: MenuIO, items: list[str]) -> bool:
    """Prompt for a new pattern and append on success. Returns False on abort."""
    while True:
        raw = io.text("New pattern (e.g. tests/**, *.pyc):", default="")
        if raw is None:
            return False
        error = _validate_pattern(raw)
        if error is None:
            items.append(raw.strip())
            return True
        print(f"  ! {error}")


def _list_manager_edit(io: MenuIO, items: list[str]) -> bool:
    """Pick an item, re-prompt with prefill, replace at same index. Abort = False."""
    if not items:
        return True
    pick = io.select("Edit which pattern?", choices=items)
    if pick is None:
        return False
    idx = items.index(pick)
    while True:
        raw = io.text("Edit pattern:", default=pick)
        if raw is None:
            return False
        error = _validate_pattern(raw)
        if error is None:
            items[idx] = raw.strip()
            return True
        print(f"  ! {error}")


def _list_manager_remove(io: MenuIO, items: list[str]) -> bool:
    """Pick an item, confirm, delete. Abort = False."""
    if not items:
        return True
    pick = io.select("Remove which pattern?", choices=items)
    if pick is None:
        return False
    confirmed = io.confirm(f"Remove {pick!r}?", default=False)
    if confirmed is None:
        return False
    if confirmed:
        items.remove(pick)
    return True


def _list_manager(io: MenuIO, label: str, initial: list[str]) -> list[str] | None:
    """Run the add/edit/remove/done loop. Returns final list, or ``None`` on Esc.

    Esc from the action picker triggers a discard-confirm prompt: Yes restores
    the original list and exits the loop; No keeps the in-progress edits.
    """
    items = list(initial)
    original = list(initial)

    while True:
        _format_items_summary(label, items)
        if items:
            choices = [_LIST_ADD, _LIST_EDIT, _LIST_REMOVE, _LIST_DONE]
        else:
            choices = [_LIST_ADD, _LIST_DONE]

        choice = io.select("Action:", choices=choices)

        if choice is None:
            # Esc — confirm discard if there are pending changes; otherwise exit.
            if items == original:
                return None
            discard = io.confirm(f"Discard changes to {label}?", default=False)
            if discard is None or discard is True:
                return None  # signal abort with original-on-disk values
            continue

        if choice == _LIST_DONE:
            return items
        if choice == _LIST_ADD:
            if not _list_manager_add(io, items):
                return None
        elif choice == _LIST_EDIT:
            if not _list_manager_edit(io, items):
                return None
        elif choice == _LIST_REMOVE:
            if not _list_manager_remove(io, items):
                return None


# ---------------------------------------------------------------------------
# §4 — Limits & Audience (Step 7).
# Five fields with sensible defaults; opening prompt makes this whole section
# skippable. ``target_audience`` is the only field with strong product impact;
# the rest are tuning knobs.
# ---------------------------------------------------------------------------


_AUDIENCE_LEVELS: list[str] = ["noob", "junior", "mid", "senior", "expert"]


def _validate_int_in_range(raw: str, low: int, high: int) -> tuple[int | None, str | None]:
    """Parse ``raw`` as int and validate against ``[low, high]``."""
    try:
        value = int(raw)
    except ValueError:
        return None, f"enter a whole number between {low} and {high}"
    if value < low or value > high:
        return None, f"value must be between {low} and {high}"
    return value, None


def _ask_int(io: MenuIO, label: str, *, default: int, low: int, high: int) -> int | None:
    """Prompt for an int with retry-on-invalid. ``None`` on abort."""
    while True:
        raw = io.text(label, default=str(default))
        if raw is None:
            return None
        value, error = _validate_int_in_range(raw, low, high)
        if value is not None:
            return value
        print(f"  ! {error}")


def _subwizard_limits(
    io: MenuIO,
    *,
    saved: WiedunflowConfig | None = None,
) -> dict[str, Any] | None:
    """§4 — collect concurrency/retries/wait/max_lessons/audience.

    Opening prompt is "Customize limits and audience? (y/N)" default N — most
    users skip and use defaults. The ``(currently: <audience>)`` hint reminds
    that audience is the most impactful field in this section.
    """
    _redraw_chrome("Generate · Section 4/5 · Limits & Audience (optional)")

    current_audience = saved.target_audience if saved is not None else "mid"
    default_concurrency = saved.llm_concurrency if saved is not None else 10
    default_retries = saved.llm_max_retries if saved is not None else 5
    default_wait = saved.llm_max_wait_s if saved is not None else 60
    default_lessons = saved.max_lessons if saved is not None else 30

    print(
        f"  Defaults: concurrency={default_concurrency}, retries={default_retries}, "
        f"wait={default_wait}s,"
    )
    print(f"            max_lessons={default_lessons}, audience={current_audience}")

    customize = io.confirm(
        f"Customize limits and audience? (currently: {current_audience})",
        default=False,
    )
    if customize is None:
        return None
    if not customize:
        return {
            "llm_concurrency": default_concurrency,
            "llm_max_retries": default_retries,
            "llm_max_wait_s": default_wait,
            "max_lessons": default_lessons,
            "target_audience": current_audience,
        }

    audience = io.select(
        "Target audience:",
        choices=_AUDIENCE_LEVELS,
        default=current_audience,
    )
    if audience is None:
        return None

    max_lessons = _ask_int(io, "Max lessons:", default=default_lessons, low=1, high=30)
    if max_lessons is None:
        return None

    concurrency = _ask_int(io, "Concurrency:", default=default_concurrency, low=1, high=20)
    if concurrency is None:
        return None

    retries = _ask_int(io, "Max retries:", default=default_retries, low=1, high=10)
    if retries is None:
        return None

    wait_s = _ask_int(io, "Max wait seconds:", default=default_wait, low=1, high=600)
    if wait_s is None:
        return None

    return {
        "llm_concurrency": concurrency,
        "llm_max_retries": retries,
        "llm_max_wait_s": wait_s,
        "max_lessons": max_lessons,
        "target_audience": audience,
    }


# ---------------------------------------------------------------------------
# §5 — Summary & Launch (Step 7).
# Pretty-print all collected fields, run a file-count cost heuristic, then
# offer Launch / Cancel. Edit-section jumpback is a v0.4 follow-up.
# ---------------------------------------------------------------------------


def _count_python_files(repo_path: Path) -> int:
    """Best-effort count of .py files in the repo for the cost heuristic."""
    try:
        return sum(1 for _ in repo_path.rglob("*.py"))
    except OSError:
        return 0


def _default_pricing_catalog() -> Any:
    """Build the production pricing chain: LiteLLM (cached 24h) → static fallback.

    Lazily instantiated so unit tests that don't need pricing avoid the
    LiteLLM HTTP call (the chain still works offline because every layer
    short-circuits cleanly to ``None``).
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


def _heuristic_estimate(
    repo_path: Path,
    max_lessons: int,
    *,
    plan_model: str | None = None,
    orchestrator_model: str | None = None,
    researcher_model: str | None = None,
    writer_model: str | None = None,
    reviewer_model: str | None = None,
    pricing_catalog: Any | None = None,
) -> Any:
    """Build a ``CostEstimate`` from a file-count heuristic (no LLM calls).

    Conservative: assume 5 symbols per Python file, lessons = min(file_count,
    max_lessons), clusters = max(1, lessons / 5). The exact estimate fires
    inside ``_run_pipeline`` after stages 1-2; this one only powers §5 review.

    Per-model pricing is resolved via the injected ``pricing_catalog`` (live
    LiteLLM JSON, 24h cache, with ``StaticPricingCatalog`` fallback) — falls
    back to the hardcoded ``cost_estimator.MODEL_PRICES`` map when the
    catalog returns ``None`` for a model id.
    """
    from wiedunflow.cli.cost_estimator import estimate

    if pricing_catalog is None:
        pricing_catalog = _default_pricing_catalog()

    file_count = _count_python_files(repo_path)
    symbols = max(1, file_count * 5)
    lessons = min(max(file_count, 1), max_lessons)
    clusters = max(1, lessons // 5)
    return estimate(
        symbols=symbols,
        lessons=lessons,
        clusters=clusters,
        plan_model=plan_model,
        orchestrator_model=orchestrator_model,
        researcher_model=researcher_model,
        writer_model=writer_model,
        reviewer_model=reviewer_model,
        pricing_catalog=pricing_catalog,
    )


def _format_summary_lines(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Convert the collected payload into key/value rows for the summary panel."""
    output_label = (
        str(payload["output_path"]) if payload.get("output_path") else "./tutorial.html (default)"
    )
    excludes = payload.get("exclude_patterns") or []
    includes = payload.get("include_patterns") or []
    return [
        ("Repo", str(payload["repo_path"])),
        ("Output", output_label),
        ("Provider", payload["llm_provider"]),
        ("Plan model", payload["llm_model_plan"]),
        ("Narrate model", payload["llm_model_narrate"]),
        ("Audience", payload["target_audience"]),
        ("Max lessons", str(payload["max_lessons"])),
        ("Concurrency", str(payload["llm_concurrency"])),
        ("Excludes", f"{len(excludes)} pattern(s)" if excludes else "(none)"),
        ("Includes", f"{len(includes)} pattern(s)" if includes else "(none)"),
    ]


def _format_cost_lines(
    estimate_obj: Any,
    *,
    plan_model: str = "gpt-5.4",
    orchestrator_model: str = "gpt-5.4",
    researcher_model: str = "gpt-5.4-mini",
    writer_model: str = "gpt-5.4",
    reviewer_model: str = "gpt-5.4-mini",
) -> tuple[list[tuple[str, str]], tuple[str, str]]:
    """Return (per-role rows, total row) for the summary cost section.

    Model labels are the actual configured model ids so the panel matches
    the user's reality (e.g. ``gpt-5.4`` for OpenAI defaults). Displays
    all five multi-agent pipeline roles (ADR-0016).
    """
    planning = estimate_obj.planning
    orchestrator = estimate_obj.orchestrator
    researcher = estimate_obj.researcher
    writer = estimate_obj.writer
    reviewer = estimate_obj.reviewer
    rows = [
        (
            plan_model,
            f"~{planning.input_tokens + planning.output_tokens:,} tokens · ${planning.cost_usd:.2f}",
        ),
        (
            orchestrator_model,
            f"~{orchestrator.input_tokens + orchestrator.output_tokens:,} tokens · ${orchestrator.cost_usd:.2f}",
        ),
        (
            researcher_model,
            f"~{researcher.input_tokens + researcher.output_tokens:,} tokens · ${researcher.cost_usd:.2f}",
        ),
        (
            writer_model,
            f"~{writer.input_tokens + writer.output_tokens:,} tokens · ${writer.cost_usd:.2f}",
        ),
        (
            reviewer_model,
            f"~{reviewer.input_tokens + reviewer.output_tokens:,} tokens · ${reviewer.cost_usd:.2f}",
        ),
    ]
    total = (
        "TOTAL",
        f"~{estimate_obj.total_tokens:,} tokens · ${estimate_obj.total_cost_usd:.2f}",
    )
    return rows, total


_SUMMARY_LAUNCH = "Launch pipeline"
_SUMMARY_CANCEL = "Cancel"


def _subwizard_summary_and_launch(io: MenuIO, payload: dict[str, Any]) -> None:
    """§5 — render summary + estimated cost, then Launch or Cancel.

    Hands off to ``_launch_pipeline`` on Launch; prints "Generation cancelled"
    and returns to the menu on Cancel/Esc. Edit-section jumpback is intentionally
    omitted from MVP (planned for v0.4 — see ADR-0013 follow-up notes).
    """
    _redraw_chrome("Generate · Section 5/5 · Review & Launch")

    from wiedunflow.cli.output import init_console, render_generate_summary

    console = init_console()
    _llm_models_payload: dict[str, str] = payload.get("llm_models") or {}
    estimate_obj = _heuristic_estimate(
        payload["repo_path"],
        payload["max_lessons"],
        plan_model=payload.get("llm_model_plan"),
        orchestrator_model=_llm_models_payload.get("orchestrator"),
        researcher_model=_llm_models_payload.get("researcher"),
        writer_model=_llm_models_payload.get("writer"),
        reviewer_model=_llm_models_payload.get("reviewer"),
    )
    cost_rows, cost_total = _format_cost_lines(
        estimate_obj,
        plan_model=str(payload.get("llm_model_plan") or "gpt-5.4"),
        orchestrator_model=str(_llm_models_payload.get("orchestrator") or "gpt-5.4"),
        researcher_model=str(_llm_models_payload.get("researcher") or "gpt-5.4-mini"),
        writer_model=str(_llm_models_payload.get("writer") or "gpt-5.4"),
        reviewer_model=str(_llm_models_payload.get("reviewer") or "gpt-5.4-mini"),
    )

    render_generate_summary(
        console,
        config_lines=_format_summary_lines(payload),
        cost_lines=cost_rows,
        cost_total=cost_total,
        runtime_minutes=(estimate_obj.runtime_min_minutes, estimate_obj.runtime_max_minutes),
        lessons_estimate=estimate_obj.lessons,
    )

    action = io.select("Action:", choices=[_SUMMARY_LAUNCH, _SUMMARY_CANCEL])
    if action is None or action == _SUMMARY_CANCEL:
        print("  Generation cancelled · no API calls were made.")
        return

    _launch_pipeline(payload)
    # Pipeline complete — keep the run report (✓ success / open file://...)
    # visible until the user acknowledges, otherwise the main menu loop's
    # redraw wipes it instantly and looks like the app crashed.
    _wait_for_return_to_menu(io)


def _launch_pipeline(payload: dict[str, Any]) -> None:
    """Build providers from ``payload`` and run the existing CLI pipeline.

    Reuses ``_build_llm_provider`` and ``_run_pipeline`` from ``cli.main`` so
    the 7-stage Rich-Live experience is identical to ``wiedunflow generate``.
    questionary's prompt_toolkit application has already exited by the time
    this runs (modal pipeline guarantee — ADR-0013 D#4).
    """
    # Local imports avoid an import cycle (main.py imports menu via main()).
    from datetime import UTC, datetime

    from wiedunflow.adapters import (
        Bm25Store,
        JediResolver,
        NetworkxRanker,
        SystemClock,
        TreeSitterParser,
    )
    from wiedunflow.adapters.sqlite_cache import SQLiteCache
    from wiedunflow.cli.config import ConfigError, load_config
    from wiedunflow.cli.consent import ConsentDeniedError, ConsentRequiredError
    from wiedunflow.cli.main import (
        _build_llm_provider,
        _resolve_output_path,
        _run_pipeline,
    )
    from wiedunflow.cli.output import init_console
    from wiedunflow.cli.signals import SigintHandler
    from wiedunflow.use_cases.generate_tutorial import Providers

    started_at = datetime.now(UTC)

    overrides = {
        "llm_provider": payload["llm_provider"],
        "llm_model_plan": payload["llm_model_plan"],
        "llm_model_narrate": payload["llm_model_narrate"],
        "llm_base_url": payload.get("llm_base_url"),
        "llm_api_key": payload.get("llm_api_key"),
        "llm_concurrency": payload["llm_concurrency"],
        "llm_max_retries": payload["llm_max_retries"],
        "llm_max_wait_s": payload["llm_max_wait_s"],
        "max_lessons": payload["max_lessons"],
        "target_audience": payload["target_audience"],
        "exclude_patterns": payload["exclude_patterns"],
        "include_patterns": payload["include_patterns"],
        "output_path": payload.get("output_path"),
    }

    console = init_console()

    try:
        config = load_config(cli_overrides=overrides)
        # Menu path has TTY; user chose Launch — implicit consent + cost ack.
        llm = _build_llm_provider(config, no_consent_prompt=False, yes=False)
    except (ConfigError, ConsentRequiredError, ConsentDeniedError) as exc:
        print(f"  ! pipeline launch aborted: {exc}")
        return

    providers = Providers(
        llm=llm,
        parser=TreeSitterParser(),
        resolver=JediResolver(),
        ranker=NetworkxRanker(),
        vector_store=Bm25Store(),
        cache=SQLiteCache(),
        clock=SystemClock(),
    )

    sigint = SigintHandler()
    sigint.install()
    try:
        exit_code = _run_pipeline(
            repo_path=payload["repo_path"],
            providers=providers,
            excludes=tuple(payload["exclude_patterns"]),
            includes=tuple(payload["include_patterns"]),
            root=None,
            max_lessons=config.max_lessons,
            should_abort=sigint.should_finish.is_set,
            started_at=started_at,
            provider_label=config.llm_provider,
            console=console,
            dry_run=False,
            review_plan=False,
            max_cost_usd=None,
            auto_yes=False,
            no_cost_prompt=False,
            is_tty=True,
            json_mode=False,
            output_path=_resolve_output_path(config.output_path, repo_path=payload["repo_path"]),
        )
    except Exception as exc:
        print(f"  ! pipeline crashed: {type(exc).__name__}: {exc}")
        exit_code = 1
    finally:
        sigint.restore()

    # Append the run to the recent-runs history so the menu's "Recent runs"
    # picker can offer one-click reopen / re-run later. Failures here are
    # non-fatal — history is best-effort.
    import contextlib

    with contextlib.suppress(Exception):
        _append_to_recent_runs(payload, exit_code=exit_code)

    # Modal pipeline complete — main_menu_loop redraws the top-level menu next.
    print()


def _subwizard_filters(
    io: MenuIO,
    *,
    saved_excludes: list[str] | None = None,
    saved_includes: list[str] | None = None,
) -> dict[str, list[str]] | None:
    """§3 — collect exclude/include patterns. Returns dict or None.

    Opening prompt is "Customize file filters? (y/N)" default N — most users
    skip this section entirely. On No, returns the saved values unchanged.
    """
    _redraw_chrome("Generate · Section 3/5 · File Filters (optional)")
    print("  Patterns extend .gitignore matching. Most users skip this section.")

    customize = io.confirm("Customize file filters?", default=False)
    if customize is None:
        return None
    if not customize:
        print("  ✓ Skipped · using .gitignore defaults only")
        return {
            "exclude_patterns": list(saved_excludes or []),
            "include_patterns": list(saved_includes or []),
        }

    excludes = _list_manager(io, "Exclude patterns", list(saved_excludes or []))
    if excludes is None:
        return None

    includes = _list_manager(io, "Include patterns", list(saved_includes or []))
    if includes is None:
        return None

    return {"exclude_patterns": excludes, "include_patterns": includes}


# ---------------------------------------------------------------------------
# Backwards-compat aliases (Step 9 → post-launch UX iteration). External
# imports + Step 9 tests referenced the pre-merge helper / constant names.
# ---------------------------------------------------------------------------
_run_show_config_from_menu = _run_config_from_menu
