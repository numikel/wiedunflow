# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Integration tests for US-004 config precedence chain.

Each test plants a *conflicting* lower-priority source and asserts the
higher-priority source wins. The resolved ``WiedunflowConfig.llm_provider``
is the probe variable because every layer can carry it.

Boundary map
------------
Test 1  CLI flag      > env var
Test 2  env var       > --config YAML
Test 3  --config YAML > ./tutorial.config.yaml (cwd)
Test 4  cwd YAML      > user-level config
Test 5  user config   > built-in defaults
Test 6  (no source)   → built-in default
Test 7  CLI + env + YAML + user all set → CLI wins end-to-end
Test 8  DEBUG log lines emitted per resolved field
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest
import yaml

import wiedunflow.cli.config as config_module
from wiedunflow.cli.config import load_config

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, provider: str) -> None:
    """Write a minimal YAML config that sets ``llm.provider = <provider>``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"llm": {"provider": provider}}), encoding="utf-8")


def _clean_wiedunflow_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all ``WIEDUNFLOW_*`` env vars so they cannot leak between tests."""
    for var in list(os.environ):
        if var.startswith("WIEDUNFLOW_"):
            monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# Test class — US-004 AC2: every precedence boundary verified
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestConfigPrecedenceChain:
    """US-004 AC2: every precedence boundary verified with conflicting values."""

    def test_cli_flag_overrides_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Boundary 1: CLI > env — CLI wins even when WIEDUNFLOW_LLM_PROVIDER is set."""
        _clean_wiedunflow_env(monkeypatch)
        monkeypatch.setenv("WIEDUNFLOW_LLM_PROVIDER", "openai")  # would lose
        monkeypatch.chdir(tmp_path)  # no project config in tmp_path

        # Patch user_config_path to point at a non-existent file
        monkeypatch.setattr(
            config_module, "user_config_path", lambda: tmp_path / "nonexistent.yaml"
        )

        cfg = load_config(cli_overrides={"llm_provider": "anthropic"})

        assert cfg.llm_provider == "anthropic", "CLI flag must override env WIEDUNFLOW_LLM_PROVIDER"

    def test_env_overrides_cli_config_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Boundary 2: env > --config YAML — env wins over an explicit --config file."""
        _clean_wiedunflow_env(monkeypatch)
        monkeypatch.setenv("WIEDUNFLOW_LLM_PROVIDER", "openai")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            config_module, "user_config_path", lambda: tmp_path / "nonexistent.yaml"
        )

        config_file = tmp_path / "custom.yaml"
        _write_yaml(config_file, "anthropic")  # would lose to env

        cfg = load_config(cli_config_path=config_file)

        assert cfg.llm_provider == "openai", (
            "Env WIEDUNFLOW_LLM_PROVIDER must override --config YAML"
        )

    def test_cli_config_overrides_project_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Boundary 3: --config > ./tutorial.config.yaml — explicit path beats cwd default."""
        _clean_wiedunflow_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            config_module, "user_config_path", lambda: tmp_path / "nonexistent.yaml"
        )

        _write_yaml(tmp_path / "tutorial.config.yaml", "anthropic")  # would lose

        wins_file = tmp_path / "wins.yaml"
        _write_yaml(wins_file, "openai")

        cfg = load_config(cli_config_path=wins_file)

        assert cfg.llm_provider == "openai", "--config YAML must override ./tutorial.config.yaml"

    def test_project_config_overrides_user_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Boundary 4: ./tutorial.config.yaml > user-level config."""
        _clean_wiedunflow_env(monkeypatch)
        monkeypatch.chdir(tmp_path)

        user_cfg = tmp_path / "user_home" / ".config" / "wiedunflow" / "config.yaml"
        _write_yaml(user_cfg, "anthropic")  # would lose
        monkeypatch.setattr(config_module, "user_config_path", lambda: user_cfg)

        _write_yaml(tmp_path / "tutorial.config.yaml", "openai")

        cfg = load_config()

        assert cfg.llm_provider == "openai", (
            "./tutorial.config.yaml must override user-level config"
        )

    def test_user_config_overrides_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Boundary 5: user-level config > built-in defaults."""
        _clean_wiedunflow_env(monkeypatch)
        monkeypatch.chdir(tmp_path)  # no project config

        user_cfg = tmp_path / "user_home" / ".config" / "wiedunflow" / "config.yaml"
        _write_yaml(user_cfg, "openai")
        monkeypatch.setattr(config_module, "user_config_path", lambda: user_cfg)

        cfg = load_config()

        assert cfg.llm_provider == "openai", "User-level config must override built-in defaults"

    def test_defaults_used_when_no_source_supplies_value(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Boundary 6: no source supplies a value → built-in default applies."""
        _clean_wiedunflow_env(monkeypatch)
        monkeypatch.chdir(tmp_path)

        # Point user_config_path at a non-existent file — no YAML anywhere.
        monkeypatch.setattr(
            config_module, "user_config_path", lambda: tmp_path / "nonexistent.yaml"
        )

        cfg = load_config()

        assert cfg.llm_provider == "anthropic", "Built-in default must be 'anthropic'"
        assert cfg.llm_model_plan == "claude-sonnet-4-6", (
            "Built-in default model_plan must be 'claude-sonnet-4-6'"
        )
        assert cfg.llm_model_narrate == "claude-opus-4-7", (
            "Built-in default model_narrate must be 'claude-opus-4-7'"
        )

    def test_all_layers_conflicting_cli_wins(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: CLI=anthropic + env=openai + project=custom + user=openai_compatible → CLI wins."""
        _clean_wiedunflow_env(monkeypatch)
        monkeypatch.setenv("WIEDUNFLOW_LLM_PROVIDER", "openai")  # layer 2 — loses

        user_cfg = tmp_path / "user_home" / ".config" / "wiedunflow" / "config.yaml"
        _write_yaml(user_cfg, "openai_compatible")  # layer 5 — loses
        monkeypatch.setattr(config_module, "user_config_path", lambda: user_cfg)

        monkeypatch.chdir(tmp_path)
        _write_yaml(tmp_path / "tutorial.config.yaml", "custom")  # layer 4 — loses

        explicit_cfg = tmp_path / "explicit.yaml"
        _write_yaml(explicit_cfg, "custom")  # layer 3 — loses

        cfg = load_config(
            cli_overrides={"llm_provider": "anthropic"},  # layer 1 — wins
            cli_config_path=explicit_cfg,
        )

        assert cfg.llm_provider == "anthropic", "CLI flag must win over all lower-priority sources"

    def test_debug_log_emitted_per_resolved_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """US-003: DEBUG lines 'config resolved: <key>=<value> from <source>' are emitted."""
        _clean_wiedunflow_env(monkeypatch)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(
            config_module, "user_config_path", lambda: tmp_path / "nonexistent.yaml"
        )

        with caplog.at_level(logging.DEBUG, logger="wiedunflow.cli.config"):
            load_config(cli_overrides={"llm_provider": "openai"})

        log_messages = [r.getMessage() for r in caplog.records]

        # Each key field must appear in exactly one debug line.
        assert any("config resolved: llm_provider=openai from cli" in m for m in log_messages), (
            "Expected 'config resolved: llm_provider=openai from cli' in debug logs"
        )
        assert any("config resolved: llm_model_plan=" in m for m in log_messages), (
            "Expected 'config resolved: llm_model_plan=...' debug log"
        )
        assert any("config resolved: llm_model_narrate=" in m for m in log_messages), (
            "Expected 'config resolved: llm_model_narrate=...' debug log"
        )
