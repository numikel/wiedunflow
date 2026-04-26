# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Interactive first-run wizard for ``wiedun-flow init`` (US-002 / US-003).

Guides the user through setting up a user-level ``config.yaml`` with LLM
provider credentials.  All prompts can be bypassed by passing the
corresponding CLI flags (US-003 non-interactive mode).

Config is written in the nested YAML format that :func:`wiedunflow.cli.config._load_yaml_flat`
expects:

.. code-block:: yaml

   llm:
     provider: anthropic
     model_plan: claude-sonnet-4-6
     model_narrate: claude-opus-4-7
     api_key: sk-ant-...
     base_url: null          # omitted when None

File permissions are set to ``0o600`` after every write (POSIX only) so the
API key is not readable by other users on shared systems.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import click
import yaml

from wiedunflow.cli.config import user_config_path

# Providers that need a base_url (and are prompted for one when in interactive mode).
_LOCAL_PROVIDERS = frozenset({"openai_compatible", "custom"})

# All valid provider choices — keep in sync with the Click option in main.py.
_PROVIDER_CHOICES = ["anthropic", "openai", "openai_compatible", "custom"]


def run_init_wizard(
    *,
    provider: str | None = None,
    model_plan: str | None = None,
    model_narrate: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    force: bool = False,
) -> int:
    """Run the interactive (or non-interactive) first-run wizard.

    When all arguments are ``None`` the wizard prompts interactively.  Any
    non-``None`` argument skips the corresponding prompt (US-003).

    Args:
        provider: LLM provider name.  When ``None`` the user is prompted.
        model_plan: Model for the planning stage.  When ``None`` the user is
            prompted.
        model_narrate: Model for the narration stage.  When ``None`` the user
            is prompted.
        api_key: Provider API key.  When ``None`` the user is prompted with
            hidden input.
        base_url: Base URL for ``openai_compatible`` / ``custom`` providers.
            Optional even for those providers.
        force: Overwrite an existing config file without prompting.

    Returns:
        ``0`` on success, ``1`` on failure (file already exists without
        ``--force``, or write error).
    """
    config_path = user_config_path()

    # Guard: refuse to overwrite unless --force.
    if config_path.exists() and not force:
        click.echo(
            f"error: {config_path} already exists. Use --force to overwrite.",
            err=True,
        )
        return 1

    # --- Step 1: provider -------------------------------------------------
    resolved_provider: str = provider or click.prompt(
        "Provider",
        type=click.Choice(_PROVIDER_CHOICES),
        default="openai",
    )

    # --- Step 2: model_plan -----------------------------------------------
    resolved_model_plan: str = model_plan or click.prompt(
        "Model for planning",
        default="gpt-5.4",
    )

    # --- Step 3: model_narrate --------------------------------------------
    resolved_model_narrate: str = model_narrate or click.prompt(
        "Model for narration",
        default="gpt-5.4",
    )

    # --- Step 4: api_key --------------------------------------------------
    resolved_api_key: str = api_key or click.prompt(
        "API key",
        hide_input=True,
    )

    # --- Step 5: base_url (optional, only prompted for local providers) ---
    resolved_base_url: str | None = base_url
    if resolved_base_url is None and resolved_provider in _LOCAL_PROVIDERS:
        raw = click.prompt(
            "Base URL (e.g. http://localhost:11434/v1)",
            default="",
        )
        resolved_base_url = raw.strip() or None

    # Build the nested YAML structure that _load_yaml_flat expects.
    llm_block: dict[str, Any] = {
        "provider": resolved_provider,
        "model_plan": resolved_model_plan,
        "model_narrate": resolved_model_narrate,
        "api_key": resolved_api_key,
    }
    if resolved_base_url:
        llm_block["base_url"] = resolved_base_url

    yaml_data: dict[str, Any] = {"llm": llm_block}

    # Write config file.
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(yaml_data, fh, default_flow_style=False, allow_unicode=True)
        if sys.platform != "win32":
            os.chmod(config_path, 0o600)
    except OSError as exc:
        click.echo(f"error: failed to write {config_path}: {exc}", err=True)
        return 1

    click.echo(f"Configuration written to {config_path}")
    return 0
