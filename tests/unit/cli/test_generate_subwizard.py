# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for Generate sub-wizard §1 (Repo+Output) and §2 (Provider+Models).

Step 5 (ADR-0013). Each section is a thin wrapper around ``MenuIO`` with
validation, conditional flow, and abort-as-None semantics. ``FakeMenuIO``
drives the prompts deterministically; ``_StubCatalog`` substitutes for the
``ModelCatalog`` adapters so tests never hit the network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wiedunflow.cli.menu import (
    _pick_hosted_model,
    _saved_section_payload,
    _subwizard_provider_models,
    _subwizard_repo_output,
    _validate_repo_path,
)
from tests.unit.cli._fake_menu_io import FakeMenuIO


class _StubCatalog:
    """Deterministic ``ModelCatalog`` for tests."""

    def __init__(self, models: list[str]) -> None:
        self.models = list(models)
        self.refresh_calls = 0

    def list_models(self) -> list[str]:
        return list(self.models)

    def refresh(self) -> list[str]:
        self.refresh_calls += 1
        return list(self.models)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Materialize a tiny real git repo so .git/ exists."""
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


# ---------------------------------------------------------------------------
# _validate_repo_path
# ---------------------------------------------------------------------------


def test_validate_repo_path_valid(git_repo: Path) -> None:
    assert _validate_repo_path(str(git_repo)) is None


def test_validate_repo_path_missing(tmp_path: Path) -> None:
    error = _validate_repo_path(str(tmp_path / "nope"))
    assert error is not None and "does not exist" in error


def test_validate_repo_path_not_a_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "afile.txt"
    file_path.write_text("x", encoding="utf-8")
    error = _validate_repo_path(str(file_path))
    assert error is not None and "not a directory" in error


def test_validate_repo_path_not_a_git_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    error = _validate_repo_path(str(plain))
    assert error is not None and ".git" in error


def test_validate_repo_path_empty_string() -> None:
    error = _validate_repo_path("")
    assert error is not None and "required" in error


# ---------------------------------------------------------------------------
# _subwizard_repo_output (§1)
# ---------------------------------------------------------------------------


def test_subwizard_repo_output_happy_path(git_repo: Path) -> None:
    io = FakeMenuIO(responses=["Type path manually", str(git_repo), ""])

    result = _subwizard_repo_output(io)

    assert result is not None
    assert result["repo_path"] == git_repo
    assert result["output_path"] is None  # empty string → default


def test_subwizard_repo_output_explicit_output(git_repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out" / "tutorial.html"
    io = FakeMenuIO(responses=["Type path manually", str(git_repo), str(out)])

    result = _subwizard_repo_output(io)

    assert result is not None
    assert result["output_path"] == out


def test_subwizard_repo_output_retry_on_invalid(git_repo: Path, tmp_path: Path) -> None:
    """Invalid path → error printed → re-prompt (no advance) → valid path accepted."""
    io = FakeMenuIO(
        responses=[
            "Type path manually",  # source selector, first pick attempt
            str(tmp_path / "missing"),  # path prompt — rejected (invalid repo)
            "Type path manually",  # source selector, second pick attempt
            str(git_repo),  # path prompt — accepted
            "",  # output_path skipped
        ]
    )

    result = _subwizard_repo_output(io)

    assert result is not None
    assert result["repo_path"] == git_repo


def test_subwizard_repo_output_abort_on_repo(git_repo: Path) -> None:
    io = FakeMenuIO(responses=[None])

    assert _subwizard_repo_output(io) is None


def test_subwizard_repo_output_abort_on_output(git_repo: Path) -> None:
    io = FakeMenuIO(responses=["Type path manually", str(git_repo), None])

    assert _subwizard_repo_output(io) is None


# ---------------------------------------------------------------------------
# _subwizard_provider_models (§2) — anthropic happy path with env-set key
# ---------------------------------------------------------------------------


def _anthropic_catalog() -> _StubCatalog:
    return _StubCatalog(["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"])


def _openai_catalog() -> _StubCatalog:
    return _StubCatalog(["gpt-5.4", "gpt-4.1", "gpt-4.1-mini"])


def test_provider_models_anthropic_with_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provider=anthropic + env key set → no API key prompt."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    io = FakeMenuIO(
        responses=[
            "anthropic",  # provider
            "claude-sonnet-4-6",  # plan model
            "claude-opus-4-7",  # narrate model
        ]
    )

    result = _subwizard_provider_models(
        io,
        saved=None,
        anthropic_catalog=_anthropic_catalog(),
        openai_catalog=_openai_catalog(),
    )

    assert result is not None
    assert result["llm_provider"] == "anthropic"
    assert result["llm_model_plan"] == "claude-sonnet-4-6"
    assert result["llm_model_narrate"] == "claude-opus-4-7"
    assert result["llm_api_key"] is None  # env var path
    assert result["llm_base_url"] is None
    methods = [call[0] for call in io.calls]
    assert "password" not in methods


def test_provider_models_anthropic_no_env_key_prompts_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    io = FakeMenuIO(
        responses=[
            "anthropic",
            "claude-sonnet-4-6",
            "claude-opus-4-7",
            "sk-ant-secret",  # password prompt
        ]
    )

    result = _subwizard_provider_models(
        io,
        saved=None,
        anthropic_catalog=_anthropic_catalog(),
        openai_catalog=_openai_catalog(),
    )

    assert result is not None
    assert result["llm_api_key"] == "sk-ant-secret"


# ---------------------------------------------------------------------------
# §2 — openai_compatible / custom paths
# ---------------------------------------------------------------------------


def test_provider_models_openai_compatible_requires_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    io = FakeMenuIO(
        responses=[
            "openai_compatible",  # provider
            "llama3-70b",  # plan model (text)
            "llama3-70b",  # narrate model (text)
            "any-key",  # password
            "ftp://bad",  # base URL — rejected
            "http://localhost:11434/v1",  # base URL — accepted
        ]
    )

    result = _subwizard_provider_models(
        io,
        saved=None,
        anthropic_catalog=_anthropic_catalog(),
        openai_catalog=_openai_catalog(),
    )

    assert result is not None
    assert result["llm_provider"] == "openai_compatible"
    assert result["llm_base_url"] == "http://localhost:11434/v1"


def test_provider_models_custom_optional_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """custom provider treats API key as optional (text input, not password)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    io = FakeMenuIO(
        responses=[
            "custom",  # provider
            "llama3",  # plan model
            "llama3",  # narrate model
            "",  # api key empty → None
            "http://localhost:8000/v1",  # base URL
        ]
    )

    result = _subwizard_provider_models(
        io,
        saved=None,
        anthropic_catalog=_anthropic_catalog(),
        openai_catalog=_openai_catalog(),
    )

    assert result is not None
    assert result["llm_provider"] == "custom"
    assert result["llm_api_key"] is None
    assert result["llm_base_url"] == "http://localhost:8000/v1"
    methods = [call[0] for call in io.calls]
    assert "password" not in methods


