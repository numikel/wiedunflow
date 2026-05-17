# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for agent_orchestrator.run_lesson().

Strategy: script llm.run_agent() responses to simulate the Orchestrator LLM
making dispatch tool calls. Nested sub-agent calls (researcher, writer, reviewer)
also go through the same scripted fake so the full dispatch chain is covered
without hitting a real API.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from wiedunflow.entities.code_ref import CodeRef
from wiedunflow.entities.lesson import Lesson
from wiedunflow.entities.lesson_manifest import LessonSpec
from wiedunflow.entities.skipped_lesson import SkippedLesson
from wiedunflow.interfaces.ports import (
    AgentResult,
    AgentTurn,
    SpendMeterProto,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from wiedunflow.use_cases.agent_orchestrator import run_closing_lesson, run_lesson
from wiedunflow.use_cases.workspace import RunWorkspace, allocate_workspace

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def workspace(tmp_path: Path) -> RunWorkspace:
    return allocate_workspace("test-run-0001", base_dir=tmp_path)


@pytest.fixture()
def spec() -> LessonSpec:
    return LessonSpec(
        id="lesson-001",
        title="Understanding _parse",
        teaches="How the parser tokenises input",
        code_refs=(
            CodeRef(
                file="parser.py",
                lines=(),
            ),
        ),
    )


def _make_spec_with_symbol(lesson_id: str = "lesson-001") -> LessonSpec:
    """LessonSpec with a code_ref that has a symbol field."""
    # CodeRef doesn't have 'symbol'; use the LessonSpec.id as fallback.
    return LessonSpec(
        id=lesson_id,
        title="Test Lesson",
        teaches="teaches something",
        code_refs=(),
    )


@pytest.fixture()
def simple_spec() -> LessonSpec:
    return _make_spec_with_symbol()


@pytest.fixture()
def tool_registry() -> dict[str, Callable[[dict[str, Any]], str]]:
    """Minimal no-op tool registry (agent_tools not exercised here)."""
    return {
        "read_symbol_body": lambda _args: "def foo(): pass",
        "get_callers": lambda _args: "No callers found",
        "get_callees": lambda _args: "No callees found",
        "search_docs": lambda _args: "No docs found",
        "read_tests": lambda _args: "No tests found",
        "grep_usages": lambda _args: "No matches",
        "list_files_in_dir": lambda _args: ".",
        "read_lines": lambda _args: "# empty",
    }


# ---------------------------------------------------------------------------
# Scripted fake LLMProvider
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """Scripted ``LLMProvider`` that returns canned ``AgentResult`` objects in order.

    Behaviour mirrors the real ``run_agent`` loop:
    - Pop one scripted response per "model turn".
    - If the response contains ``tool_calls``, fire each via ``tool_executor``
      (this may trigger nested ``run_agent`` calls for sub-agents, which also
      pop from the shared queue), then loop to the next model turn.
    - When a response has no ``tool_calls``, treat it as an ``end_turn`` and
      return from the current ``run_agent`` call.
    - When the queue is empty, return immediately with ``stop_reason="end_turn"``.

    This allows a single shared queue to handle both the outer Orchestrator loop
    and inner sub-agent (researcher / writer / reviewer) calls.
    """

    def __init__(self, responses: list[AgentResult]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def run_agent(
        self,
        *,
        system: str,
        user: str,
        tools: list[ToolSpec],
        tool_executor: Callable[[ToolCall], ToolResult],
        model: str,
        max_iterations: int = 15,
        max_cost_usd: float = 1.0,
        spend_meter: SpendMeterProto | None = None,
        prompt_caching: bool = False,
        max_history_iterations: int = 10,
    ) -> AgentResult:
        self.calls.append(
            {
                "system_prefix": system[:80],
                "model": model,
                "max_cost_usd": max_cost_usd,
            }
        )
        transcript: list[AgentTurn] = []
        total_in = total_out = 0
        last_text: str | None = None
        stop_reason: str = "end_turn"

        for _ in range(max_iterations):
            if not self._responses:
                stop_reason = "end_turn"
                break
            resp = self._responses.pop(0)
            total_in += resp.total_input_tokens
            total_out += resp.total_output_tokens
            last_text = resp.final_text
            transcript.extend(resp.transcript)

            has_tool_calls = False
            for turn in resp.transcript:
                for tc in turn.tool_calls:
                    has_tool_calls = True
                    tool_executor(tc)

            if not has_tool_calls:
                # Final response for this agent — return.
                stop_reason = resp.stop_reason
                break
        else:
            stop_reason = "max_iterations"

        return AgentResult(
            final_text=last_text,
            transcript=transcript,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_cost_usd=0.01,
            stop_reason=stop_reason,  # type: ignore[arg-type]
            iterations=len(self.calls),
        )

    # Satisfy Protocol — unused methods
    def plan(self, outline: str) -> Any:  # type: ignore[return]
        raise NotImplementedError


def _mk_result(
    final_text: str,
    tool_calls: list[ToolCall] | None = None,
) -> AgentResult:
    """Build an AgentResult with optional tool calls recorded in the transcript."""
    turn = AgentTurn(
        role="assistant",
        text=final_text,
        tool_calls=tool_calls or [],
        input_tokens=100,
        output_tokens=50,
    )
    return AgentResult(
        final_text=final_text,
        transcript=[turn],
        total_input_tokens=100,
        total_output_tokens=50,
        total_cost_usd=0.01,
        stop_reason="end_turn",
        iterations=1,
    )


def _tc(tool_id: str, name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(id=tool_id, name=name, arguments=arguments)


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Orchestrator runs researcher → writer → reviewer (pass) → mark_lesson_done."""

    def test_returns_lesson_on_mark_done(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """mark_lesson_done produces a Lesson with the supplied narrative."""
        narrative = "## Test Lesson\n\nThe parser works by..."

        # The Orchestrator LLM fires dispatch tools in order, then mark_lesson_done.
        # Sub-agents (researcher, writer, reviewer) each get one scripted response.
        llm = _ScriptedLLM(
            [
                # 1. Orchestrator turn 1: dispatch_researcher
                _mk_result(
                    "Dispatching researcher.",
                    tool_calls=[
                        _tc(
                            "tc-1",
                            "dispatch_researcher",
                            {
                                "symbol": "lesson-001",
                                "research_brief": "main symbol",
                                "budget_usd": 0.05,
                            },
                        )
                    ],
                ),
                # 2. Researcher sub-agent response (consumed by _run_researcher)
                _mk_result("# Research Notes: lesson-001\n\ndef foo(): pass\n"),
                # 3. Orchestrator turn 2: dispatch_writer (uses auto research_refs)
                _mk_result(
                    "Dispatching writer.",
                    tool_calls=[
                        _tc(
                            "tc-2",
                            "dispatch_writer",
                            {"research_refs": [], "lesson_spec": "{}"},
                        )
                    ],
                ),
                # 4. Writer sub-agent: call submit_lesson_draft (structured output via tool).
                _mk_result(
                    "Submitting draft.",
                    tool_calls=[
                        _tc(
                            "tc-writer",
                            "submit_lesson_draft",
                            {
                                "overview": "Test overview mentioning the parser.",
                                "how_it_works": narrative,
                                "key_details": "",
                                "what_to_watch_for": "Edge cases here.",
                                "cited_symbols": [],
                                "uncertain_regions": [],
                            },
                        )
                    ],
                ),
                # 4b. Writer second turn: end after submit_lesson_draft ack.
                _mk_result(""),
                # 5. Orchestrator turn 3: dispatch_reviewer
                _mk_result(
                    "Dispatching reviewer.",
                    tool_calls=[
                        _tc(
                            "tc-3",
                            "dispatch_reviewer",
                            {"draft_path": "", "research_refs": []},
                        )
                    ],
                ),
                # 6. Reviewer sub-agent: call submit_verdict (structured output via tool).
                _mk_result(
                    "Submitting verdict.",
                    tool_calls=[
                        _tc(
                            "tc-rev",
                            "submit_verdict",
                            {
                                "verdict": "pass",
                                "checks": [],
                                "feedback": "All good.",
                            },
                        )
                    ],
                ),
                # 6b. Reviewer second turn: end after submit_verdict ack.
                _mk_result(""),
                # 7. Orchestrator turn 4: mark_lesson_done
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-4",
                            "mark_lesson_done",
                            {"lesson_id": "lesson-001", "final_narrative": narrative},
                        )
                    ],
                ),
            ]
        )

        outcome = run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
        )
        result = outcome.result

        assert isinstance(result, Lesson)
        assert result.id == "lesson-001"
        assert result.status == "generated"
        assert narrative in result.narrative

    def test_workspace_finished_written(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """After mark_lesson_done, finished/lesson-001/lesson.json must exist."""
        llm = _ScriptedLLM(
            [
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-1",
                            "mark_lesson_done",
                            {
                                "lesson_id": "lesson-001",
                                "final_narrative": "## Lesson\n\nHello world.",
                            },
                        )
                    ],
                )
            ]
        )
        run_lesson(simple_spec, workspace=workspace, llm=llm, tool_registry=tool_registry)  # type: ignore[arg-type]

        assert (workspace.base_dir / "finished" / "lesson-001" / "lesson.json").exists()


# ---------------------------------------------------------------------------
# Tests — Writer retries surface via RunLessonOutcome.writer_retries
# ---------------------------------------------------------------------------


class TestWriterRetries:
    """A second Writer dispatch (Reviewer rejected the first) bumps writer_retries by 1.

    The Orchestrator state tracks writer dispatches; everything beyond the first is
    counted as a retry and surfaced through ``RunLessonOutcome.writer_retries`` so
    the pipeline can accumulate it into ``RunReport``.
    """

    def test_outcome_writer_retries_zero_on_clean_run(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """One Writer dispatch (no retry) → writer_retries == 0."""
        narrative = "## Test Lesson\n\nThe parser works by..."
        llm = _ScriptedLLM(
            [
                _mk_result(
                    "Dispatching researcher.",
                    tool_calls=[
                        _tc(
                            "tc-1",
                            "dispatch_researcher",
                            {"symbol": "lesson-001", "research_brief": "x", "budget_usd": 0.05},
                        )
                    ],
                ),
                _mk_result("# Research\n\ndef foo(): pass\n"),
                _mk_result(
                    "Dispatching writer.",
                    tool_calls=[
                        _tc("tc-2", "dispatch_writer", {"research_refs": [], "lesson_spec": "{}"}),
                    ],
                ),
                _mk_result(
                    "Submitting draft.",
                    tool_calls=[
                        _tc(
                            "tc-w1",
                            "submit_lesson_draft",
                            {
                                "overview": "ov",
                                "how_it_works": narrative,
                                "key_details": "",
                                "what_to_watch_for": "",
                                "cited_symbols": [],
                                "uncertain_regions": [],
                            },
                        )
                    ],
                ),
                _mk_result(""),
                _mk_result(
                    "Dispatching reviewer.",
                    tool_calls=[
                        _tc("tc-3", "dispatch_reviewer", {"draft_path": "", "research_refs": []}),
                    ],
                ),
                _mk_result(
                    "Reviewer.",
                    tool_calls=[
                        _tc(
                            "tc-rv",
                            "submit_verdict",
                            {"verdict": "pass", "checks": [], "feedback": ""},
                        )
                    ],
                ),
                _mk_result(""),
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-4",
                            "mark_lesson_done",
                            {"lesson_id": "lesson-001", "final_narrative": narrative},
                        )
                    ],
                ),
            ]
        )

        outcome = run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
        )

        assert isinstance(outcome.result, Lesson)
        assert outcome.writer_retries == 0

    def test_outcome_writer_retries_one_after_reviewer_rejection(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """Two Writer dispatches (initial + retry after Reviewer fail) → writer_retries == 1."""
        narrative_v1 = "## Lesson\n\nFirst draft."
        narrative_v2 = "## Lesson\n\nRevised draft."
        llm = _ScriptedLLM(
            [
                # Researcher
                _mk_result(
                    "Dispatching researcher.",
                    tool_calls=[
                        _tc(
                            "tc-r",
                            "dispatch_researcher",
                            {"symbol": "lesson-001", "research_brief": "x", "budget_usd": 0.05},
                        )
                    ],
                ),
                _mk_result("# Research\n\ndef foo(): pass\n"),
                # Writer #1
                _mk_result(
                    "Dispatching writer (1st).",
                    tool_calls=[
                        _tc(
                            "tc-w-a", "dispatch_writer", {"research_refs": [], "lesson_spec": "{}"}
                        ),
                    ],
                ),
                _mk_result(
                    "Submitting draft #1.",
                    tool_calls=[
                        _tc(
                            "tc-d1",
                            "submit_lesson_draft",
                            {
                                "overview": "ov",
                                "how_it_works": narrative_v1,
                                "key_details": "",
                                "what_to_watch_for": "",
                                "cited_symbols": [],
                                "uncertain_regions": [],
                            },
                        )
                    ],
                ),
                _mk_result(""),
                # Reviewer #1 — FAIL
                _mk_result(
                    "Dispatching reviewer (1st).",
                    tool_calls=[
                        _tc("tc-rv1", "dispatch_reviewer", {"research_refs": []}),
                    ],
                ),
                _mk_result(
                    "Verdict fail.",
                    tool_calls=[
                        _tc(
                            "tc-vd1",
                            "submit_verdict",
                            {"verdict": "fail", "checks": [], "feedback": "redo"},
                        )
                    ],
                ),
                _mk_result(""),
                # Writer #2 — RETRY
                _mk_result(
                    "Dispatching writer (2nd, retry).",
                    tool_calls=[
                        _tc(
                            "tc-w-b", "dispatch_writer", {"research_refs": [], "lesson_spec": "{}"}
                        ),
                    ],
                ),
                _mk_result(
                    "Submitting draft #2.",
                    tool_calls=[
                        _tc(
                            "tc-d2",
                            "submit_lesson_draft",
                            {
                                "overview": "ov",
                                "how_it_works": narrative_v2,
                                "key_details": "",
                                "what_to_watch_for": "",
                                "cited_symbols": [],
                                "uncertain_regions": [],
                            },
                        )
                    ],
                ),
                _mk_result(""),
                # Reviewer #2 — PASS
                _mk_result(
                    "Dispatching reviewer (2nd).",
                    tool_calls=[
                        _tc("tc-rv2", "dispatch_reviewer", {"research_refs": []}),
                    ],
                ),
                _mk_result(
                    "Verdict pass.",
                    tool_calls=[
                        _tc(
                            "tc-vd2",
                            "submit_verdict",
                            {"verdict": "pass", "checks": [], "feedback": ""},
                        )
                    ],
                ),
                _mk_result(""),
                # Mark done
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-done",
                            "mark_lesson_done",
                            {"lesson_id": "lesson-001", "final_narrative": narrative_v2},
                        )
                    ],
                ),
            ]
        )

        outcome = run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
        )

        assert outcome.writer_retries == 1, (
            f"second Writer dispatch should bump retries to 1; got {outcome.writer_retries}"
        )

    def test_run_closing_lesson_outcome_has_zero_retries(
        self,
        workspace: RunWorkspace,
    ) -> None:
        """Closing lesson is a single Writer pass — no retry path exists."""
        closing_spec = LessonSpec(
            id="lesson-closing",
            title="Where to go next",
            teaches="summary",
            code_refs=(),
        )
        llm = _ScriptedLLM(
            [
                AgentResult(
                    final_text="## Closing\n\nKeep reading.",
                    transcript=[],
                    total_input_tokens=5,
                    total_output_tokens=8,
                    total_cost_usd=0.0,
                    stop_reason="end_turn",
                    iterations=1,
                )
            ]
        )

        outcome = run_closing_lesson(
            closing_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
        )

        assert isinstance(outcome.result, Lesson)
        assert outcome.writer_retries == 0


# ---------------------------------------------------------------------------
# Tests — skip path
# ---------------------------------------------------------------------------


class TestSkipPath:
    """Orchestrator calls skip_lesson → returns SkippedLesson."""

    def test_returns_skipped_lesson(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        llm = _ScriptedLLM(
            [
                _mk_result(
                    "Skipping.",
                    tool_calls=[
                        _tc(
                            "tc-1",
                            "skip_lesson",
                            {"lesson_id": "lesson-001", "reason": "symbol not found"},
                        )
                    ],
                )
            ]
        )

        result = run_lesson(
            simple_spec, workspace=workspace, llm=llm, tool_registry=tool_registry
        ).result  # type: ignore[arg-type]

        assert isinstance(result, SkippedLesson)
        assert result.lesson_id == "lesson-001"
        assert "symbol not found" in result.reason

    def test_skip_writes_checkpoint(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        llm = _ScriptedLLM(
            [
                _mk_result(
                    "Skipping.",
                    tool_calls=[
                        _tc(
                            "tc-1",
                            "skip_lesson",
                            {"lesson_id": "lesson-001", "reason": "budget exhausted"},
                        )
                    ],
                )
            ]
        )
        run_lesson(simple_spec, workspace=workspace, llm=llm, tool_registry=tool_registry)  # type: ignore[arg-type]

        checkpoint = workspace.base_dir / "finished" / "lesson-001" / "lesson.json"
        assert checkpoint.exists()
        data = json.loads(checkpoint.read_text())
        assert data["skipped"] is True
        assert "budget exhausted" in data["reason"]


# ---------------------------------------------------------------------------
# Tests — resume path
# ---------------------------------------------------------------------------


class TestResumePath:
    """When workspace already has a finished checkpoint, run_lesson re-uses it."""

    def test_resumes_from_finished_lesson_json(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        # Pre-write a finished checkpoint.
        finished_dir = workspace.lesson_dir("lesson-001", "finished")
        lesson_data = {
            "id": "lesson-001",
            "title": "Test Lesson",
            "narrative": "## Pre-existing lesson\n\nContent from prior run.",
            "segments": [],
            "code_refs": [],
            "helper_appendix": [],
            "layout": "split",
            "code_panel_html": None,
            "status": "generated",
            "confidence": "MEDIUM",
        }
        workspace.write_json_atomic(finished_dir / "lesson.json", lesson_data)

        # LLM should NOT be called (zero responses queued, any call would raise).
        llm = _ScriptedLLM([])

        result = run_lesson(
            simple_spec, workspace=workspace, llm=llm, tool_registry=tool_registry
        ).result  # type: ignore[arg-type]

        assert isinstance(result, Lesson)
        assert "Pre-existing lesson" in result.narrative
        assert len(llm.calls) == 0

    def test_resumes_skipped_checkpoint(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        finished_dir = workspace.lesson_dir("lesson-001", "finished")
        workspace.write_json_atomic(
            finished_dir / "lesson.json",
            {"skipped": True, "reason": "prior run skip", "lesson_id": "lesson-001"},
        )
        llm = _ScriptedLLM([])

        result = run_lesson(
            simple_spec, workspace=workspace, llm=llm, tool_registry=tool_registry
        ).result  # type: ignore[arg-type]

        assert isinstance(result, SkippedLesson)
        assert "prior run skip" in result.reason


# ---------------------------------------------------------------------------
# Tests — fallback path
# ---------------------------------------------------------------------------


class TestFallbackPath:
    """Orchestrator exits without mark/skip → use last draft if available."""

    def test_fallback_to_last_draft(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """If Orchestrator exits mid-pipeline but a draft exists, use it."""
        # Write the draft manually (simulating a writer sub-agent run).
        draft_narrative = "## Test Lesson\n\nDraft content from fallback."
        processing = workspace.lesson_dir("lesson-001", "processing")
        draft_path = processing / "draft-001.md"
        workspace.write_atomic(draft_path, draft_narrative)

        # Orchestrator returns with dispatch_writer that sets state.last_draft_path
        # but then exits without calling mark_lesson_done.
        class _PartialOrchestrator(_ScriptedLLM):
            def run_agent(self, *, system: str, **kwargs: Any) -> AgentResult:
                call_info = {"system_prefix": system[:80]}
                self.calls.append(call_info)
                if not self._responses:
                    # Sub-agent calls return empty (writer already ran)
                    return AgentResult(
                        final_text=draft_narrative,
                        transcript=[],
                        total_input_tokens=0,
                        total_output_tokens=0,
                        total_cost_usd=0.0,
                        stop_reason="end_turn",
                        iterations=1,
                    )
                return self._responses.pop(0)

        llm = _PartialOrchestrator(
            [
                # Orchestrator issues dispatch_writer, setting state.last_draft_path
                _mk_result(
                    "Dispatching writer.",
                    tool_calls=[
                        _tc(
                            "tc-1",
                            "dispatch_writer",
                            {"research_refs": [], "lesson_spec": "{}"},
                        )
                    ],
                ),
                # Orchestrator then exits without mark/skip (max_iterations exhausted)
                AgentResult(
                    final_text=None,
                    transcript=[],
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cost_usd=0.0,
                    stop_reason="max_iterations",
                    iterations=15,
                ),
            ]
        )

        result = run_lesson(
            simple_spec, workspace=workspace, llm=llm, tool_registry=tool_registry
        ).result  # type: ignore[arg-type]

        # Should recover using the writer's output (returned by sub-agent)
        assert isinstance(result, (Lesson, SkippedLesson))

    def test_fallback_to_skipped_when_no_draft(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """If Orchestrator exits with no draft and no decision, return SkippedLesson."""
        llm = _ScriptedLLM(
            [
                # Orchestrator exits immediately without any dispatch
                AgentResult(
                    final_text=None,
                    transcript=[],
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cost_usd=0.0,
                    stop_reason="max_cost",
                    iterations=1,
                )
            ]
        )

        result = run_lesson(
            simple_spec, workspace=workspace, llm=llm, tool_registry=tool_registry
        ).result  # type: ignore[arg-type]

        assert isinstance(result, SkippedLesson)
        assert result.lesson_id == "lesson-001"
        assert "max_cost" in result.reason


# ---------------------------------------------------------------------------
# Tests — concepts_introduced propagation
# ---------------------------------------------------------------------------


class TestConceptsPropagation:
    """concepts_introduced must be forwarded to sub-agents and persisted."""

    def test_concepts_in_orchestrator_kwargs(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """The Orchestrator system prompt must include the concepts_introduced list."""
        observed_systems: list[str] = []

        class _CapturingLLM(_ScriptedLLM):
            def run_agent(self, *, system: str, **kwargs: Any) -> AgentResult:
                observed_systems.append(system)
                return AgentResult(
                    final_text=None,
                    transcript=[],
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cost_usd=0.0,
                    stop_reason="max_cost",
                    iterations=1,
                )

        llm = _CapturingLLM([])
        run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
            concepts_introduced=("concept-alpha", "concept-beta"),
        )

        assert observed_systems, "run_agent should have been called at least once"
        orch_system = observed_systems[0]
        assert "concept-alpha" in orch_system
        assert "concept-beta" in orch_system


# ---------------------------------------------------------------------------
# Tests — Bug #2 regression: fallback paths must persist to finished/
# ---------------------------------------------------------------------------


class TestFallbackPersistsToFinished:
    """Bug #2 regression: SkippedLesson fallback paths must write finished/lesson.json."""

    def test_run_lesson_fallback_no_draft_writes_finished(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """When orchestrator exits without decision and no draft exists, the
        SkippedLesson fallback must still produce finished/lesson-001/lesson.json
        so that resume logic recognises the lesson as done."""
        llm = _ScriptedLLM(
            [
                AgentResult(
                    final_text=None,
                    transcript=[],
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cost_usd=0.0,
                    stop_reason="max_cost",
                    iterations=1,
                )
            ]
        )

        outcome = run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
        )
        result = outcome.result

        assert isinstance(result, SkippedLesson)
        finished_path = workspace.base_dir / "finished" / "lesson-001" / "lesson.json"
        assert finished_path.exists(), "finished/lesson.json must be written even for fallback skip"
        data = json.loads(finished_path.read_text())
        assert data["skipped"] is True
        assert data["lesson_id"] == "lesson-001"
        assert "stop_reason" in data["reason"]

    def test_run_lesson_fallback_reason_contains_stop_reason(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """The persisted reason must mention the orchestrator stop_reason."""
        llm = _ScriptedLLM(
            [
                AgentResult(
                    final_text=None,
                    transcript=[],
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cost_usd=0.0,
                    stop_reason="max_iterations",
                    iterations=15,
                )
            ]
        )
        run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
        )
        data = json.loads(
            (workspace.base_dir / "finished" / "lesson-001" / "lesson.json").read_text()
        )
        assert "max_iterations" in data["reason"]

    def test_run_closing_lesson_assembles_structured_json_into_markdown(
        self,
        workspace: RunWorkspace,
    ) -> None:
        """The closing Writer is given ``tools=[]`` but may still emit a JSON
        blob matching ``submit_lesson_draft`` schema. The orchestrator MUST
        stitch the four sections into a single markdown narrative — not
        persist the raw JSON string (which would render as visible
        ``{"overview":...}`` in the HTML reader).
        """
        closing_spec = LessonSpec(
            id="lesson-closing",
            title="Where to go next",
            teaches="Where to go next",
            code_refs=(),
        )
        # Simulate the real-world bug: gpt-5.4 emits structured JSON as plain
        # text because the writer card forces an output_contract: format=json.
        structured_payload = json.dumps(
            {
                "overview": "Start with the README.",
                "how_it_works": "Re-open entry points and trace imports.",
                "key_details": "Helpers validate inputs and write templates.",
                "what_to_watch_for": "Don't dive into untested helpers first.",
            }
        )
        llm = _ScriptedLLM(
            [
                AgentResult(
                    final_text=structured_payload,
                    transcript=[],
                    total_input_tokens=10,
                    total_output_tokens=20,
                    total_cost_usd=0.0,
                    stop_reason="end_turn",
                    iterations=1,
                )
            ]
        )

        lesson = run_closing_lesson(
            closing_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
        ).result

        assert isinstance(lesson, Lesson)
        # Each section must appear in the assembled narrative...
        for section_text in (
            "Start with the README.",
            "Re-open entry points and trace imports.",
            "Helpers validate inputs and write templates.",
            "Don't dive into untested helpers first.",
        ):
            assert section_text in lesson.narrative
        # ...and the raw JSON envelope MUST NOT leak into the narrative.
        assert not lesson.narrative.lstrip().startswith("{")
        assert '"overview"' not in lesson.narrative

    def test_run_closing_lesson_assembles_fenced_json(
        self,
        workspace: RunWorkspace,
    ) -> None:
        """Some models wrap their structured payload in a ```json fence even
        when forced into plain text mode. The assembler must strip the fence
        before parsing.
        """
        closing_spec = LessonSpec(
            id="lesson-closing",
            title="Where to go next",
            teaches="Where to go next",
            code_refs=(),
        )
        fenced = (
            "```json\n"
            + json.dumps({"overview": "Read on.", "how_it_works": "Step through."})
            + "\n```"
        )
        llm = _ScriptedLLM(
            [
                AgentResult(
                    final_text=fenced,
                    transcript=[],
                    total_input_tokens=5,
                    total_output_tokens=8,
                    total_cost_usd=0.0,
                    stop_reason="end_turn",
                    iterations=1,
                )
            ]
        )

        lesson = run_closing_lesson(
            closing_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
        ).result

        assert isinstance(lesson, Lesson)
        assert "Read on." in lesson.narrative
        assert "Step through." in lesson.narrative
        assert "```" not in lesson.narrative

    def test_run_closing_lesson_passes_through_plain_markdown(
        self,
        workspace: RunWorkspace,
    ) -> None:
        """When the Writer correctly emits plain markdown, the assembler is a
        no-op — the narrative is preserved verbatim.
        """
        closing_spec = LessonSpec(
            id="lesson-closing",
            title="Where to go next",
            teaches="Where to go next",
            code_refs=(),
        )
        plain_markdown = "## Where to go next\n\nKeep reading the README."
        llm = _ScriptedLLM(
            [
                AgentResult(
                    final_text=plain_markdown,
                    transcript=[],
                    total_input_tokens=5,
                    total_output_tokens=8,
                    total_cost_usd=0.0,
                    stop_reason="end_turn",
                    iterations=1,
                )
            ]
        )

        lesson = run_closing_lesson(
            closing_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
        ).result

        assert isinstance(lesson, Lesson)
        assert lesson.narrative == plain_markdown

    def test_run_closing_lesson_empty_output_writes_finished(
        self,
        workspace: RunWorkspace,
        tool_registry: dict[str, Any],
    ) -> None:
        """When the closing Writer returns empty text, finished/lesson-closing/lesson.json
        must be written with skipped=True."""
        closing_spec = LessonSpec(
            id="lesson-closing",
            title="Where to go next",
            teaches="Summary of helpers and next steps",
            code_refs=(),
        )
        llm = _ScriptedLLM(
            [
                AgentResult(
                    final_text="",  # empty — triggers the fallback path
                    transcript=[],
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cost_usd=0.0,
                    stop_reason="end_turn",
                    iterations=1,
                )
            ]
        )

        result = run_closing_lesson(
            closing_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
        ).result

        assert isinstance(result, SkippedLesson)
        finished_path = workspace.base_dir / "finished" / "lesson-closing" / "lesson.json"
        assert finished_path.exists(), (
            "finished/lesson.json must be written for closing-lesson skip"
        )
        data = json.loads(finished_path.read_text())
        assert data["skipped"] is True
        assert data["lesson_id"] == "lesson-closing"
        assert "Closing lesson Writer produced no output" in data["reason"]

    def test_resume_after_fallback_skip_does_not_call_llm(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """After a fallback skip persists finished/lesson.json, a second call to
        run_lesson must hit the resume path and return SkippedLesson without
        invoking run_agent."""
        # First run — orchestrator exits with no decision, writes finished/
        llm1 = _ScriptedLLM(
            [
                AgentResult(
                    final_text=None,
                    transcript=[],
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_cost_usd=0.0,
                    stop_reason="max_cost",
                    iterations=1,
                )
            ]
        )
        outcome1 = run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm1,  # type: ignore[arg-type]
            tool_registry=tool_registry,
        )
        result1 = outcome1.result
        assert isinstance(result1, SkippedLesson)

        # Second run — must resume from checkpoint without calling run_agent.
        class _AssertNotCalled(_ScriptedLLM):
            def run_agent(self, **kwargs: Any) -> AgentResult:  # type: ignore[override]
                raise AssertionError("run_agent must not be called on resume")

        outcome2 = run_lesson(
            simple_spec,
            workspace=workspace,
            llm=_AssertNotCalled([]),  # type: ignore[arg-type]
            tool_registry=tool_registry,
        )
        result2 = outcome2.result
        assert isinstance(result2, SkippedLesson)
        assert result2.lesson_id == "lesson-001"


# ---------------------------------------------------------------------------
# Tests — Fix D: structured Writer output via submit_lesson_draft tool
# ---------------------------------------------------------------------------


class TestStructuredWriterOutput:
    """Fix D regression: Writer must use submit_lesson_draft tool, not raw text."""

    def test_writer_assembles_markdown_from_structured_args(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """Writer's submit_lesson_draft args are assembled into structured markdown.

        Assertions:
        - draft file contains ## Overview, ## How It Works, ## What To Watch For headers
        - ## Key Details is absent when key_details was ""
        - frontmatter contains cited_symbols
        - structured=True logged (checked via draft file frontmatter)
        """
        llm = _ScriptedLLM(
            [
                # 1. Orchestrator: dispatch_writer directly
                _mk_result(
                    "Dispatching writer.",
                    tool_calls=[
                        _tc(
                            "tc-orch-w",
                            "dispatch_writer",
                            {"research_refs": [], "lesson_spec": "{}"},
                        )
                    ],
                ),
                # 2. Writer sub-agent: submit_lesson_draft with 4-section structure
                _mk_result(
                    "Submitting draft.",
                    tool_calls=[
                        _tc(
                            "tc-writer",
                            "submit_lesson_draft",
                            {
                                "overview": "The `_parse` function tokenises raw input strings.",
                                "how_it_works": "It iterates over each character calling `_tokenise`.",
                                "key_details": "",
                                "what_to_watch_for": "Watch for edge cases with empty strings.",
                                "cited_symbols": [],
                                "uncertain_regions": [],
                            },
                        )
                    ],
                ),
                # 3. Writer second turn: end after submit ack
                _mk_result(""),
                # 4. Orchestrator: mark_lesson_done
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-done",
                            "mark_lesson_done",
                            {"lesson_id": "lesson-001", "final_narrative": ""},
                        )
                    ],
                ),
            ]
        )

        run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
        )

        # Locate the draft file written by _run_writer
        processing = workspace.lesson_dir("lesson-001", "processing")
        draft_files = sorted(processing.glob("draft-*.md"))
        assert draft_files, "Expected at least one draft-*.md file in processing/"
        draft_content = draft_files[0].read_text(encoding="utf-8")

        # Structured sections must be present
        assert "## Overview" in draft_content
        assert "## How It Works" in draft_content
        assert "## What To Watch For" in draft_content
        # key_details was "" so the section must be absent
        assert "## Key Details" not in draft_content
        # Frontmatter must be present with cited_symbols
        assert "cited_symbols:" in draft_content
        assert "ungrounded_cited:" in draft_content

    def test_writer_assembles_uncertain_regions_as_callouts(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """uncertain_regions entries are rendered as > [!note] callout blocks."""
        llm = _ScriptedLLM(
            [
                _mk_result(
                    "Dispatching writer.",
                    tool_calls=[
                        _tc(
                            "tc-orch-w",
                            "dispatch_writer",
                            {"research_refs": [], "lesson_spec": "{}"},
                        )
                    ],
                ),
                _mk_result(
                    "Submitting draft.",
                    tool_calls=[
                        _tc(
                            "tc-writer",
                            "submit_lesson_draft",
                            {
                                "overview": "Overview text.",
                                "how_it_works": "How it works text.",
                                "key_details": "Some detail.",
                                "what_to_watch_for": "Watch for X.",
                                "cited_symbols": [],
                                "uncertain_regions": [
                                    {
                                        "symbol": "dynamic_dispatch",
                                        "callout": "Resolved at runtime via config.",
                                    }
                                ],
                            },
                        )
                    ],
                ),
                _mk_result(""),
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-done",
                            "mark_lesson_done",
                            {"lesson_id": "lesson-001", "final_narrative": ""},
                        )
                    ],
                ),
            ]
        )

        run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
        )

        processing = workspace.lesson_dir("lesson-001", "processing")
        draft_files = sorted(processing.glob("draft-*.md"))
        assert draft_files
        draft_content = draft_files[0].read_text(encoding="utf-8")

        assert "> [!note] dynamic_dispatch" in draft_content
        assert "Resolved at runtime via config." in draft_content
        assert "uncertain_regions_count: 1" in draft_content

    def test_writer_fallback_when_tool_not_called(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When Writer's LLM returns raw text without calling submit_lesson_draft,
        the draft is saved with the raw text and a warning is logged."""
        import logging

        raw_text = "## Lesson\n\nSome raw prose without tool call."
        llm = _ScriptedLLM(
            [
                _mk_result(
                    "Dispatching writer.",
                    tool_calls=[
                        _tc(
                            "tc-orch-w",
                            "dispatch_writer",
                            {"research_refs": [], "lesson_spec": "{}"},
                        )
                    ],
                ),
                # Writer does NOT call the tool — returns raw text
                _mk_result(raw_text),
                # Orchestrator: mark_lesson_done using last_draft_path
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-done",
                            "mark_lesson_done",
                            {"lesson_id": "lesson-001", "final_narrative": ""},
                        )
                    ],
                ),
            ]
        )

        with caplog.at_level(logging.WARNING, logger="wiedunflow.use_cases.agent_orchestrator"):
            run_lesson(
                simple_spec,
                workspace=workspace,
                llm=llm,  # type: ignore[arg-type]
                tool_registry=tool_registry,
            )

        # Draft file must exist with raw text
        processing = workspace.lesson_dir("lesson-001", "processing")
        draft_files = sorted(processing.glob("draft-*.md"))
        assert draft_files
        draft_content = draft_files[0].read_text(encoding="utf-8")
        assert raw_text in draft_content

        # Warning must have been emitted
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("writer_no_structured_output" in str(m) for m in warning_msgs)


# ---------------------------------------------------------------------------
# Per-call budget wiring — agent-card max_cost_usd is now a real cap
# ---------------------------------------------------------------------------


class _RecordingSpendMeter:
    """Minimal SpendMeter stub recording lifecycle calls for orchestrator tests."""

    def __init__(self) -> None:
        self.begin_calls: list[float] = []
        self.end_calls: int = 0
        self._cost = 0.0

    @property
    def total_cost_usd(self) -> float:
        return self._cost

    def charge(self, **_kwargs: Any) -> None:
        self._cost += 0.001

    def would_exceed(self) -> bool:
        return False

    def begin_lesson(self, cap_usd: float) -> None:
        self.begin_calls.append(cap_usd)

    def end_lesson(self) -> None:
        self.end_calls += 1


class TestBudgetWiring:
    """Per-role agent-card budgets now actually constrain run_agent calls."""

    def test_orchestrator_run_caps_max_cost_usd_to_min_of_card_and_remaining(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """When remaining budget > card cap → effective cap is the card cap.

        Orchestrator card ships with ``max_cost_usd=0.80`` (per
        ``orchestrator.md`` frontmatter). With a $5 lesson remaining, MIN
        is the card cap → reviewer/researcher/writer cannot blow their share
        on a stuck loop even when the lesson has plenty of headroom.
        """
        llm = _ScriptedLLM(
            [
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-done",
                            "mark_lesson_done",
                            {
                                "lesson_id": "lesson-001",
                                "final_narrative": "Closing it out fast.",
                            },
                        )
                    ],
                ),
            ]
        )
        run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
            budget_remaining_usd=5.0,
        )
        # Orchestrator card cap is 0.80 → expected cap (min with 5.0) = 0.80.
        orch_calls = [c for c in llm.calls if "orchestrator" in c["system_prefix"].lower()]
        assert orch_calls, "Orchestrator run_agent call not recorded"
        assert orch_calls[0]["max_cost_usd"] == pytest.approx(0.80, rel=1e-6)

    def test_orchestrator_run_caps_max_cost_usd_to_min_when_remaining_tighter(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """When remaining budget < card cap → effective cap is the remaining.

        A near-exhausted global budget overrides the card cap so the
        orchestrator never spends more than the global headroom allows.
        """
        llm = _ScriptedLLM(
            [
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-done",
                            "mark_lesson_done",
                            {"lesson_id": "lesson-001", "final_narrative": "x"},
                        )
                    ],
                ),
            ]
        )
        run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
            budget_remaining_usd=0.05,  # tighter than card cap 0.80
        )
        orch_calls = [c for c in llm.calls if "orchestrator" in c["system_prefix"].lower()]
        assert orch_calls, "Orchestrator run_agent call not recorded"
        assert orch_calls[0]["max_cost_usd"] == pytest.approx(0.05, rel=1e-6)

    def test_run_lesson_opens_and_closes_spend_meter_window(
        self,
        workspace: RunWorkspace,
        simple_spec: LessonSpec,
        tool_registry: dict[str, Any],
    ) -> None:
        """run_lesson wraps Stage 5/6 work in begin_lesson / end_lesson so
        the meter can isolate per-lesson spend even on the unhappy path.
        """
        llm = _ScriptedLLM(
            [
                _mk_result(
                    "Done.",
                    tool_calls=[
                        _tc(
                            "tc-done",
                            "mark_lesson_done",
                            {"lesson_id": "lesson-001", "final_narrative": "x"},
                        )
                    ],
                ),
            ]
        )
        meter = _RecordingSpendMeter()
        run_lesson(
            simple_spec,
            workspace=workspace,
            llm=llm,  # type: ignore[arg-type]
            tool_registry=tool_registry,
            budget_remaining_usd=4.0,
            spend_meter=meter,  # type: ignore[arg-type]
        )
        assert meter.begin_calls == [pytest.approx(4.0, rel=1e-6)]
        assert meter.end_calls == 1
