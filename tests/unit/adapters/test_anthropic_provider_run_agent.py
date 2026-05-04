# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for AnthropicProvider.run_agent()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from anthropic.types import TextBlock, ToolUseBlock

from wiedunflow.adapters.anthropic_provider import AnthropicProvider
from wiedunflow.interfaces.ports import AgentResult, AgentTurn, ToolCall, ToolResult, ToolSpec
from wiedunflow.use_cases.spend_meter import SpendMeter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_provider(monkeypatch: pytest.MonkeyPatch, mock_cls: MagicMock) -> AnthropicProvider:
    """Construct an AnthropicProvider with a mocked Anthropic client."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    mock_cls.return_value = MagicMock()
    return AnthropicProvider()


def _mk_text_response(
    text: str = "hello",
    stop_reason: str = "end_turn",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> MagicMock:
    """Build a minimal mock anthropic.Message with a TextBlock."""
    resp = MagicMock()
    resp.content = [TextBlock(type="text", text=text)]
    resp.stop_reason = stop_reason
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


def _mk_tool_use_response(
    tool_use_id: str,
    tool_name: str,
    tool_input: dict,  # type: ignore[type-arg]
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> MagicMock:
    """Build a mock anthropic.Message containing a ToolUseBlock."""
    resp = MagicMock()
    resp.content = [ToolUseBlock(type="tool_use", id=tool_use_id, name=tool_name, input=tool_input)]
    resp.stop_reason = "tool_use"
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    return resp


def _simple_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="fetch_data",
        description="Fetches some data",
        input_schema={"type": "object", "properties": {}, "required": []},
    )


def _passthrough_executor(call: ToolCall) -> ToolResult:
    return ToolResult(tool_call_id=call.id, content=f"result-of-{call.name}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_no_tools_returns_end_turn(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Model returns stop_reason=end_turn with no tool calls → stop_reason='end_turn', iterations=1."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = _mk_text_response(
        text="Done", stop_reason="end_turn"
    )

    result = provider.run_agent(
        system="sys",
        user="do something",
        tools=[],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
    )

    assert isinstance(result, AgentResult)
    assert result.stop_reason == "end_turn"
    assert result.iterations == 1
    assert result.final_text == "Done"
    assert len(result.transcript) == 1
    assert result.transcript[0].role == "assistant"
    assert result.transcript[0].tool_calls == []


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_single_tool_call(mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Model calls 1 tool, executor returns result, model then responds with text."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    # First response: tool_use; second response: end_turn
    mock_client.messages.create.side_effect = [
        _mk_tool_use_response("tu-1", "fetch_data", {"key": "val"}),
        _mk_text_response(text="Final answer", stop_reason="end_turn"),
    ]

    result = provider.run_agent(
        system="sys",
        user="get data",
        tools=[_simple_tool_spec()],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
    )

    assert result.stop_reason == "end_turn"
    assert result.iterations == 2
    assert result.final_text == "Final answer"
    assert len(result.transcript) == 2
    # First turn had a tool call
    assert result.transcript[0].tool_calls[0].name == "fetch_data"
    assert result.transcript[0].tool_calls[0].arguments == {"key": "val"}
    assert mock_client.messages.create.call_count == 2


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_max_iterations_reached(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Model always requests a tool call; loop stops at max_iterations → stop_reason='max_iterations'."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    mock_client.messages.create.return_value = _mk_tool_use_response("tu-x", "fetch_data", {})

    result = provider.run_agent(
        system="sys",
        user="loop forever",
        tools=[_simple_tool_spec()],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        max_iterations=3,
    )

    assert result.stop_reason == "max_iterations"
    assert result.iterations == 3
    assert mock_client.messages.create.call_count == 3


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_spend_meter_abort(mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """spend_meter.would_exceed() returns True after first charge → stop_reason='max_cost'."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    mock_client.messages.create.return_value = _mk_text_response(
        text="partial", stop_reason="end_turn"
    )

    mock_meter = MagicMock()
    mock_meter.would_exceed.return_value = True

    result = provider.run_agent(
        system="sys",
        user="do something expensive",
        tools=[],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        spend_meter=mock_meter,
    )

    assert result.stop_reason == "max_cost"
    assert result.iterations == 1
    mock_meter.charge.assert_called_once()
    mock_meter.would_exceed.assert_called_once()


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_transcript_records_turns(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After 1 iteration, transcript contains exactly 1 AgentTurn with correct token counts."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    mock_client.messages.create.return_value = _mk_text_response(
        text="hello",
        stop_reason="end_turn",
        input_tokens=120,
        output_tokens=30,
    )

    result = provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
    )

    assert len(result.transcript) == 1
    turn: AgentTurn = result.transcript[0]
    assert turn.role == "assistant"
    assert turn.text == "hello"
    assert turn.input_tokens == 120
    assert turn.output_tokens == 30
    assert result.total_input_tokens == 120
    assert result.total_output_tokens == 30


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_total_cost_reflects_spend_meter_delta(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AgentResult.total_cost_usd carries the per-call delta, not cumulative meter spend.

    The meter is shared across many ``run_agent`` invocations within a single
    pipeline run. The result must report only what *this* call spent, so the
    pipeline can attribute cost per role/lesson without subtracting earlier
    runs by hand.
    """
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    mock_client.messages.create.return_value = _mk_text_response(
        text="done",
        stop_reason="end_turn",
        input_tokens=200_000,
        output_tokens=100_000,
    )

    # Pre-spend $5 on the meter (simulating earlier agent runs in the same pipeline).
    meter = SpendMeter(budget_usd=100.0)
    meter.charge(model="claude-sonnet-4-6", input_tokens=250_000, output_tokens=83_333)
    pre_spend = meter.total_cost_usd
    assert pre_spend > 0.0

    result = provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        spend_meter=meter,
    )

    # Per-call delta: only what *this* run charged.
    expected_delta = meter.total_cost_usd - pre_spend
    assert result.total_cost_usd == pytest.approx(expected_delta)
    # Sanity: the delta is strictly less than cumulative — no leak of prior spend.
    assert result.total_cost_usd < meter.total_cost_usd


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_total_cost_zero_without_spend_meter(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no SpendMeter is wired, AgentResult.total_cost_usd is 0.0 (no synthetic cost)."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = _mk_text_response(stop_reason="end_turn")

    result = provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
    )

    assert result.total_cost_usd == 0.0
