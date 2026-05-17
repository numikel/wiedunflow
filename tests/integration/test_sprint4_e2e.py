# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sprint 4 end-to-end integration tests (T-004.INT).

Exercises the full CLI pipeline via :class:`click.testing.CliRunner` against
the ``tiny_repo`` fixture.  Uses :class:`FakeLLMProvider` variants to cover
the four terminal run states + closing-lesson contract + ``--cache-path``
override:

1. First run OK — status=ok, exit 0, run-report.json written.
2. DEGRADED — hallucinated symbols + short narration → > 30 % skipped,
   exit 2, status=degraded.
3. Failed — exception during ``narrate`` → exit 1, status=failed with
   stack_trace.
4. Interrupted — SigintHandler fires before Stage 1 → exit 130,
   status=interrupted.
5. Closing lesson — assert tutorial.html carries ``planned + 1`` lessons.
6. ``--cache-path`` override — SQLite file created at the requested path.

Scenarios that require Phase-4+ cache-hit wiring (``--resume``,
``--regenerate-plan``, incremental run < 5 min) are intentionally deferred:
the flags are recognised today but the pipeline does not yet read/write the
SQLite cache, so an e2e assertion would be a no-op.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from wiedunflow.adapters.fake_llm_provider import FakeLLMProvider
from wiedunflow.cli.main import cli as cli_main
from wiedunflow.entities.lesson import Lesson
from wiedunflow.entities.lesson_manifest import LessonManifest
from wiedunflow.interfaces.ports import AgentResult, AgentTurn, ToolCall

pytestmark = pytest.mark.integration

_TINY_REPO = Path(__file__).parent.parent / "fixtures" / "tiny_repo"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_repo_copy(tmp_path: Path) -> Path:
    """Clone ``tiny_repo`` into ``tmp_path`` so run-report writes are isolated."""
    dst = tmp_path / "tiny_repo"
    shutil.copytree(_TINY_REPO, dst)
    return dst


@pytest.fixture(autouse=True)
def _patch_llm_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: swap ``_build_llm_provider`` for the deterministic FakeLLMProvider.

    Individual tests override this via their own ``monkeypatch.setattr`` to
    inject degraded / exploding / hallucinating variants.
    """
    monkeypatch.setattr(
        "wiedunflow.cli.main._build_llm_provider",
        lambda config, **_kwargs: FakeLLMProvider(),
    )


@pytest.fixture(autouse=True)
def _patch_sigint_handler_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace :class:`SigintHandler` with a no-op so tests never install real signal handlers.

    Individual tests (e.g. the interrupted scenario) re-override with a pre-fired
    variant.  This keeps test isolation clean on Windows where ``signal.SIGINT``
    is partially supported.
    """

    class _NoopHandler:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.should_finish = threading.Event()

        def install(self) -> None:
            pass

        def restore(self) -> None:
            pass

    monkeypatch.setattr("wiedunflow.cli.main.SigintHandler", _NoopHandler)


def _invoke_cli(repo: Path, extra: list[str] | None = None) -> Any:
    """Run the CLI inside an isolated filesystem so ``tutorial.html`` lands in tmp cwd."""
    runner = CliRunner()
    argv = [str(repo), "--yes", *(extra or [])]
    with runner.isolated_filesystem():
        result = runner.invoke(cli_main, argv, standalone_mode=True)
    return result


def _load_report(repo: Path) -> dict[str, Any]:
    report_path = repo / ".wiedunflow" / "run-report.json"
    assert report_path.exists(), f"run-report.json missing at {report_path}"
    data: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    return data


# ---------------------------------------------------------------------------
# Custom FakeLLMProvider variants (per-scenario)
# ---------------------------------------------------------------------------


