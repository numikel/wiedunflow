# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for cli/config.py — CodeguideConfig and load_config()."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from codeguide.cli.config import (
    CodeguideConfig,
    ConfigError,
    load_config,
    resolve_api_key,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.dump(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Defaults
# ---------------------------------------------------------------------------


def test_defaults(monkeypatch):
    """CodeguideConfig() produces sensible defaults when no env / YAML present."""
    # Remove env vars that might leak from CI
    monkeypatch.delenv("CODEGUIDE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("CODEGUIDE_LLM_MODEL_PLAN", raising=False)
    monkeypatch.delenv("CODEGUIDE_LLM_MODEL_NARRATE", raising=False)
    cfg = CodeguideConfig()
    assert cfg.llm_provider == "anthropic"
    assert cfg.llm_model_plan == "claude-sonnet-4-6"
    assert cfg.llm_model_narrate == "claude-opus-4-7"
    assert cfg.max_lessons == 30
    assert cfg.llm_concurrency == 10
    assert cfg.llm_api_key is None


# ---------------------------------------------------------------------------
# 2. YAML override via cli_config_path
# ---------------------------------------------------------------------------


def test_yaml_override_provider(tmp_path, monkeypatch):
    """YAML llm.provider overrides the default value."""
    monkeypatch.delenv("CODEGUIDE_LLM_PROVIDER", raising=False)
    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(cfg_file, {"llm": {"provider": "openai"}})

    cfg = load_config(cli_config_path=cfg_file)
    assert cfg.llm_provider == "openai"


def test_yaml_all_llm_fields(tmp_path, monkeypatch):
    """YAML llm block populates all llm_ fields."""
    for env in [
        "CODEGUIDE_LLM_PROVIDER",
        "CODEGUIDE_LLM_MODEL_PLAN",
        "CODEGUIDE_LLM_MODEL_NARRATE",
        "CODEGUIDE_LLM_CONCURRENCY",
        "CODEGUIDE_LLM_MAX_RETRIES",
        "CODEGUIDE_LLM_MAX_WAIT_S",
    ]:
        monkeypatch.delenv(env, raising=False)

    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(
        cfg_file,
        {
            "llm": {
                "provider": "openai_compatible",
                "model_plan": "gpt-4o",
                "model_narrate": "gpt-4o-mini",
                "concurrency": 5,
                "max_retries": 3,
                "max_wait_s": 30,
            }
        },
    )
    cfg = load_config(cli_config_path=cfg_file)
    assert cfg.llm_provider == "openai_compatible"
    assert cfg.llm_model_plan == "gpt-4o"
    assert cfg.llm_model_narrate == "gpt-4o-mini"
    assert cfg.llm_concurrency == 5
    assert cfg.llm_max_retries == 3
    assert cfg.llm_max_wait_s == 30


def test_yaml_top_level_fields(tmp_path, monkeypatch):
    """YAML top-level keys (max_lessons, target_audience) are loaded."""
    monkeypatch.delenv("CODEGUIDE_MAX_LESSONS", raising=False)
    monkeypatch.delenv("CODEGUIDE_TARGET_AUDIENCE", raising=False)
    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(
        cfg_file,
        {"max_lessons": 15, "target_audience": "senior engineer"},
    )
    cfg = load_config(cli_config_path=cfg_file)
    assert cfg.max_lessons == 15
    assert cfg.target_audience == "senior engineer"


# ---------------------------------------------------------------------------
# 3. ENV override beats YAML
# ---------------------------------------------------------------------------


def test_env_overrides_yaml(tmp_path, monkeypatch):
    """CODEGUIDE_LLM_MODEL_PLAN env var beats the YAML value."""
    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(cfg_file, {"llm": {"model_plan": "yaml-model"}})
    monkeypatch.setenv("CODEGUIDE_LLM_MODEL_PLAN", "env-model")

    cfg = load_config(cli_config_path=cfg_file)
    assert cfg.llm_model_plan == "env-model"


# ---------------------------------------------------------------------------
# 4. CLI override beats everything
# ---------------------------------------------------------------------------


def test_cli_override_beats_yaml_and_env(tmp_path, monkeypatch):
    """CLI overrides have highest priority, beating both YAML and env."""
    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(cfg_file, {"llm": {"model_plan": "yaml-model"}})
    monkeypatch.setenv("CODEGUIDE_LLM_MODEL_PLAN", "env-model")

    cfg = load_config(
        cli_overrides={"llm_model_plan": "cli-model"},
        cli_config_path=cfg_file,
    )
    assert cfg.llm_model_plan == "cli-model"


def test_cli_none_values_filtered(tmp_path, monkeypatch):
    """None CLI overrides are ignored — they do not override lower-priority sources."""
    monkeypatch.delenv("CODEGUIDE_LLM_MODEL_PLAN", raising=False)
    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(cfg_file, {"llm": {"model_plan": "yaml-model"}})

    cfg = load_config(
        cli_overrides={"llm_model_plan": None},  # should be filtered
        cli_config_path=cfg_file,
    )
    assert cfg.llm_model_plan == "yaml-model"


# ---------------------------------------------------------------------------
# 5. Full precedence chain in one test
# ---------------------------------------------------------------------------


def test_full_precedence_chain(tmp_path, monkeypatch):
    """CLI > env > --config YAML > default, verified field by field."""
    # Only remove env vars for the specific fields under test to avoid side effects
    monkeypatch.delenv("CODEGUIDE_LLM_MODEL_NARRATE", raising=False)
    monkeypatch.setenv("CODEGUIDE_LLM_MODEL_PLAN", "env-plan")
    monkeypatch.delenv("CODEGUIDE_LLM_PROVIDER", raising=False)

    cfg_file = tmp_path / "config.yaml"
    _write_yaml(
        cfg_file,
        {
            "llm": {
                "model_plan": "yaml-plan",  # should be beaten by env
                "model_narrate": "yaml-narrate",  # only YAML sets this
                "provider": "openai",  # should remain (no env/cli override)
            }
        },
    )
    cfg = load_config(
        cli_overrides={"llm_model_plan": "cli-plan"},  # beats env
        cli_config_path=cfg_file,
    )
    assert cfg.llm_model_plan == "cli-plan"  # CLI wins
    assert cfg.llm_model_narrate == "yaml-narrate"  # YAML (no env/cli)
    assert cfg.llm_provider == "openai"  # YAML (no env/cli)


# ---------------------------------------------------------------------------
# 6. resolve_api_key — anthropic provider
# ---------------------------------------------------------------------------


def test_resolve_api_key_from_env(monkeypatch):
    """resolve_api_key returns the ANTHROPIC_API_KEY env var."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    monkeypatch.delenv("CODEGUIDE_LLM_API_KEY", raising=False)
    cfg = CodeguideConfig(llm_provider="anthropic")
    key = resolve_api_key(cfg)
    assert key == "sk-from-env"


def test_resolve_api_key_from_config(monkeypatch):
    """resolve_api_key prefers llm_api_key in config over env var."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    cfg = CodeguideConfig(llm_provider="anthropic", llm_api_key="sk-config-key")  # type: ignore[arg-type]
    key = resolve_api_key(cfg)
    assert key == "sk-config-key"


# ---------------------------------------------------------------------------
# 7. resolve_api_key — missing key → ConfigError
# ---------------------------------------------------------------------------


def test_resolve_api_key_missing_raises(monkeypatch):
    """resolve_api_key raises ConfigError when no key is available."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = CodeguideConfig(llm_provider="anthropic")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY is required"):
        resolve_api_key(cfg)


def test_resolve_api_key_unsupported_provider():
    """resolve_api_key raises ConfigError for unknown provider values."""
    # Force an unknown value past Pydantic validation using model_construct.
    cfg = CodeguideConfig.model_construct(llm_provider="unknown_provider")  # type: ignore[call-arg]
    with pytest.raises(ConfigError, match="Unknown provider"):
        resolve_api_key(cfg)


# ---------------------------------------------------------------------------
# 8. resolve_api_key — openai provider
# ---------------------------------------------------------------------------


def test_resolve_api_key_openai_from_env(monkeypatch):
    """resolve_api_key returns OPENAI_API_KEY env var for openai provider."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-env")
    monkeypatch.delenv("CODEGUIDE_LLM_API_KEY", raising=False)
    cfg = CodeguideConfig(llm_provider="openai")
    key = resolve_api_key(cfg)
    assert key == "sk-openai-env"


def test_resolve_api_key_openai_from_config(monkeypatch):
    """resolve_api_key prefers llm_api_key in config over OPENAI_API_KEY env var."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    cfg = CodeguideConfig(llm_provider="openai", llm_api_key="sk-config-key")  # type: ignore[arg-type]
    key = resolve_api_key(cfg)
    assert key == "sk-config-key"


def test_resolve_api_key_openai_missing_raises(monkeypatch):
    """resolve_api_key raises ConfigError when OPENAI_API_KEY is absent for openai provider."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = CodeguideConfig(llm_provider="openai")
    with pytest.raises(ConfigError, match="OPENAI_API_KEY is required"):
        resolve_api_key(cfg)


def test_resolve_api_key_openai_compatible_from_env(monkeypatch):
    """resolve_api_key handles openai_compatible provider the same as openai."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-compat-env")
    monkeypatch.delenv("CODEGUIDE_LLM_API_KEY", raising=False)
    cfg = CodeguideConfig(llm_provider="openai_compatible")
    key = resolve_api_key(cfg)
    assert key == "sk-compat-env"


# ---------------------------------------------------------------------------
# 9. resolve_api_key — custom provider (Ollama / LM Studio / vLLM)
# ---------------------------------------------------------------------------


def test_resolve_api_key_custom_with_api_key_env(monkeypatch):
    """resolve_api_key reads the env var named by llm_api_key_env for custom provider."""
    monkeypatch.setenv("MY_LOCAL_KEY", "sk-local-secret")
    cfg = CodeguideConfig(llm_provider="custom", llm_api_key_env="MY_LOCAL_KEY")
    key = resolve_api_key(cfg)
    assert key == "sk-local-secret"


def test_resolve_api_key_custom_api_key_env_missing_raises(monkeypatch):
    """resolve_api_key raises ConfigError when the named env var is not set."""
    monkeypatch.delenv("MY_LOCAL_KEY", raising=False)
    cfg = CodeguideConfig(llm_provider="custom", llm_api_key_env="MY_LOCAL_KEY")
    with pytest.raises(ConfigError, match="MY_LOCAL_KEY"):
        resolve_api_key(cfg)


def test_resolve_api_key_custom_no_api_key_env_returns_placeholder(monkeypatch):
    """resolve_api_key returns 'not-needed' when custom provider has no api_key_env."""
    cfg = CodeguideConfig(llm_provider="custom")
    key = resolve_api_key(cfg)
    assert key == "not-needed"


def test_resolve_api_key_custom_explicit_api_key_wins(monkeypatch):
    """resolve_api_key prefers explicit llm_api_key over api_key_env for custom provider."""
    monkeypatch.setenv("MY_LOCAL_KEY", "sk-from-env-var")
    cfg = CodeguideConfig(
        llm_provider="custom",
        llm_api_key="sk-explicit",  # type: ignore[arg-type]
        llm_api_key_env="MY_LOCAL_KEY",
    )
    key = resolve_api_key(cfg)
    assert key == "sk-explicit"


# ---------------------------------------------------------------------------
# 10. YAML flattening for new BYOK fields
# ---------------------------------------------------------------------------


def test_yaml_base_url_and_api_key_env(tmp_path, monkeypatch):
    """YAML llm.base_url and llm.api_key_env are loaded into config fields."""
    monkeypatch.delenv("CODEGUIDE_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("CODEGUIDE_LLM_API_KEY_ENV", raising=False)
    cfg_file = tmp_path / "tutorial.config.yaml"
    _write_yaml(
        cfg_file,
        {
            "llm": {
                "provider": "custom",
                "base_url": "http://localhost:11434/v1",
                "api_key_env": "OLLAMA_KEY",
            }
        },
    )
    cfg = load_config(cli_config_path=cfg_file)
    assert cfg.llm_provider == "custom"
    assert cfg.llm_base_url == "http://localhost:11434/v1"
    assert cfg.llm_api_key_env == "OLLAMA_KEY"
