# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""WiedunFlow configuration — loading, validation, and precedence chain.

Precedence (highest to lowest):
  1. CLI flags (``cli_overrides``)
  2. Environment variables (``WIEDUNFLOW_*``)
  3. ``--config <path>`` YAML
  4. ``./tutorial.config.yaml`` (cwd)
  5. ``~/.config/wiedunflow/config.yaml`` (user-level)
  6. Built-in defaults
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

import platformdirs
import yaml
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def user_config_path() -> Path:
    """Return the platform-appropriate user-level config path."""
    return Path(platformdirs.user_config_dir("wiedunflow")) / "config.yaml"


class WiedunflowConfig(BaseSettings):
    """Validated configuration model for a WiedunFlow run.

    All ``WIEDUNFLOW_*`` environment variables are picked up automatically by
    Pydantic BaseSettings.  Nested YAML keys (``llm.provider``) are flattened
    to ``llm_provider`` etc. before being passed as init kwargs.

    Provider values:
    - ``anthropic``: uses ``ANTHROPIC_API_KEY``
    - ``openai``: uses ``OPENAI_API_KEY``
    - ``openai_compatible``: alias for ``openai``, also uses ``OPENAI_API_KEY``
    - ``custom``: uses ``llm_api_key_env`` env-var name (for Ollama / LM Studio / vLLM);
      ``llm_base_url`` points to the OSS endpoint (e.g. ``http://localhost:11434/v1``)
    """

    # ADR-0015 (BREAKING in v0.7.0): default provider switched to OpenAI due to
    # Anthropic rate-limit ergonomics. Anthropic stays as a fully supported BYOK
    # alternative — set ``llm.provider: anthropic`` in YAML to opt back in.
    llm_provider: Literal["anthropic", "openai", "openai_compatible", "custom"] = "openai"
    llm_model_plan: str = "gpt-5.4"
    llm_model_narrate: str = "gpt-5.4"
    llm_api_key: SecretStr | None = None
    llm_base_url: str | None = None
    llm_api_key_env: str | None = None
    llm_concurrency: int = 10
    llm_max_retries: int = 5
    llm_max_wait_s: int = 60
    exclude_patterns: list[str] = Field(default_factory=list)
    include_patterns: list[str] = Field(default_factory=list)
    max_lessons: int = 30
    # ADR-0013 decision 9 (BREAKING CHANGE in v0.4.0): target_audience is a
    # 5-level enum, not free text. Old free-text values flow through
    # ``_normalize_target_audience`` in ``_load_yaml_flat`` (fuzzy mapping
    # with logged warning) so existing YAML configs keep loading; the shim
    # is removed in v1.0. Per-level narration prompt branches arrive in v0.4.
    target_audience: Literal["noob", "junior", "mid", "senior", "expert"] = "mid"
    # v0.2.0: Override the tutorial output path. Relative paths resolve against
    # cwd at runtime; absolute paths are used verbatim. ``None`` keeps the
    # default ``./tutorial.html``. CLI flag ``--output``/``-o`` takes precedence.
    output_path: Path | None = None
    # US-008: exact file names exempted from the hard-refuse secret blocklist.
    # YAML path: security.allow_secret_files: [".env.example"]
    security_allow_secret_files: frozenset[str] = Field(default_factory=frozenset)

    # v0.2.1: tutorial quality controls (opt-in; defaults preserve v0.2.0 behaviour).
    # YAML path: planning.entry_point_first
    planning_entry_point_first: Literal["auto", "always", "never"] = "auto"
    # YAML path: planning.skip_trivial_helpers
    planning_skip_trivial_helpers: bool = False
    # YAML path: narration.min_words_trivial
    narration_min_words_trivial: int = 50
    # YAML path: narration.snippet_validation
    narration_snippet_validation: bool = True

    model_config = SettingsConfigDict(
        env_prefix="WIEDUNFLOW_",
        env_nested_delimiter="__",
        extra="ignore",
    )