class _DegradedFakeLLM:
    """Routes every Researcher/Writer call to a hallucinated symbol response and an undersized narrative body, driving :func:`run_lesson` into the skip+placeholder branch via a Reviewer fatal verdict. Exercises the degraded-status end-to-end exit code 2 path."""

    def __init__(self) -> None:
        self._delegate = FakeLLMProvider()

    def plan(self, outline: str) -> LessonManifest:
        return self._delegate.plan(outline)

    def describe_symbol(self, symbol: object, context: str) -> str:
        return self._delegate.describe_symbol(symbol, context)  # type: ignore[arg-type]

    def narrate(self, spec_json: str, concepts_introduced: tuple[str, ...]) -> Lesson:
        spec = json.loads(spec_json)
        return Lesson(
            id=str(spec["id"]),
            title=str(spec["title"]),
            narrative="Short stub that is below the 150-word validator threshold.",
            code_refs=("hallucinated.fake.symbol",),
            status="generated",
        )

    def run_agent(
        self,
        *,
        system: str,
        user: str,
        tools: list[Any],
        tool_executor: Any,
        model: str,
        **kwargs: Any,
    ) -> AgentResult:
        tool_names = {t.name for t in tools}
        if "skip_lesson" in tool_names:
            match = re.search(r"lesson `([^`]+)`", user)
            lesson_id = match.group(1) if match else "lesson-unknown"
            tool_executor(
                ToolCall(
                    id="degraded-skip-001",
                    name="skip_lesson",
                    arguments={"lesson_id": lesson_id, "reason": "degraded test fixture"},
                )
            )
        stub = "Degraded stub."
        return AgentResult(
            final_text=stub,
            transcript=[
                AgentTurn(
                    role="assistant",
                    text=stub,
                    tool_calls=[],
                    tool_results=[],
                    input_tokens=0,
                    output_tokens=0,
                )
            ],
            total_input_tokens=0,
            total_output_tokens=0,
            total_cost_usd=0.0,
            stop_reason="end_turn",
            iterations=1,
        )


class _ExplodingFakeLLM:
    """Raises :class:`RuntimeError` during the very first ``narrate`` call.

    Drives the CLI's top-level ``except Exception`` branch → exit 1,
    ``run_report.status == "failed"`` with a populated ``stack_trace``.
    """

    def __init__(self) -> None:
        self._delegate = FakeLLMProvider()

    def plan(self, outline: str) -> LessonManifest:
        return self._delegate.plan(outline)

    def describe_symbol(self, symbol: object, context: str) -> str:
        return self._delegate.describe_symbol(symbol, context)  # type: ignore[arg-type]

    def narrate(self, spec_json: str, concepts_introduced: tuple[str, ...]) -> Lesson:
        raise RuntimeError("boom from _ExplodingFakeLLM test fixture")

    def run_agent(
        self,
        *,
        system: str,
        user: str,
        tools: list[Any],
        tool_executor: Any,
        model: str,
        **kwargs: Any,
    ) -> AgentResult:
        raise RuntimeError("boom from _ExplodingFakeLLM test fixture")


# ---------------------------------------------------------------------------
# Scenario 1 — First run OK
# ---------------------------------------------------------------------------


def test_first_run_writes_ok_run_report(tiny_repo_copy: Path, tmp_path: Path) -> None:
    """Happy path: FakeLLM + tiny_repo → exit 0, status=ok, report on disk."""
    result = _invoke_cli(
        tiny_repo_copy,
        extra=["--cache-path", str(tmp_path / "cache.db")],
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}"

    report = _load_report(tiny_repo_copy)
    assert report["status"] == "ok"
    assert report["schema_version"] == "1.0.0"
    assert report["total_planned_lessons"] >= 1
    assert report["skipped_lessons_count"] == 0
    assert report["failed_at_lesson"] is None
    assert report["stack_trace"] is None
    assert report["degraded_ratio"] == 0.0


# ---------------------------------------------------------------------------
# Scenario 2 — DEGRADED (> 30 % skipped → exit 2)
# ---------------------------------------------------------------------------


