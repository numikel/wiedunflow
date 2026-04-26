# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for Step 8 — init wizard via menu, cost-gate confirm_fn injection,
``Show config`` / ``Estimate cost`` / ``Resume last run`` / ``Help`` actions,
and ``SQLiteCache.has_checkpoint``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from wiedunflow.cli.menu import (
    _run_config_from_menu,
    _run_estimate_from_menu,
    _run_help_from_menu,
    _run_init_from_menu,
    _run_resume_from_menu,
)
from tests.unit.cli._fake_menu_io import FakeMenuIO

# Backward-compat alias for tests written against the pre-merge name.
_run_show_config_from_menu = _run_config_from_menu


class _StubCatalog:
    """Deterministic ``ModelCatalog`` for init wizard tests."""

    def __init__(self, models: list[str]) -> None:
        self.models = list(models)
        self.refresh_calls = 0

    def list_models(self) -> list[str]:
        return list(self.models)

    def refresh(self) -> list[str]:
        self.refresh_calls += 1
        return list(self.models)


def _anthropic_catalog() -> _StubCatalog:
    return _StubCatalog(["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5"])


def _openai_catalog() -> _StubCatalog:
    return _StubCatalog(["gpt-5.4", "gpt-4.1", "gpt-4.1-mini"])


def _init_kwargs() -> dict[str, Any]:
    return {
        "anthropic_catalog": _anthropic_catalog(),
        "openai_catalog": _openai_catalog(),
    }


