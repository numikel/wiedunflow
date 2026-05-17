# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from wiedunflow import __version__ as _wiedunflow_version
from wiedunflow.entities.code_ref import CodeRef
from wiedunflow.entities.lesson_manifest import LessonManifest, LessonSpec, ManifestMetadata
from wiedunflow.interfaces.ports import (
    AgentResult,
    AgentTurn,
    SpendMeterProto,
    ToolCall,
    ToolResult,
    ToolSpec,
)


class FakeLLMProvider:
    """Deterministic stub LLMProvider for testing — returns hardcoded responses.

    Produces a fixed 3-lesson manifest covering the tiny_repo calculator fixture:
      lesson-001: add function
      lesson-002: subtract function
      lesson-003: CLI entry point

    Implements the LLMProvider Protocol via duck typing (no explicit Protocol
    import needed — structural subtyping is verified at runtime via
    isinstance(fake, LLMProvider)).
    """

    def plan(self, outline: str) -> LessonManifest:
        """Return a hardcoded 3-lesson manifest regardless of the outline.

        Args:
            outline: Code-graph outline string (ignored in stub).

        Returns:
            A fixed LessonManifest covering the tiny_repo calculator fixture,
            with structured ``CodeRef`` entries and full ``ManifestMetadata``.
        """
        lessons = (
            LessonSpec(
                id="lesson-001",
                title="The add function",
                teaches="How to implement basic addition as a typed Python function",
                code_refs=(
                    CodeRef(
                        file_path=Path("calculator.py"),
                        symbol="calculator.add",
                        line_start=1,
                        line_end=3,
                        role="primary",
                    ),
                ),
            ),
            LessonSpec(
                id="lesson-002",
                title="The subtract function",
                teaches="How to implement basic subtraction and reuse the same pattern",
                prerequisites=("lesson-001",),
                code_refs=(
                    CodeRef(
                        file_path=Path("calculator.py"),
                        symbol="calculator.subtract",
                        line_start=5,
                        line_end=7,
                        role="primary",
                    ),
                ),
            ),
            LessonSpec(
                id="lesson-003",
                title="CLI entry point",
                teaches="How the main() function ties the calculator together",
                prerequisites=("lesson-001", "lesson-002"),
                code_refs=(
                    CodeRef(
                        file_path=Path("main.py"),
                        symbol="main.cli",
                        line_start=1,
                        line_end=10,
                        role="primary",
                    ),
                ),
            ),
        )
        return LessonManifest(
            schema_version="1.0.0",
            lessons=lessons,
            metadata=ManifestMetadata(
                schema_version="1.0.0",
                wiedunflow_version=_wiedunflow_version,
                total_lessons=len(lessons),
                generated_at=datetime(2026, 4, 20, 0, 0, 0, tzinfo=UTC),
                has_readme=True,
                doc_coverage=None,
            ),
        )

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
    ) -> AgentResult:
        """Return a deterministic stub AgentResult without calling any LLM.

        When ``mark_lesson_done`` is in the advertised tools (Orchestrator mode),
        the stub automatically calls it via ``tool_executor`` with a hardcoded
        narrative so the lesson pipeline completes without DEGRADED output.

        When called as a sub-agent (Researcher / Writer / Reviewer), there is no
        ``mark_lesson_done`` tool, so the stub returns a plain text response.

        Args:
            system: System prompt (ignored in stub).
            user: Initial user message.
            tools: Available tools — determines Orchestrator vs sub-agent mode.
            tool_executor: Tool executor called with ``mark_lesson_done`` in
                Orchestrator mode.
            model: Model identifier (ignored in stub).
            max_iterations: Iteration cap (ignored in stub).
            max_cost_usd: Budget cap (ignored in stub).
            spend_meter: Spend tracker (ignored in stub).

        Returns:
            An :class:`AgentResult` with deterministic content, ``stop_reason="end_turn"``,
            and ``iterations=1``.
        """
        stub_narrative = (
            "## Lesson\n\n"
            "This is a deterministic stub narrative generated by FakeLLMProvider. "
            "In production, this text is generated by a real LLM such as Anthropic Claude or "
            "OpenAI GPT-4o. The stub exists so the full pipeline can be validated end-to-end "
            "without consuming API credits and without flaky network dependencies. Because the "
            "content is fully deterministic, snapshot tests can pin exact output and reviewers "
            "can reason about structure without re-running the LLM.\n\n"
            "The implementation follows a straightforward pattern: accept typed parameters, "
            "perform the operation, and return a typed result. Python's type hints make this "
            "code self-documenting at the function signature level, and Pydantic validators "
            "keep runtime invariants honest without a large framework."
        )

        tool_names = {t.name for t in tools}
        if "mark_lesson_done" in tool_names:
            # Orchestrator mode — extract lesson_id from the user message and call
            # mark_lesson_done so the pipeline completes without DEGRADED output.
            lesson_id_match = re.search(r"lesson `([^`]+)`", user)
            lesson_id = lesson_id_match.group(1) if lesson_id_match else "lesson-unknown"
            mark_call = ToolCall(
                id="fake-mark-tc-001",
                name="mark_lesson_done",
                arguments={"lesson_id": lesson_id, "final_narrative": stub_narrative},
            )
            tool_executor(mark_call)
            stub_text = f"Lesson {lesson_id} completed by stub."
        else:
            stub_text = stub_narrative

        # Simulate token usage so SpendMeter.total_cost_usd > 0 in tests.
        # 100 input + 50 output tokens per agent call mirrors a minimal real call.
        if spend_meter is not None:
            spend_meter.charge(model=model, input_tokens=100, output_tokens=50)

        return AgentResult(
            final_text=stub_text,
            transcript=[
                AgentTurn(
                    role="assistant",
                    text=stub_text,
                    tool_calls=[],
                    tool_results=[],
                    input_tokens=100,
                    output_tokens=50,
                )
            ],
            total_input_tokens=100,
            total_output_tokens=50,
            total_cost_usd=0.0,
            stop_reason="end_turn",
            iterations=1,
        )
