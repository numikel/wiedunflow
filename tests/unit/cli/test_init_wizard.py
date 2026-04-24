# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for cli/init_wizard.py — run_init_wizard() (US-002/003)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from codeguide.cli.config import _load_yaml_flat
from codeguide.cli.main import cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_config_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect user_config_path() to a temp directory and return the path."""
    config_path = tmp_path / "codeguide" / "config.yaml"
    monkeypatch.setattr(
        "codeguide.cli.init_wizard.user_config_path",
        lambda: config_path,
    )
    return config_path


# ---------------------------------------------------------------------------
# 1. Interactive wizard writes valid YAML
# ---------------------------------------------------------------------------


def test_wizard_writes_yaml_to_user_config_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Interactive mode: scripted prompts produce a valid nested YAML config."""
    config_path = _patch_config_path(monkeypatch, tmp_path)
    runner = CliRunner()

    # Input sequence: provider → model_plan → model_narrate → api_key
    result = runner.invoke(
        cli,
        ["init"],
        input="anthropic\nclaude-sonnet-4-6\nclaude-opus-4-7\nsk-test-key\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"
    assert config_path.exists(), "Config file must be written"

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "anthropic"
    assert data["llm"]["model_plan"] == "claude-sonnet-4-6"
    assert data["llm"]["model_narrate"] == "claude-opus-4-7"
    assert data["llm"]["api_key"] == "sk-test-key"


def test_wizard_output_mentions_config_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Wizard must print 'Configuration written to <path>' on success."""
    _patch_config_path(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["init"],
        input="anthropic\nclaude-sonnet-4-6\nclaude-opus-4-7\nsk-test-key\n",
        catch_exceptions=False,
    )

    assert "Configuration written to" in result.output


# ---------------------------------------------------------------------------
# 2. --force flag
# ---------------------------------------------------------------------------


def test_wizard_refuses_existing_file_without_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without --force, wizard must exit 1 and print error when file exists."""
    config_path = _patch_config_path(monkeypatch, tmp_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("llm:\n  provider: anthropic\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["init"], input="", catch_exceptions=False)

    assert result.exit_code == 1, f"Expected exit 1, got {result.exit_code}"
    assert "already exists" in result.output or "already exists" in (result.stderr or "")


def test_wizard_force_overwrites_existing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--force must overwrite an existing config file."""
    config_path = _patch_config_path(monkeypatch, tmp_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("llm:\n  provider: openai\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["init", "--force"],
        input="anthropic\nclaude-sonnet-4-6\nclaude-opus-4-7\nsk-new-key\n",
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "anthropic"
    assert data["llm"]["api_key"] == "sk-new-key"


# ---------------------------------------------------------------------------
# 3. Non-interactive all-flags mode (US-003)
# ---------------------------------------------------------------------------


def test_wizard_non_interactive_all_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """All flags supplied → no prompts, YAML written immediately."""
    config_path = _patch_config_path(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "init",
            "--provider=openai",
            "--model-plan=gpt-4o",
            "--model-narrate=gpt-4o",
            "--api-key=sk-openai-test",
        ],
        input="",  # no interactive input expected
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "openai"
    assert data["llm"]["model_plan"] == "gpt-4o"
    assert data["llm"]["model_narrate"] == "gpt-4o"
    assert data["llm"]["api_key"] == "sk-openai-test"


def test_wizard_non_interactive_base_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """--base-url is written to YAML for openai_compatible provider."""
    config_path = _patch_config_path(monkeypatch, tmp_path)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "init",
            "--provider=openai_compatible",
            "--model-plan=gpt-4o",
            "--model-narrate=gpt-4o",
            "--api-key=sk-test",
            "--base-url=http://localhost:11434/v1",
        ],
        input="",
        catch_exceptions=False,
    )

    assert result.exit_code == 0, f"Expected exit 0, got {result.exit_code}.\n{result.output}"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert data["llm"]["base_url"] == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# 4. File permissions (POSIX-only)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="chmod semantics differ on Windows")
def test_wizard_writes_yaml_file_permissions_0600(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Config file written by wizard must have 0o600 permissions on POSIX."""
    config_path = _patch_config_path(monkeypatch, tmp_path)
    runner = CliRunner()

    runner.invoke(
        cli,
        ["init"],
        input="anthropic\nclaude-sonnet-4-6\nclaude-opus-4-7\nsk-key\n",
        catch_exceptions=False,
    )

    assert config_path.exists()
    mode = os.stat(config_path).st_mode & 0o777
    assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


# ---------------------------------------------------------------------------
# 5. YAML structure is loadable by _load_yaml_flat
# ---------------------------------------------------------------------------


def test_wizard_yaml_loadable_by_load_yaml_flat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """YAML written by wizard must be parseable by _load_yaml_flat."""
    config_path = _patch_config_path(monkeypatch, tmp_path)
    runner = CliRunner()

    runner.invoke(
        cli,
        ["init"],
        input="anthropic\nclaude-sonnet-4-6\nclaude-opus-4-7\nsk-key\n",
        catch_exceptions=False,
    )

    flat = _load_yaml_flat(config_path)
    assert flat["llm_provider"] == "anthropic"
    assert flat["llm_model_plan"] == "claude-sonnet-4-6"
    assert flat["llm_model_narrate"] == "claude-opus-4-7"
    assert flat["llm_api_key"] == "sk-key"