def test_degraded_run_exits_2_and_reports_degraded_status(
    tiny_repo_copy: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All lessons skipped → degraded_ratio=1.0 → exit 2."""
    monkeypatch.setattr(
        "wiedunflow.cli.main._build_llm_provider",
        lambda config, **_kwargs: _DegradedFakeLLM(),
    )
    result = _invoke_cli(
        tiny_repo_copy,
        extra=["--cache-path", str(tmp_path / "cache.db")],
    )
    assert result.exit_code == 2, (
        f"expected exit 2, got {result.exit_code} (output: {result.output})"
    )

    report = _load_report(tiny_repo_copy)
    assert report["status"] == "degraded"
    assert report["skipped_lessons_count"] == report["total_planned_lessons"]
    assert report["degraded_ratio"] > 0.30


# ---------------------------------------------------------------------------
# Scenario 3 — Failed (unhandled exception → exit 1, stack_trace captured)
# ---------------------------------------------------------------------------


def test_unhandled_exception_produces_failed_report_with_stack_trace(
    tiny_repo_copy: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM raises mid-pipeline → US-029: run-report status=failed + stack_trace, exit 1."""
    monkeypatch.setattr(
        "wiedunflow.cli.main._build_llm_provider",
        lambda config, **_kwargs: _ExplodingFakeLLM(),
    )
    result = _invoke_cli(
        tiny_repo_copy,
        extra=["--cache-path", str(tmp_path / "cache.db")],
    )
    assert result.exit_code == 1, (
        f"expected exit 1, got {result.exit_code} (output: {result.output})"
    )

    report = _load_report(tiny_repo_copy)
    assert report["status"] == "failed"
    assert report["stack_trace"] is not None
    assert "_ExplodingFakeLLM" in report["stack_trace"]
    assert "RuntimeError" in report["stack_trace"]
    assert report["failed_at_lesson"] is not None


# ---------------------------------------------------------------------------
# Scenario 4 — Interrupted (pre-fired SIGINT → exit 130)
# ---------------------------------------------------------------------------


def test_pre_fired_sigint_produces_interrupted_report(
    tiny_repo_copy: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SigintHandler whose ``should_finish`` is set before Stage 1 → US-027 path."""

    class _AlreadyFired:
        """Replaces SigintHandler with an instance pre-armed to abort."""

        def __init__(self, *_a: Any, **_k: Any) -> None:
            event = threading.Event()
            event.set()
            self.should_finish = event

        def install(self) -> None:
            pass

        def restore(self) -> None:
            pass

    monkeypatch.setattr("wiedunflow.cli.main.SigintHandler", _AlreadyFired)

    result = _invoke_cli(
        tiny_repo_copy,
        extra=["--cache-path", str(tmp_path / "cache.db")],
    )
    assert result.exit_code == 130, (
        f"expected exit 130, got {result.exit_code} (output: {result.output})"
    )

    report = _load_report(tiny_repo_copy)
    assert report["status"] == "interrupted"
    # Interrupted runs abort before Stage 6 completes → no per-lesson stats.
    assert report["stack_trace"] is None
    assert report["failed_at_lesson"] is None


# ---------------------------------------------------------------------------
# Scenario 5 — Closing lesson appended (+1 beyond cap)
# ---------------------------------------------------------------------------


def test_closing_lesson_is_appended_to_generated_tutorial(
    tiny_repo_copy: Path,
    tmp_path: Path,
) -> None:
    """tiny_repo planner returns 3 regular lessons → tutorial.html carries 4 total (US-049)."""
    runner = CliRunner()
    with runner.isolated_filesystem() as tmp_cwd:
        result = runner.invoke(
            cli_main,
            [
                str(tiny_repo_copy),
                "--yes",
                "--cache-path",
                str(tmp_path / "cache.db"),
            ],
            standalone_mode=True,
        )
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        # Default output location per v0.9.1+ UX: <repo>/wiedunflow-<repo-name>.html
        # (was: <cwd>/wiedunflow-<repo>.html — moved next to the analyzed repo so
        # the artifact lives with the source it documents).
        del tmp_cwd  # cwd is no longer the default location
        html = (tiny_repo_copy / f"wiedunflow-{tiny_repo_copy.name}.html").read_text(
            encoding="utf-8"
        )

    report = _load_report(tiny_repo_copy)
    # total_planned_lessons excludes the closing lesson (spec decision).
    planned = report["total_planned_lessons"]
    # Count lesson-* ids inside the embedded tutorial-data JSON block.
    regular_ids = html.count('"lesson-00')  # lesson-001, 002, 003 ...
    closing_ids = html.count('"lesson-closing"')
    assert regular_ids == planned, (
        f"regular lesson ids in HTML ({regular_ids}) != planned ({planned})"
    )
    assert closing_ids == 1, "closing lesson must appear exactly once"


# ---------------------------------------------------------------------------
# Scenario 6 — --cache-path override creates SQLite file at the requested path
# ---------------------------------------------------------------------------


def test_cache_path_override_creates_sqlite_at_requested_location(
    tiny_repo_copy: Path,
    tmp_path: Path,
) -> None:
    """US-020: --cache-path=<file> creates parent dir + DB at the requested location."""
    custom_cache = tmp_path / "sub" / "deeply" / "nested" / "cache.db"
    assert not custom_cache.parent.exists(), "precondition: parent dir must not exist"

    result = _invoke_cli(tiny_repo_copy, extra=["--cache-path", str(custom_cache)])
    assert result.exit_code == 0, f"CLI failed: {result.output}"

    assert custom_cache.exists(), f"SQLite file not created at {custom_cache}"
    assert custom_cache.stat().st_size > 0, "SQLite file is empty"
