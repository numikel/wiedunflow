# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Integration tests for CLI gateway security: SSRF + consent banner bypass.

These tests use Click's CliRunner to invoke ``wiedunflow generate`` end-to-end
with a manipulated ``tutorial.config.yaml`` and verify:

1. Malicious ``base_url`` values (cloud-metadata endpoints) → non-zero exit code
   and the word "cloud-metadata" in stderr/output — no SDK call ever made.
2. Bad-scheme ``base_url`` → non-zero exit, "scheme" in error output.
3. Valid localhost ``base_url`` → config is loaded without raising ConfigError
   (functional path, isolated from SDK via monkeypatch).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from wiedunflow.cli.main import cli as cli_main

pytestmark = pytest.mark.integration

_TINY_REPO = Path(__file__).parent.parent / "fixtures" / "tiny_repo"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, llm_block: dict[str, Any]) -> Path:
    cfg = tmp_path / "tutorial.config.yaml"
    cfg.write_text(yaml.safe_dump({"llm": llm_block}), encoding="utf-8")
    return cfg


def _invoke_generate(
    repo: Path,
    config_path: Path,
    *,
    extra: list[str] | None = None,
) -> Any:
    """Invoke ``wiedunflow generate <repo>`` with the given config file.

    Uses ``catch_exceptions=True`` (Click default) so that ``sys.exit(1)``
    raised by the ConfigError handler is properly captured as exit_code=1
    rather than propagating as SystemExit.

    In Click 8.x, ``CliRunner`` merges stdout and stderr into ``result.output``
    by default, so both ``click.echo(...)`` and ``click.echo(..., err=True)``
    are visible in ``result.output``.
    """
    runner = CliRunner()
    argv = [
        "generate",
        str(repo),
        "--config",
        str(config_path),
        "--yes",  # bypass consent prompt if we ever reach it
        "--no-consent-prompt",
        *(extra or []),
    ]
    return runner.invoke(cli_main, argv)


# ---------------------------------------------------------------------------
# 1. Cloud-metadata endpoint → hard block, non-zero exit
# ---------------------------------------------------------------------------


class TestImdsBaseUrlRejected:
    """Malicious tutorial.config.yaml with IMDS URL → exit nonzero, no SDK call."""

    def test_aws_imds_v4_rejected(self, tmp_path: Path) -> None:
        """http://169.254.169.254 is the AWS IMDS v4 endpoint — must be blocked."""
        cfg = _write_config(
            tmp_path,
            {
                "provider": "openai_compatible",
                "base_url": "http://169.254.169.254/v1",
            },
        )
        result = _invoke_generate(_TINY_REPO, cfg)

        assert result.exit_code != 0, (
            f"Expected non-zero exit for IMDS base_url; got {result.exit_code}. "
            f"Output: {result.output}"
        )
        assert "cloud-metadata endpoint" in result.output, (
            f"Error message must mention 'cloud-metadata endpoint'. Got output: {result.output!r}"
        )

    def test_gcp_metadata_fqdn_rejected(self, tmp_path: Path) -> None:
        """http://metadata.google.internal is the GCP metadata server."""
        cfg = _write_config(
            tmp_path,
            {
                "provider": "custom",
                "base_url": "http://metadata.google.internal/computeMetadata/v1",
            },
        )
        result = _invoke_generate(_TINY_REPO, cfg)

        assert result.exit_code != 0
        assert "cloud-metadata endpoint" in result.output

    def test_alibaba_cloud_metadata_rejected(self, tmp_path: Path) -> None:
        """100.100.100.200 is the Alibaba Cloud metadata server."""
        cfg = _write_config(
            tmp_path,
            {
                "provider": "openai_compatible",
                "base_url": "http://100.100.100.200/latest/meta-data",
            },
        )
        result = _invoke_generate(_TINY_REPO, cfg)

        assert result.exit_code != 0
        assert "cloud-metadata endpoint" in result.output


# ---------------------------------------------------------------------------
# 2. Bad scheme → rejected before any SDK call
# ---------------------------------------------------------------------------


class TestBadSchemeBaseUrlRejected:
    def test_file_scheme_rejected(self, tmp_path: Path) -> None:
        """file:// is not an allowed scheme for base_url."""
        cfg = _write_config(
            tmp_path,
            {
                "provider": "openai_compatible",
                "base_url": "file:///etc/passwd",
            },
        )
        result = _invoke_generate(_TINY_REPO, cfg)

        assert result.exit_code != 0
        assert "scheme" in result.output.lower()

    def test_gopher_scheme_rejected(self, tmp_path: Path) -> None:
        """gopher:// is a classic SSRF pivot scheme."""
        cfg = _write_config(
            tmp_path,
            {
                "provider": "openai_compatible",
                "base_url": "gopher://internal.service/exploit",
            },
        )
        result = _invoke_generate(_TINY_REPO, cfg)

        assert result.exit_code != 0
        assert "scheme" in result.output.lower()


# ---------------------------------------------------------------------------
# 3. Valid localhost → config loads without ConfigError (SDK call patched out)
# ---------------------------------------------------------------------------


class TestValidLocalhostBaseUrl:
    """Localhost base_url with custom provider passes validate_base_url."""

    @pytest.fixture(autouse=True)
    def _patch_llm_builder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Swap _build_llm_provider so no SDK is needed."""
        from wiedunflow.adapters.fake_llm_provider import FakeLLMProvider

        monkeypatch.setattr(
            "wiedunflow.cli.main._build_llm_provider",
            lambda config, **_kw: FakeLLMProvider(),
        )

    def test_localhost_ollama_base_url_allowed(self, tmp_path: Path) -> None:
        """http://localhost:11434/v1 (Ollama) is a valid base_url — must not raise ConfigError."""
        cfg = _write_config(
            tmp_path,
            {
                "provider": "custom",
                "base_url": "http://localhost:11434/v1",
            },
        )
        # The CLI should not exit with an error due to base_url validation.
        # It may fail further in the pipeline (missing API key etc.) but the
        # validate_base_url gate must not fire for localhost.
        result = _invoke_generate(_TINY_REPO, cfg)

        # ConfigError from validate_base_url would contain "scheme must be" or
        # "cloud-metadata endpoint". Neither should appear.
        assert "cloud-metadata endpoint" not in result.output, (
            "Localhost must not be treated as SSRF target."
        )
        assert "scheme must be" not in result.output


# ---------------------------------------------------------------------------
# 4. Inline config (no YAML file) — CLI --base-url flag with IMDS value
# ---------------------------------------------------------------------------


class TestCliBaseUrlFlag:
    """--base-url CLI flag is also validated before any SDK call."""

    def test_cli_flag_imds_url_rejected(self) -> None:
        """Passing --base-url http://169.254.169.254/v1 via CLI flag is blocked."""
        runner = CliRunner()
        argv = [
            "generate",
            str(_TINY_REPO),
            "--provider",
            "openai_compatible",
            "--base-url",
            "http://169.254.169.254/v1",
            "--yes",
            "--no-consent-prompt",
        ]
        result = runner.invoke(cli_main, argv)

        assert result.exit_code != 0
        assert "cloud-metadata endpoint" in result.output
