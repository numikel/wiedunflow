# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""CodeGuide configuration — loading, validation, and precedence chain.

Precedence (highest to lowest):
  1. CLI flags (``cli_overrides``)
  2. Environment variables (``CODEGUIDE_*``)
  3. ``--config <path>`` YAML
  4. ``./tutorial.config.yaml`` (cwd)
  5. ``~/.config/codeguide/config.yaml`` (user-level)
  6. Built-in defaults
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import platformdirs
import yaml
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def user_config_path() -> Path:
    """Return the platform-appropriate user-level config path."""
    return Path(platformdirs.user_config_dir("codeguide")) / "config.yaml"


class CodeguideConfig(BaseSettings):
    """Validated configuration model for a CodeGuide run.

    All ``CODEGUIDE_*`` environment variables are picked up automatically by
    Pydantic BaseSettings.  Nested YAML keys (``llm.provider``) are flattened
    to ``llm_provider`` etc. before being passed as init kwargs.
    """

    llm_provider: Literal["anthropic", "openai", "openai_compatible"] = "anthropic"
    llm_model_plan: str = "claude-sonnet-4-6"
    llm_model_narrate: str = "claude-opus-4-7"
    llm_api_key: SecretStr | None = None
    llm_concurrency: int = 10
    llm_max_retries: int = 5
    llm_max_wait_s: int = 60
    exclude_patterns: list[str] = Field(default_factory=list)
    include_patterns: list[str] = Field(default_factory=list)
    max_lessons: int = 30
    target_audience: str = "mid-level Python developer"

    model_config = SettingsConfigDict(
        env_prefix="CODEGUIDE_",
        env_nested_delimiter="__",
        extra="ignore",
    )


def load_config(
    *,
    cli_overrides: dict[str, Any] | None = None,
    cli_config_path: Path | None = None,
) -> CodeguideConfig:
    """Build a validated ``CodeguideConfig`` applying the full precedence chain.

    Args:
        cli_overrides: Values from CLI flags (``None`` values are filtered out
            so they do not shadow lower-priority sources).
        cli_config_path: Path passed via ``--config``; loaded after the cwd
            YAML, before CLI overrides.

    Returns:
        A fully-resolved and validated ``CodeguideConfig``.
    """
    # Filter out None values — they represent "not supplied" CLI flags.
    clean_overrides: dict[str, Any] = {
        k: v for k, v in (cli_overrides or {}).items() if v is not None
    }

    # Gather YAML sources in ascending priority order.
    yaml_sources: list[Path] = [
        user_config_path(),  # lowest YAML priority
        Path.cwd() / "tutorial.config.yaml",
        *(([cli_config_path]) if cli_config_path else []),  # highest YAML priority
    ]

    merged_yaml: dict[str, Any] = {}
    for path in yaml_sources:
        if path.is_file():
            merged_yaml.update(_load_yaml_flat(path))

    # ENV vars must win over YAML but lose to CLI overrides.
    # BaseSettings reads env automatically, but only when a field is NOT
    # supplied as an init kwarg.  Strip YAML entries that have a corresponding
    # env var set (unless the CLI also overrides that field — CLI always wins).
    for field_name in list(merged_yaml.keys()):
        env_name = f"CODEGUIDE_{field_name.upper()}"
        if env_name in os.environ and field_name not in clean_overrides:
            merged_yaml.pop(field_name)

    # Build init kwargs: YAML (already env-stripped) + CLI (dominates).
    init_kwargs: dict[str, Any] = {**merged_yaml, **clean_overrides}

    return CodeguideConfig(**init_kwargs)


def _load_yaml_flat(path: Path) -> dict[str, Any]:
    """Load a YAML config file and flatten nested ``llm:`` block to field names."""
    with path.open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh) or {}

    flat: dict[str, Any] = {}

    llm = data.get("llm")
    if isinstance(llm, dict):
        _map = {
            "provider": "llm_provider",
            "model_plan": "llm_model_plan",
            "model_narrate": "llm_model_narrate",
            "api_key": "llm_api_key",
            "concurrency": "llm_concurrency",
            "max_retries": "llm_max_retries",
            "max_wait_s": "llm_max_wait_s",
        }
        for yaml_key, field_name in _map.items():
            if yaml_key in llm:
                flat[field_name] = llm[yaml_key]

    for key in ("exclude_patterns", "include_patterns", "max_lessons", "target_audience"):
        if key in data:
            flat[key] = data[key]

    return flat


def resolve_api_key(config: CodeguideConfig) -> str:
    """Extract and return the plain API key for the configured provider.

    Priority: ``config.llm_api_key`` (from YAML / env) → ``ANTHROPIC_API_KEY``
    environment variable for the Anthropic provider.

    Args:
        config: Resolved ``CodeguideConfig``.

    Returns:
        The plain-text API key string.

    Raises:
        ConfigError: No key is available for the requested provider.
    """
    if config.llm_provider == "anthropic":
        if config.llm_api_key is not None:
            return config.llm_api_key.get_secret_value()
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ConfigError(
                "ANTHROPIC_API_KEY is required when --provider=anthropic. "
                "Set the env var or configure llm.api_key in tutorial.config.yaml."
            )
        return key

    # S4+ — other providers supported in future sprints.
    raise ConfigError(f"Provider {config.llm_provider!r} not yet supported in Sprint 3.")
