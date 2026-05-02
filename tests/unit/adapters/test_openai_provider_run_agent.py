# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for OpenAIProvider.run_agent()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiedunflow.adapters.openai_provider import OpenAIProvider
from wiedunflow.interfaces.ports import AgentResult, AgentTurn, ToolCall, ToolResult, ToolSpec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_provider(monkeypatch: pytest.MonkeyPatch, mock_cls: MagicMock) -> OpenAIProvider:
    """Construct an OpenAIProvider with a mocked OpenAI client."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_cls.return_value = MagicMock()
    return OpenAIProvider()


def _mk_chat_response(
    content: str | None = "hello",
    tool_calls: list[MagicMock] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> MagicMock:
    """Build a minimal mock ChatCompletion response."""
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls
    choice.finish_reason = finish_reason
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    return resp


def _mk_tool_call_mock(call_id: str, name: str, arguments: str = "{}") -> MagicMock:
    """Build a minimal mock tool_call object as returned by the OpenAI SDK."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = arguments
    return tc


def _simple_tool_spec() -> ToolSpec:
    return ToolSpec(
        name="get_info",
        description="Returns some info",
        input_schema={"type": "object", "properties": {}, "required": []},
    )


def _passthrough_executor(call: ToolCall) -> ToolResult:
    return ToolResult(tool_call_id=call.id, content=f"result-of-{call.name}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_no_tools_returns_end_turn(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Model returns finish_reason=stop with no tool calls → stop_reason='end_turn', iterations=1."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.chat.completions.create.return_value = _mk_chat_response(
        content="Done", tool_calls=None, finish_reason="stop"
    )

    result = provider.run_agent(
        system="sys",
        user="do something",
        tools=[],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
    )

    assert isinstance(result, AgentResult)
    assert result.stop_reason == "end_turn"
    assert result.iterations == 1
    assert result.final_text == "Done"
    assert len(result.transcript) == 1
    assert result.transcript[0].role == "assistant"
    assert result.transcript[0].tool_calls == []


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_single_tool_call(mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Model calls 1 tool, executor returns result, model then responds with text."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    tool_call_mock = _mk_tool_call_mock("call-1", "get_info", '{"key": "val"}')

    # First response: tool_use; second response: end_turn
    mock_client.chat.completions.create.side_effect = [
        _mk_chat_response(
            content=None,
            tool_calls=[tool_call_mock],
            finish_reason="tool_calls",
        ),
        _mk_chat_response(content="Final answer", tool_calls=None, finish_reason="stop"),
    ]

    tool_specs = [_simple_tool_spec()]
    result = provider.run_agent(
        system="sys",
        user="get info",
        tools=tool_specs,
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
    )

    assert result.stop_reason == "end_turn"
    assert result.iterations == 2
    assert result.final_text == "Final answer"
    # Two assistant turns recorded
    assert len(result.transcript) == 2
    # First turn had a tool call
    assert result.transcript[0].tool_calls[0].name == "get_info"
    assert result.transcript[0].tool_calls[0].arguments == {"key": "val"}
    # Tool executor was invoked once → second messages.create call was made
    assert mock_client.chat.completions.create.call_count == 2


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_max_iterations_reached(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Model always requests a tool call; loop stops at max_iterations → stop_reason='max_iterations'."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    tool_call_mock = _mk_tool_call_mock("call-x", "get_info")
    # Always return a tool_calls response
    mock_client.chat.completions.create.return_value = _mk_chat_response(
        content=None,
        tool_calls=[tool_call_mock],
        finish_reason="tool_calls",
    )

    result = provider.run_agent(
        system="sys",
        user="loop forever",
        tools=[_simple_tool_spec()],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
        max_iterations=3,
    )

    assert result.stop_reason == "max_iterations"
    assert result.iterations == 3
    assert mock_client.chat.completions.create.call_count == 3


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_spend_meter_abort(mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """spend_meter.would_exceed() returns True after first charge → stop_reason='max_cost'."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    # Response: no tool calls (so we'd normally get end_turn) — but spend_meter fires first
    mock_client.chat.completions.create.return_value = _mk_chat_response(
        content="partial", tool_calls=None, finish_reason="stop"
    )

    mock_meter = MagicMock()
    mock_meter.would_exceed.return_value = True  # always over budget

    result = provider.run_agent(
        system="sys",
        user="do something expensive",
        tools=[],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
        spend_meter=mock_meter,
    )

    assert result.stop_reason == "max_cost"
    assert result.iterations == 1
    mock_meter.charge.assert_called_once()
    mock_meter.would_exceed.assert_called_once()


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_transcript_records_turns(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After 1 iteration, transcript contains exactly 1 AgentTurn with correct token counts."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    mock_client.chat.completions.create.return_value = _mk_chat_response(
        content="hello",
        tool_calls=None,
        finish_reason="stop",
        prompt_tokens=120,
        completion_tokens=30,
    )

    result = provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
    )

    assert len(result.transcript) == 1
    turn: AgentTurn = result.transcript[0]
    assert turn.role == "assistant"
    assert turn.text == "hello"
    assert turn.input_tokens == 120
    assert turn.output_tokens == 30
    assert result.total_input_tokens == 120
    assert result.total_output_tokens == 30