@pytest.fixture
def isolated_user_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``user_config_path()`` into a tmp dir for write/read tests."""
    target = tmp_path / "config.yaml"
    monkeypatch.setattr("wiedunflow.cli.menu.user_config_path", lambda: target)
    monkeypatch.setattr("wiedunflow.cli.config.user_config_path", lambda: target)
    return target


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


# ---------------------------------------------------------------------------
# _run_init_from_menu
# ---------------------------------------------------------------------------


def test_init_from_menu_writes_yaml(
    isolated_user_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    io = FakeMenuIO(
        responses=[
            "anthropic",  # provider
            "claude-sonnet-4-6",  # plan
            "claude-opus-4-7",  # narrate
            "sk-ant-test",  # api key
        ]
    )

    _run_init_from_menu(io, **_init_kwargs())

    assert isolated_user_config.is_file()
    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "anthropic"
    assert data["llm"]["model_plan"] == "claude-sonnet-4-6"
    assert data["llm"]["api_key"] == "sk-ant-test"


def test_init_from_menu_overwrite_confirm_no_aborts(
    isolated_user_config: Path,
) -> None:
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text("llm:\n  provider: openai\n", encoding="utf-8")
    io = FakeMenuIO(responses=[False])  # overwrite? no

    _run_init_from_menu(io, **_init_kwargs())

    # File should remain unchanged.
    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "openai"


def test_init_from_menu_overwrite_confirm_yes_replaces(
    isolated_user_config: Path,
) -> None:
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text("llm:\n  provider: openai\n", encoding="utf-8")
    io = FakeMenuIO(
        responses=[
            True,  # overwrite? yes
            "anthropic",
            "claude-sonnet-4-6",
            "claude-opus-4-7",
            "sk-new",
        ]
    )

    _run_init_from_menu(io, **_init_kwargs())

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "anthropic"


def test_init_from_menu_openai_compatible_writes_base_url(
    isolated_user_config: Path,
) -> None:
    io = FakeMenuIO(
        responses=[
            "openai_compatible",
            "llama3",
            "llama3",
            "any-key",
            "http://localhost:11434/v1",
        ]
    )

    _run_init_from_menu(io, **_init_kwargs())

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["llm"]["base_url"] == "http://localhost:11434/v1"


def test_init_from_menu_abort_on_provider(isolated_user_config: Path) -> None:
    """Esc on the very first step (provider) aborts back to the menu."""
    io = FakeMenuIO(responses=[None])

    _run_init_from_menu(io, **_init_kwargs())

    assert not isolated_user_config.exists()


def test_init_from_menu_back_from_model_plan_returns_to_provider(
    isolated_user_config: Path,
) -> None:
    """Esc on model_plan must navigate back to the provider step (not abort)."""
    io = FakeMenuIO(
        responses=[
            "anthropic",  # provider (step 0)
            None,  # Esc on model_plan → back to provider
            "openai",  # provider re-pick
            "gpt-4.1",  # plan
            "gpt-4.1",  # narrate
            "sk-openai-test",  # api key
        ]
    )

    _run_init_from_menu(io, **_init_kwargs())

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "openai"
    assert data["llm"]["model_plan"] == "gpt-4.1"


def test_init_from_menu_back_preserves_state_so_defaults_show_prior_value(
    isolated_user_config: Path,
) -> None:
    """When the user goes back, the next forward prompt re-fills with the prior choice.

    We can't observe the *default* from FakeMenuIO directly (it ignores defaults),
    but we can prove the cursor moved back: the response queue is consumed in
    cursor order, so we just need to count how many prompts fire.
    """
    io = FakeMenuIO(
        responses=[
            "anthropic",  # provider
            "claude-sonnet-4-6",  # plan
            None,  # Esc on narrate → back to plan
            "claude-haiku-4-5",  # plan re-prompt (overrides earlier)
            "claude-opus-4-7",  # narrate
            "sk-back",  # api key
        ]
    )

    _run_init_from_menu(io, **_init_kwargs())

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["llm"]["model_plan"] == "claude-haiku-4-5"
    assert data["llm"]["model_narrate"] == "claude-opus-4-7"


def test_init_from_menu_back_from_base_url_returns_to_api_key(
    isolated_user_config: Path,
) -> None:
    """The conditional base_url step participates in back navigation."""
    io = FakeMenuIO(
        responses=[
            "openai_compatible",  # provider
            "llama3",  # plan
            "llama3",  # narrate
            "wrong-key",  # api key
            None,  # Esc on base_url → back to api_key
            "right-key",  # api key re-prompt
            "http://localhost:11434/v1",  # base_url
        ]
    )

    _run_init_from_menu(io, **_init_kwargs())

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == "right-key"
    assert data["llm"]["base_url"] == "http://localhost:11434/v1"


def test_init_from_menu_double_esc_walks_back_to_abort(
    isolated_user_config: Path,
) -> None:
    """Repeated Esc all the way to the first step aborts cleanly."""
    io = FakeMenuIO(
        responses=[
            "anthropic",  # provider
            "claude-sonnet-4-6",  # plan
            None,  # Esc on narrate → back to plan
            None,  # Esc on plan → back to provider
            None,  # Esc on provider → abort
        ]
    )

    _run_init_from_menu(io, **_init_kwargs())

    assert not isolated_user_config.exists()


def test_init_from_menu_provider_change_inserts_base_url_step(
    isolated_user_config: Path,
) -> None:
    """Switching the provider mid-wizard rebuilds the step list — base_url appears
    when the new provider needs it."""
    io = FakeMenuIO(
        responses=[
            "anthropic",  # provider
            "claude-sonnet-4-6",  # plan
            None,  # Esc → back to plan
            None,  # Esc → back to provider
            "openai_compatible",  # provider re-pick (needs base_url)
            "llama3",  # plan
            "llama3",  # narrate
            "any-key",  # api key
            "http://localhost:8000/v1",  # base_url
        ]
    )

    _run_init_from_menu(io, **_init_kwargs())

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "openai_compatible"
    assert data["llm"]["base_url"] == "http://localhost:8000/v1"


# ---------------------------------------------------------------------------
# _run_show_config_from_menu
# ---------------------------------------------------------------------------


def test_show_config_no_file_prints_hint(
    isolated_user_config: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When no config exists, the merged Configuration entry offers to init.

    Declining the init prompt returns to the main menu without writing anything.
    """
    io = FakeMenuIO(responses=[False])  # decline "initialize one now?"

    _run_show_config_from_menu(io)

    out = capsys.readouterr().out
    assert "No saved config" in out
    assert not isolated_user_config.exists()


