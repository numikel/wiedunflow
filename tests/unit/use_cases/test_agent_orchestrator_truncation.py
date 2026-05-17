# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Tests for research-notes truncation in the orchestrator pipeline.

Covers _truncate_research_notes() directly and the integration into
_run_writer / _run_reviewer via the scripted fake LLMProvider.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from wiedunflow.interfaces.ports import (
    AgentResult,
    AgentTurn,
    SpendMeterProto,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from wiedunflow.use_cases.agent_orchestrator import _truncate_research_notes

# ---------------------------------------------------------------------------
# Minimal fake LLMProvider for truncation tests
# ---------------------------------------------------------------------------


class _FakeLLM:
    """Minimal LLMProvider that records whether run_agent was called for summarization."""

    def __init__(self, summary_text: str = "summarized notes") -> None:
        self.summarize_calls: list[dict[str, Any]] = []
        self.summary_text = summary_text
        self.should_raise: type[Exception] | None = None

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
        self.summarize_calls.append({"model": model, "user_length": len(user)})
        if self.should_raise is not None:
            raise self.should_raise("simulated failure")
        return AgentResult(
            final_text=self.summary_text,
            transcript=[
                AgentTurn(
                    role="assistant",
                    text=self.summary_text,
                    tool_calls=[],
                    input_tokens=50,
                    output_tokens=20,
                )
            ],
            total_input_tokens=50,
            total_output_tokens=20,
            total_cost_usd=0.001,
            stop_reason="end_turn",
            iterations=1,
        )

    def plan(self, outline: str) -> Any:  # type: ignore[return]
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Tests for _truncate_research_notes
# ---------------------------------------------------------------------------


class TestTruncateResearchNotes:
    """Unit tests for the three-tier truncation logic."""

    def _make_parts(self, sizes_kb: list[float]) -> list[str]:
        """Build a list of text parts with specified approximate sizes in KB."""
        parts = []
        for i, size_kb in enumerate(sizes_kb, start=1):
            # Each part is a numbered chunk of 'x' bytes padded to target size.
            content = f"# Note {i}\n\n" + "x" * max(0, int(size_kb * 1024) - 10)
            parts.append(content)
        return parts

    def test_under_cap_passthrough(self) -> None:
        """Total size under cap → notes returned unchanged without any LLM call."""
        parts = self._make_parts([2.0, 3.0])  # ~5 KB total
        llm = _FakeLLM()

        result = _truncate_research_notes(
            parts,
            cap_bytes=20 * 1024,
            summarize_threshold_bytes=30 * 1024,
            llm=llm,
            summarize_model="some-model",
            spend_meter=None,
        )

        assert llm.summarize_calls == [], "LLM must NOT be called when under cap"
        assert "# Note 1" in result
        assert "# Note 2" in result

    def test_fifo_drop_between_cap_and_threshold(self) -> None:
        """Over cap but under threshold → oldest parts dropped, no LLM call."""
        # Create 3 parts that together exceed the cap (25 KB) but stay under
        # the summarize threshold (30 KB).
        parts = self._make_parts([9.0, 9.0, 9.0])  # ~27 KB combined
        cap_kb = 20
        threshold_kb = 30
        llm = _FakeLLM()

        result = _truncate_research_notes(
            parts,
            cap_bytes=cap_kb * 1024,
            summarize_threshold_bytes=threshold_kb * 1024,
            llm=llm,
            summarize_model="some-model",
            spend_meter=None,
        )

        assert llm.summarize_calls == [], "No summarize call expected in FIFO-drop range"
        # Oldest note should have been dropped; youngest must be present.
        assert "# Note 3" in result
        # The result must fit within cap.
        assert len(result.encode("utf-8")) <= cap_kb * 1024

    def test_fifo_drop_preserves_youngest_notes(self) -> None:
        """FIFO drop keeps the most recent notes (highest index) over older ones."""
        parts = self._make_parts([8.0, 8.0, 8.0])  # ~24 KB > 20 KB cap
        llm = _FakeLLM()

        result = _truncate_research_notes(
            parts,
            cap_bytes=20 * 1024,
            summarize_threshold_bytes=30 * 1024,
            llm=llm,
            summarize_model="m",
            spend_meter=None,
        )

        # Note 1 (oldest) should have been discarded first.
        assert "# Note 1" not in result

    def test_summarize_called_over_threshold(self) -> None:
        """When total size exceeds summarize threshold, the LLM summarize call fires."""
        parts = self._make_parts([12.0, 12.0, 12.0])  # ~36 KB > 30 KB threshold
        expected_summary = "summarized notes content"
        llm = _FakeLLM(summary_text=expected_summary)

        result = _truncate_research_notes(
            parts,
            cap_bytes=20 * 1024,
            summarize_threshold_bytes=30 * 1024,
            llm=llm,
            summarize_model="mini-model",
            spend_meter=None,
        )

        assert len(llm.summarize_calls) == 1, "Exactly one summarize call expected"
        assert llm.summarize_calls[0]["model"] == "mini-model"
        # Summary was short enough to fit under cap → returned as-is.
        assert expected_summary in result

    def test_summarize_failure_falls_back_to_fifo(self) -> None:
        """When the summarize LLM call raises, FIFO drop is applied without propagating."""
        parts = self._make_parts([12.0, 12.0, 12.0])  # ~36 KB
        llm = _FakeLLM()
        llm.should_raise = RuntimeError

        # Must NOT raise — exception must be swallowed internally.
        result = _truncate_research_notes(
            parts,
            cap_bytes=20 * 1024,
            summarize_threshold_bytes=30 * 1024,
            llm=llm,
            summarize_model="flaky-model",
            spend_meter=None,
        )

        assert len(llm.summarize_calls) == 1, "Summarize was attempted"
        # FIFO fallback: result must fit within cap.
        assert len(result.encode("utf-8")) <= 20 * 1024

    def test_cap_zero_disables_truncation(self) -> None:
        """cap_bytes == 0 disables all truncation; full content returned."""
        parts = self._make_parts([15.0, 15.0, 15.0])  # ~45 KB
        llm = _FakeLLM()

        result = _truncate_research_notes(
            parts,
            cap_bytes=0,
            summarize_threshold_bytes=30 * 1024,
            llm=llm,
            summarize_model="m",
            spend_meter=None,
        )

        assert llm.summarize_calls == []
        assert "# Note 1" in result
        assert "# Note 2" in result
        assert "# Note 3" in result

    def test_single_part_under_cap_no_separator_artifact(self) -> None:
        """Single part under cap — no separator injected."""
        parts = ["# Only note\n\nContent here."]
        llm = _FakeLLM()

        result = _truncate_research_notes(
            parts,
            cap_bytes=20 * 1024,
            summarize_threshold_bytes=30 * 1024,
            llm=llm,
            summarize_model="m",
            spend_meter=None,
        )

        assert result == parts[0]

    def test_empty_parts_returns_empty_string(self) -> None:
        """Empty input list → empty string, no error."""
        llm = _FakeLLM()
        result = _truncate_research_notes(
            [],
            cap_bytes=20 * 1024,
            summarize_threshold_bytes=30 * 1024,
            llm=llm,
            summarize_model="m",
            spend_meter=None,
        )
        assert result == ""
