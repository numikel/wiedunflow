# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Operator-visible failure events emitted by ``_run_pipeline``.

When a pipeline stage raises an unexpected exception, the CLI catches it,
writes ``run-report.json``, and prints a one-line error. Before this test,
the JSON log stream stayed silent during failures -- operators tailing
``--log-format=json`` had to poll the report file to detect crashes. The
guarantee is now: a structured ``unhandled_exception`` event with
``level=error`` is emitted *before* the report is written.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
import structlog
from click.testing import CliRunner

from wiedunflow.cli.main import cli as cli_main


@pytest.fixture(autouse=True)
def _reset_structlog() -> None:
    yield
    structlog.reset_defaults()


def _force_pipeline_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``generate_tutorial`` raise a generic exception during the run."""

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("forced failure for test")

    monkeypatch.setattr("wiedunflow.cli.main.generate_tutorial", _boom)


def _silence_sigint(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Noop:
        def __init__(self, *_a: object, **_k: object) -> None:
            import threading

            self.should_finish = threading.Event()

        def install(self) -> None:
            return None

        def restore(self) -> None:
            return None

    monkeypatch.setattr("wiedunflow.cli.main.SigintHandler", _Noop)


def _stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    from wiedunflow.adapters.fake_llm_provider import FakeLLMProvider

    monkeypatch.setattr(
        "wiedunflow.cli.main._build_llm_provider",
        lambda config, **_kwargs: FakeLLMProvider(),
    )


def _invoke(repo: str) -> Callable[[], object]:
    runner = CliRunner()
    return lambda: runner.invoke(
        cli_main, [repo, "--yes", "--log-format", "json"], standalone_mode=True
    )


def test_unhandled_exception_emits_structured_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Forced failure → JSON log stream must contain ``unhandled_exception`` event."""
    # Build a minimal repo on disk so click's path validation accepts it.
    repo = tmp_path / "tiny"
    repo.mkdir()
    (repo / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='tiny'\n", encoding="utf-8")

    _stub_llm(monkeypatch)
    _silence_sigint(monkeypatch)
    _force_pipeline_failure(monkeypatch)

    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli_main,
            [str(repo), "--yes", "--log-format", "json"],
            standalone_mode=True,
        )

    assert result.exit_code != 0, "forced failure must exit non-zero"

    # The structured event lands on stderr in JSON mode; click's CliRunner
    # captures stdout but stderr flows through capsys.
    captured = capsys.readouterr()
    stream = captured.err + captured.out + (result.output or "")

    matched = False
    for raw_line in stream.splitlines():
        candidate = raw_line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if payload.get("msg") == "unhandled_exception" and payload.get("level") == "error":
            matched = True
            break
    assert matched, (
        "expected one JSON log line with msg='unhandled_exception' level='error', "
        f"got stream:\n{stream}"
    )
