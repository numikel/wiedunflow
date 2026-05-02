# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 8 / v0.2.0: ``output_path`` config field + ``--output`` CLI flag.

Coverage:

- YAML ``output_path:`` is parsed into ``WiedunflowConfig.output_path`` as
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

from wiedunflow.cli.config import WiedunflowConfig, load_config
from wiedunflow.cli.main import _resolve_output_path

# ---------------------------------------------------------------------------
# WiedunflowConfig — output_path field
# ---------------------------------------------------------------------------


def test_default_output_path_is_none() -> None:
    config = WiedunflowConfig()
    assert config.output_path is None


def test_output_path_accepts_string_value() -> None:
    config = WiedunflowConfig(output_path="./out/tutorial.html")
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
# _resolve_output_path — defaults, relative vs absolute, .html auto-append
# ---------------------------------------------------------------------------


def test_resolve_output_path_defaults_to_repo_dir(tmp_path: Path) -> None:
    """v0.9.1+: when no path is configured, the default lives next to the
    analyzed repo (was: ``./tutorial.html`` in cwd) and uses the repo name as
    the file stem so the artifact is self-describing."""
    repo = tmp_path / "my-cool-project"
    repo.mkdir()

    resolved = _resolve_output_path(None, repo_path=repo)

    assert resolved.is_absolute()
    assert resolved == (repo / "wiedunflow-my-cool-project.html").resolve()


def test_resolve_output_path_keeps_absolute_unchanged(tmp_path: Path) -> None:
    abs_path = tmp_path / "tutorial.html"
    repo = tmp_path / "repo"
    repo.mkdir()

    assert _resolve_output_path(abs_path, repo_path=repo) == abs_path


def test_resolve_output_path_makes_relative_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Path("out/tutorial.html")
    repo = tmp_path / "any-repo"
    repo.mkdir()

    resolved = _resolve_output_path(relative, repo_path=repo)

    assert resolved.is_absolute()
    # Resolved path may differ in case on Windows but the suffix matches.
    assert resolved.name == "tutorial.html"
    assert resolved.parent.name == "out"


def test_resolve_output_path_appends_html_when_missing_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """v0.9.1+: ``--output my-tour`` (no extension) must become ``my-tour.html``
    so the file opens in the browser when double-clicked. Closes the
    "I forgot the extension" feedback from the v0.9.0 manual eval."""
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "any-repo"
    repo.mkdir()

    resolved = _resolve_output_path(Path("my-tour"), repo_path=repo)

    assert resolved.name == "my-tour.html"


def test_resolve_output_path_preserves_existing_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the user already supplied an extension (``.html``, ``.htm``, or
    anything else) we MUST NOT touch it — only the empty-suffix case gets the
    auto-append."""
    monkeypatch.chdir(tmp_path)
    repo = tmp_path / "any-repo"
    repo.mkdir()

    assert _resolve_output_path(Path("tour.html"), repo_path=repo).name == "tour.html"
    assert _resolve_output_path(Path("tour.htm"), repo_path=repo).name == "tour.htm"


def test_resolve_output_path_default_uses_repo_name_with_spaces(tmp_path: Path) -> None:
    """The repo dir's name flows into the default output filename verbatim —
    spaces and unicode included. The resulting Path must still be valid."""
    repo = tmp_path / "Codeguide v2 (legacy)"
    repo.mkdir()

    resolved = _resolve_output_path(None, repo_path=repo)

    assert resolved.parent == repo.resolve()
    assert resolved.name == "wiedunflow-Codeguide v2 (legacy).html"
