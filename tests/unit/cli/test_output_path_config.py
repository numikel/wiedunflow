# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 8 / v0.2.0: ``output_path`` config field + ``--output`` CLI flag.

Coverage:

- YAML ``output_path:`` is parsed into ``CodeguideConfig.output_path`` as
  :class:`pathlib.Path`.
- CLI ``--output``/``-o`` flag overrides the YAML value (precedence rule).
- Empty / missing config keeps ``output_path == None`` so the orchestrator
  falls back to ``./tutorial.html``.
- ``_resolve_output_path`` resolves relative paths against ``cwd`` and
  preserves absolute paths verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeguide.cli.config import CodeguideConfig, load_config
from codeguide.cli.main import _resolve_output_path

# ---------------------------------------------------------------------------
# CodeguideConfig — output_path field
# ---------------------------------------------------------------------------


def test_default_output_path_is_none() -> None:
    config = CodeguideConfig()
    assert config.output_path is None


def test_output_path_accepts_string_value() -> None:
    config = CodeguideConfig(output_path="./out/tutorial.html")
    assert config.output_path == Path("out/tutorial.html")


# ---------------------------------------------------------------------------
# YAML loader — output_path top-level key
# ---------------------------------------------------------------------------


def test_yaml_output_path_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tutorial.config.yaml").write_text(
        "output_path: ./reports/tutorial.html\n", encoding="utf-8"
    )

    config = load_config()

    assert config.output_path == Path("reports/tutorial.html")


def test_yaml_without_output_path_defaults_to_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tutorial.config.yaml").write_text("max_lessons: 5\n", encoding="utf-8")

    config = load_config()

    assert config.output_path is None


def test_cli_override_wins_over_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sprint 8 / v0.2.0: ``--output`` CLI flag must dominate YAML config."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tutorial.config.yaml").write_text(
        "output_path: ./from-yaml.html\n", encoding="utf-8"
    )

    cli_path = tmp_path / "from-cli.html"
    config = load_config(cli_overrides={"output_path": cli_path})

    assert config.output_path == cli_path


def test_cli_none_does_not_shadow_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``None`` from CLI means "flag not supplied" and must NOT erase YAML."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tutorial.config.yaml").write_text(
        "output_path: ./from-yaml.html\n", encoding="utf-8"
    )

    config = load_config(cli_overrides={"output_path": None})

    assert config.output_path == Path("from-yaml.html")


# ---------------------------------------------------------------------------
# _resolve_output_path — relative vs absolute
# ---------------------------------------------------------------------------


def test_resolve_output_path_returns_none_for_none() -> None:
    assert _resolve_output_path(None) is None


def test_resolve_output_path_keeps_absolute_unchanged(tmp_path: Path) -> None:
    abs_path = tmp_path / "tutorial.html"
    assert _resolve_output_path(abs_path) == abs_path


def test_resolve_output_path_makes_relative_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Path("out/tutorial.html")

    resolved = _resolve_output_path(relative)

    assert resolved is not None
    assert resolved.is_absolute()
    # Resolved path may differ in case on Windows but the suffix matches.
    assert resolved.name == "tutorial.html"
    assert resolved.parent.name == "out"