def test_show_config_with_saved_renders_panel(
    isolated_user_config: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text(
        "llm:\n  provider: anthropic\n  model_plan: claude-sonnet-4-6\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WIEDUNFLOW_LLM_PROVIDER", raising=False)
    # Render once → user picks [Done] → loop exits without edits.
    io = FakeMenuIO(responses=["[Done]"])

    _run_show_config_from_menu(io)

    out = capsys.readouterr().out
    assert "anthropic" in out
    assert "CURRENT CONFIG" in out


def test_show_config_edit_audience_persists_to_yaml(
    isolated_user_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Picking ``Audience`` then a new value rewrites the YAML and re-renders."""
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text(
        "llm:\n  provider: anthropic\n  model_plan: claude-sonnet-4-6\n  model_narrate: claude-opus-4-7\n"
        "target_audience: mid\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WIEDUNFLOW_TARGET_AUDIENCE", raising=False)
    io = FakeMenuIO(
        responses=[
            "Audience",  # field selector
            "senior",  # new value
            "[Done]",  # second loop iteration → exit
        ]
    )

    _run_show_config_from_menu(io)

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["target_audience"] == "senior"


def test_show_config_edit_max_lessons_persists(
    isolated_user_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text(
        "llm:\n  provider: anthropic\n  model_plan: claude-sonnet-4-6\n  model_narrate: claude-opus-4-7\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WIEDUNFLOW_MAX_LESSONS", raising=False)
    io = FakeMenuIO(responses=["Max lessons", "12", "[Done]"])

    _run_show_config_from_menu(io)

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["max_lessons"] == 12


def test_show_config_edit_concurrency_persists(
    isolated_user_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text(
        "llm:\n  provider: anthropic\n  model_plan: claude-sonnet-4-6\n  model_narrate: claude-opus-4-7\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WIEDUNFLOW_LLM_CONCURRENCY", raising=False)
    io = FakeMenuIO(responses=["Concurrency", "15", "[Done]"])

    _run_show_config_from_menu(io)

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["llm"]["concurrency"] == 15


def test_show_config_edit_base_url_empty_clears(
    isolated_user_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text(
        "llm:\n  provider: openai_compatible\n  model_plan: llama3\n  model_narrate: llama3\n"
        "  base_url: http://localhost:11434/v1\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WIEDUNFLOW_LLM_BASE_URL", raising=False)
    io = FakeMenuIO(responses=["Base URL", "", "[Done]"])

    _run_show_config_from_menu(io)

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert "base_url" not in data["llm"]


def test_show_config_esc_on_field_keeps_existing_value(
    isolated_user_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Esc on a per-field prompt cancels just that edit; existing value preserved."""
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text(
        "llm:\n  provider: anthropic\n  model_plan: claude-sonnet-4-6\n  model_narrate: claude-opus-4-7\n"
        "max_lessons: 30\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WIEDUNFLOW_MAX_LESSONS", raising=False)
    io = FakeMenuIO(responses=["Max lessons", None, "[Done]"])

    _run_show_config_from_menu(io)

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["max_lessons"] == 30


def test_show_config_edit_excludes_uses_list_manager(
    isolated_user_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wiedunflow.cli.menu import _LIST_ADD, _LIST_DONE

    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text(
        "llm:\n  provider: anthropic\n  model_plan: claude-sonnet-4-6\n  model_narrate: claude-opus-4-7\n",
        encoding="utf-8",
    )
    io = FakeMenuIO(
        responses=[
            "Exclude patterns",  # field selector
            _LIST_ADD,
            "tests/**",
            _LIST_DONE,
            "[Done]",
        ]
    )

    _run_show_config_from_menu(io)

    data = yaml.safe_load(isolated_user_config.read_text(encoding="utf-8"))
    assert data["exclude_patterns"] == ["tests/**"]


def test_show_config_esc_on_field_selector_exits_to_menu(
    isolated_user_config: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Esc on the field-selector itself exits the editor (no infinite loop)."""
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text(
        "llm:\n  provider: anthropic\n  model_plan: claude-sonnet-4-6\n  model_narrate: claude-opus-4-7\n",
        encoding="utf-8",
    )
    io = FakeMenuIO(responses=[None])

    _run_show_config_from_menu(io)
    # No exception, no second iteration — return is implicit on Esc.


# ---------------------------------------------------------------------------
# _run_estimate_from_menu
# ---------------------------------------------------------------------------


def test_estimate_renders_panel_for_valid_repo(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (git_repo / "module.py").write_text("def foo(): pass\n", encoding="utf-8")
    # Path prompt + "press Enter to return" pause.
    io = FakeMenuIO(responses=[str(git_repo), ""])

    _run_estimate_from_menu(io)

    out = capsys.readouterr().out
    assert "COST ESTIMATE" in out
    assert "$" in out


def test_estimate_aborts_on_invalid_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    io = FakeMenuIO(responses=[str(tmp_path / "missing")])

    _run_estimate_from_menu(io)

    out = capsys.readouterr().out
    assert "does not exist" in out


def test_estimate_abort_returns_silently(capsys: pytest.CaptureFixture[str]) -> None:
    io = FakeMenuIO(responses=[None])

    _run_estimate_from_menu(io)

    out = capsys.readouterr().out
    assert "COST ESTIMATE" not in out


# ---------------------------------------------------------------------------
# _run_resume_from_menu
# ---------------------------------------------------------------------------


def test_resume_no_checkpoint_returns_to_menu(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _StubCache:
        def has_checkpoint(self, _path: Path) -> bool:
            return False

    monkeypatch.setattr(
        "wiedunflow.adapters.sqlite_cache.SQLiteCache",
        lambda *_a, **_k: _StubCache(),
    )
    launched: list[bool] = []
    monkeypatch.setattr(
        "wiedunflow.cli.menu._launch_pipeline",
        lambda _p: launched.append(True),
    )
    io = FakeMenuIO(responses=[str(git_repo)])

    _run_resume_from_menu(io)

    out = capsys.readouterr().out
    assert "No checkpoint found" in out
    assert launched == []


def test_resume_with_checkpoint_calls_launch(
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_user_config: Path,
) -> None:
    isolated_user_config.parent.mkdir(parents=True, exist_ok=True)
    isolated_user_config.write_text(
        "llm:\n  provider: anthropic\n  model_plan: claude-sonnet-4-6\n  model_narrate: claude-opus-4-7\n",
        encoding="utf-8",
    )

    class _StubCache:
        def has_checkpoint(self, _path: Path) -> bool:
            return True

    monkeypatch.setattr(
        "wiedunflow.adapters.sqlite_cache.SQLiteCache",
        lambda *_a, **_k: _StubCache(),
    )
    launched: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "wiedunflow.cli.menu._launch_pipeline",
        lambda payload: launched.append(payload),
    )
    io = FakeMenuIO(responses=[str(git_repo)])

    _run_resume_from_menu(io)

    assert len(launched) == 1
    assert launched[0]["repo_path"] == git_repo
    assert launched[0]["llm_provider"] == "anthropic"


def test_resume_aborts_silently_on_path_esc(
    capsys: pytest.CaptureFixture[str],
) -> None:
    io = FakeMenuIO(responses=[None])

    _run_resume_from_menu(io)

    out = capsys.readouterr().out
    assert "Resuming" not in out


# ---------------------------------------------------------------------------
# _run_help_from_menu
# ---------------------------------------------------------------------------


def test_help_renders_panel(capsys: pytest.CaptureFixture[str]) -> None:
    # Help renders a panel + waits on Enter before returning to the menu.
    io = FakeMenuIO(responses=[""])

    _run_help_from_menu(io)

    out = capsys.readouterr().out
    assert "WIEDUNFLOW MENU" in out
    assert "Generate tutorial" in out
    assert "WIEDUNFLOW_NO_MENU" in out


# ---------------------------------------------------------------------------
# Cost gate confirm_fn injection
# ---------------------------------------------------------------------------


def test_cost_gate_uses_confirm_fn_when_provided() -> None:
    from wiedunflow.cli.cost_estimator import estimate
    from wiedunflow.cli.cost_gate import prompt_cost_gate
    from wiedunflow.cli.output import init_console

    captured: list[str] = []

    def fake_confirm(message: str) -> bool:
        captured.append(message)
        return True

    console = init_console()
    est = estimate(symbols=10, lessons=5, clusters=2)

    result = prompt_cost_gate(
        console,
        estimate=est,
        auto_yes=False,
        prompt_disabled=False,
        is_tty=True,
        confirm_fn=fake_confirm,
    )

    assert result is True
    assert captured == ["Proceed?"]


def test_cost_gate_falls_back_to_click_when_confirm_fn_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from wiedunflow.cli.cost_estimator import estimate
    from wiedunflow.cli.cost_gate import prompt_cost_gate
    from wiedunflow.cli.output import init_console

    monkeypatch.setattr("click.confirm", lambda _msg, default=False: True)
    console = init_console()
    est = estimate(symbols=10, lessons=5, clusters=2)

    result = prompt_cost_gate(
        console,
        estimate=est,
        auto_yes=False,
        prompt_disabled=False,
        is_tty=True,
    )

    assert result is True


# ---------------------------------------------------------------------------
# SQLiteCache.has_checkpoint
# ---------------------------------------------------------------------------


def test_sqlite_has_checkpoint_returns_false_when_empty(tmp_path: Path) -> None:
    from wiedunflow.adapters.sqlite_cache import SQLiteCache

    cache = SQLiteCache(path=tmp_path / "cache.db")

    assert cache.has_checkpoint(tmp_path / "any-repo") is False


def test_sqlite_has_checkpoint_returns_true_after_save(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from wiedunflow.adapters.sqlite_cache import SQLiteCache
    from wiedunflow.entities.cache_entry import CheckpointEntry

    cache = SQLiteCache(path=tmp_path / "cache.db")
    repo = tmp_path / "myrepo"

    cache.save_checkpoint(
        CheckpointEntry(
            cache_key="k1",
            repo_abs=repo,
            commit_hash="abc123",
            lesson_id="l1",
            lesson_json="{}",
            concepts_snapshot="[]",
            model_used="claude-opus-4-7",
            cost_cents=10,
            created_at=datetime.now(UTC),
        )
    )

    assert cache.has_checkpoint(repo) is True
    assert cache.has_checkpoint(tmp_path / "other") is False