# ---------------------------------------------------------------------------
# §2 — express path (saved config detected)
# ---------------------------------------------------------------------------


def test_provider_models_express_path_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Saved config + Y → returns saved values + _express marker."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-saved")
    from wiedunflow.cli.config import CodeguideConfig

    saved = CodeguideConfig(
        llm_provider="anthropic",
        llm_model_plan="claude-sonnet-4-6",
        llm_model_narrate="claude-opus-4-7",
    )
    io = FakeMenuIO(responses=[True])

    result = _subwizard_provider_models(
        io,
        saved=saved,
        anthropic_catalog=_anthropic_catalog(),
        openai_catalog=_openai_catalog(),
    )

    assert result is not None
    assert result.get("_express") is True
    assert result["llm_provider"] == "anthropic"
    assert result["llm_model_plan"] == "claude-sonnet-4-6"


def test_provider_models_express_path_no_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-saved")
    from wiedunflow.cli.config import CodeguideConfig

    saved = CodeguideConfig(
        llm_provider="anthropic",
        llm_model_plan="claude-sonnet-4-6",
        llm_model_narrate="claude-opus-4-7",
    )
    io = FakeMenuIO(
        responses=[
            False,  # express? no
            "anthropic",  # provider re-pick
            "claude-haiku-4-5",  # plan
            "claude-opus-4-7",  # narrate
        ]
    )

    result = _subwizard_provider_models(
        io,
        saved=saved,
        anthropic_catalog=_anthropic_catalog(),
        openai_catalog=_openai_catalog(),
    )

    assert result is not None
    assert result.get("_express", False) is False
    assert result["llm_model_plan"] == "claude-haiku-4-5"


def test_saved_section_payload_marks_express() -> None:
    from wiedunflow.cli.config import CodeguideConfig

    saved = CodeguideConfig(
        llm_provider="openai",
        llm_model_plan="gpt-4.1",
        llm_model_narrate="gpt-4.1",
    )
    payload = _saved_section_payload(saved)
    assert payload["_express"] is True
    assert payload["llm_provider"] == "openai"


# ---------------------------------------------------------------------------
# §2 — model picker refresh sentinel
# ---------------------------------------------------------------------------


def test_pick_hosted_model_refresh_then_select() -> None:
    catalog = _StubCatalog(["claude-opus-4-7", "claude-sonnet-4-6"])
    refresh_label = "[r] Refresh now (re-fetch from provider API)"
    io = FakeMenuIO(responses=[refresh_label, "claude-opus-4-7"])

    result = _pick_hosted_model(io, catalog=catalog, label="Planning model:")

    assert result == "claude-opus-4-7"
    assert catalog.refresh_calls == 1


def test_pick_hosted_model_abort_returns_none() -> None:
    catalog = _StubCatalog(["claude-opus-4-7"])
    io = FakeMenuIO(responses=[None])

    assert _pick_hosted_model(io, catalog=catalog, label="x") is None


# ---------------------------------------------------------------------------
# §2 — abort paths
# ---------------------------------------------------------------------------


def test_provider_models_abort_on_provider_select(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    io = FakeMenuIO(responses=[None])  # provider Esc

    assert (
        _subwizard_provider_models(
            io,
            saved=None,
            anthropic_catalog=_anthropic_catalog(),
            openai_catalog=_openai_catalog(),
        )
        is None
    )


def test_provider_models_abort_on_express_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    from wiedunflow.cli.config import CodeguideConfig

    saved = CodeguideConfig()
    io = FakeMenuIO(responses=[None])  # express confirm Esc

    assert (
        _subwizard_provider_models(
            io,
            saved=saved,
            anthropic_catalog=_anthropic_catalog(),
            openai_catalog=_openai_catalog(),
        )
        is None
    )


def test_provider_models_abort_on_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    io = FakeMenuIO(
        responses=[
            "anthropic",
            "claude-sonnet-4-6",
            "claude-opus-4-7",
            None,  # password Esc
        ]
    )

    assert (
        _subwizard_provider_models(
            io,
            saved=None,
            anthropic_catalog=_anthropic_catalog(),
            openai_catalog=_openai_catalog(),
        )
        is None
    )