def load_config(
    *,
    cli_overrides: dict[str, Any] | None = None,
    cli_config_path: Path | None = None,
) -> WiedunflowConfig:
    """Build a validated ``WiedunflowConfig`` applying the full precedence chain.

    Args:
        cli_overrides: Values from CLI flags (``None`` values are filtered out
            so they do not shadow lower-priority sources).
        cli_config_path: Path passed via ``--config``; loaded after the cwd
            YAML, before CLI overrides.

    Returns:
        A fully-resolved and validated ``WiedunflowConfig``.
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
        env_name = f"WIEDUNFLOW_{field_name.upper()}"
        if env_name in os.environ and field_name not in clean_overrides:
            merged_yaml.pop(field_name)

    # Build init kwargs: YAML (already env-stripped) + CLI (dominates).
    init_kwargs: dict[str, Any] = {**merged_yaml, **clean_overrides}

    config = WiedunflowConfig(**init_kwargs)

    # US-003: emit DEBUG log for key resolved config fields with their source.
    _log_resolved_config(config, clean_overrides, merged_yaml)

    return config


def _log_resolved_config(
    config: WiedunflowConfig,
    cli_overrides: dict[str, Any],
    yaml_values: dict[str, Any],
) -> None:
    """Emit DEBUG-level logs showing where each key config field was resolved from."""
    key_fields = ("llm_provider", "llm_model_plan", "llm_model_narrate")
    for field in key_fields:
        if field in cli_overrides:
            source = "cli"
        elif f"WIEDUNFLOW_{field.upper()}" in os.environ:
            source = "env"
        elif field in yaml_values:
            source = "yaml"
        else:
            source = "default"
        value = getattr(config, field)
        logger.debug("config resolved: %s=%s from %s", field, value, source)


_LLM_BLOCK_MAP: dict[str, str] = {
    "provider": "llm_provider",
    "model_plan": "llm_model_plan",
    "model_narrate": "llm_model_narrate",
    "api_key": "llm_api_key",
    "base_url": "llm_base_url",
    "api_key_env": "llm_api_key_env",
    "concurrency": "llm_concurrency",
    "max_retries": "llm_max_retries",
    "max_wait_s": "llm_max_wait_s",
}

_PLANNING_BLOCK_MAP: dict[str, str] = {
    "entry_point_first": "planning_entry_point_first",
    "skip_trivial_helpers": "planning_skip_trivial_helpers",
}

_NARRATION_BLOCK_MAP: dict[str, str] = {
    "min_words_trivial": "narration_min_words_trivial",
    "snippet_validation": "narration_snippet_validation",
}

_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "exclude_patterns",
    "include_patterns",
    "max_lessons",
    "target_audience",
    "output_path",
)


def _apply_block(
    data: dict[str, Any],
    block_name: str,
    key_to_field: dict[str, str],
    flat: dict[str, Any],
) -> None:
    """Copy nested block keys (``data[block_name][k]``) to flat field names."""
    block = data.get(block_name)
    if not isinstance(block, dict):
        return
    for yaml_key, field_name in key_to_field.items():
        if yaml_key in block:
            flat[field_name] = block[yaml_key]


_TARGET_AUDIENCE_ENUM: frozenset[str] = frozenset({"noob", "junior", "mid", "senior", "expert"})


def _normalize_target_audience(raw: Any) -> Any:
    """Map free-text ``target_audience`` (pre-v0.4.0) to one of the 5 enum levels.

    The shim only fires for YAML inputs (CLI flags and env vars use the enum
    directly). Already-valid enum values pass through unchanged. Non-string
    values pass through so Pydantic surfaces the type error itself.

    Mapping rules (first match wins; case-insensitive substring):
    - ``"noob"`` → ``"noob"``
    - ``"junior"`` or ``"beginner"`` → ``"junior"``
    - ``"senior"`` → ``"senior"``
    - ``"expert"`` or ``"advanced"`` → ``"expert"``
    - ``"mid"`` → ``"mid"``
    - anything else → ``"mid"`` with a logged warning

    Removed in v1.0 once old YAML configs are assumed migrated.
    """
    if not isinstance(raw, str):
        return raw  # let Pydantic surface the validation error
    if raw in _TARGET_AUDIENCE_ENUM:
        return raw
    lowered = raw.lower()
    if "noob" in lowered:
        return "noob"
    if "junior" in lowered or "beginner" in lowered:
        return "junior"
    if "senior" in lowered:
        return "senior"
    if "expert" in lowered or "advanced" in lowered:
        return "expert"
    if "mid" in lowered:
        return "mid"
    logger.warning(
        "target_audience %r did not match any 5-level enum (noob/junior/mid/senior/expert); "
        "defaulting to 'mid'. Update your YAML to one of the enum values.",
        raw,
    )
    return "mid"


def _load_yaml_flat(path: Path) -> dict[str, Any]:
    """Load a YAML config file and flatten nested blocks to field names."""
    with path.open("r", encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh) or {}

    flat: dict[str, Any] = {}

    _apply_block(data, "llm", _LLM_BLOCK_MAP, flat)
    _apply_block(data, "planning", _PLANNING_BLOCK_MAP, flat)
    _apply_block(data, "narration", _NARRATION_BLOCK_MAP, flat)

    for key in _TOP_LEVEL_KEYS:
        if key in data:
            flat[key] = data[key]

    # ADR-0013 decision 9: legacy free-text target_audience → fuzzy-mapped enum.
    if "target_audience" in flat:
        flat["target_audience"] = _normalize_target_audience(flat["target_audience"])

    # security.allow_secret_files → frozenset[str] (special-case: type coercion).
    security = data.get("security")
    if isinstance(security, dict):
        allow_list = security.get("allow_secret_files")
        if isinstance(allow_list, list):
            flat["security_allow_secret_files"] = frozenset(str(x) for x in allow_list)

    return flat


def resolve_api_key(config: WiedunflowConfig) -> str:
    """Extract and return the plain API key for the configured provider.

    Resolution order per provider:

    - **anthropic**: ``config.llm_api_key`` → ``ANTHROPIC_API_KEY`` env var.
    - **openai** / **openai_compatible**: ``config.llm_api_key`` → ``OPENAI_API_KEY`` env var.
    - **custom** (Ollama / LM Studio / vLLM): reads the env var named by
      ``config.llm_api_key_env`` when set; falls back to ``"not-needed"``
      placeholder (OSS endpoints typically ignore the api_key).

    Args:
        config: Resolved ``WiedunflowConfig``.

    Returns:
        The plain-text API key string (may be ``"not-needed"`` for local endpoints).

    Raises:
        ConfigError: No key is available for the requested provider.
    """
    # llm_api_key in config always wins regardless of provider.
    if config.llm_api_key is not None:
        return config.llm_api_key.get_secret_value()

    if config.llm_provider == "anthropic":
        return _require_env("ANTHROPIC_API_KEY", "anthropic")

    if config.llm_provider in ("openai", "openai_compatible"):
        return _require_env("OPENAI_API_KEY", config.llm_provider)

    if config.llm_provider == "custom":
        return _resolve_custom_key(config)

    raise ConfigError(f"Unknown provider {config.llm_provider!r}.")


def _require_env(env_var: str, provider: str) -> str:
    """Return ``env_var`` value or raise :class:`ConfigError`."""
    key = os.environ.get(env_var)
    if not key:
        raise ConfigError(
            f"{env_var} is required when --provider={provider}. "
            "Set the env var or configure llm.api_key in tutorial.config.yaml."
        )
    return key


def _resolve_custom_key(config: WiedunflowConfig) -> str:
    """Resolve API key for the ``custom`` provider (Ollama / LM Studio / vLLM).

    Reads the env var named by ``config.llm_api_key_env`` when set; falls back
    to ``"not-needed"`` for endpoints that ignore the api_key entirely.
    """
    if config.llm_api_key_env:
        key = os.environ.get(config.llm_api_key_env)
        if not key:
            raise ConfigError(
                f"Env var {config.llm_api_key_env!r} is not set for custom provider. "
                "Set the env var or remove llm.api_key_env from tutorial.config.yaml."
            )
        return key
    return "not-needed"
