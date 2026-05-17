# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for OpenAIProvider.run_agent()."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from wiedunflow.adapters.openai_provider import OpenAIProvider
from wiedunflow.interfaces.ports import AgentResult, AgentTurn, ToolCall, ToolResult, ToolSpec
from wiedunflow.use_cases.spend_meter import SpendMeter

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
    cached_tokens: int = 0,
) -> MagicMock:
    """Build a minimal mock ChatCompletion response.

    ``cached_tokens`` lives at ``usage.prompt_tokens_details.cached_tokens``.
    The field must be set explicitly because MagicMock auto-attribute proxies
    return MagicMock objects (truthy, but non-numeric), which silently breaks
    the spend meter's arithmetic.
    """
    choice = MagicMock()
    choice.message.content = content
    choice.message.tool_calls = tool_calls
    choice.finish_reason = finish_reason
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage.prompt_tokens = prompt_tokens
    resp.usage.completion_tokens = completion_tokens
    resp.usage.prompt_tokens_details.cached_tokens = cached_tokens
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


@patch("wiedunflow.adapters.openai_provider.OpenAI")
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

    mock_client.chat.completions.create.return_value = _mk_chat_response(
        content="done",
        tool_calls=None,
        finish_reason="stop",
        prompt_tokens=200_000,
        completion_tokens=100_000,
    )

    # Pre-spend on the meter (simulating earlier agent runs in the same pipeline).
    meter = SpendMeter(budget_usd=100.0)
    meter.charge(model="gpt-5.4", input_tokens=250_000, output_tokens=83_333)
    pre_spend = meter.total_cost_usd
    assert pre_spend > 0.0

    result = provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
        spend_meter=meter,
    )

    expected_delta = meter.total_cost_usd - pre_spend
    assert result.total_cost_usd == pytest.approx(expected_delta)
    assert result.total_cost_usd < meter.total_cost_usd


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_total_cost_zero_without_spend_meter(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When no SpendMeter is wired, AgentResult.total_cost_usd is 0.0."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.chat.completions.create.return_value = _mk_chat_response(
        content="hi", tool_calls=None, finish_reason="stop"
    )

    result = provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
    )

    assert result.total_cost_usd == 0.0


# ---------------------------------------------------------------------------
# Cached tokens + prompt_caching kwarg
# ---------------------------------------------------------------------------


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_cached_tokens_reduce_meter_charge(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When prompt_tokens_details.cached_tokens > 0 the meter applies the 0.5x cached rate."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.chat.completions.create.return_value = _mk_chat_response(
        content="done",
        tool_calls=None,
        finish_reason="stop",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cached_tokens=1_000_000,
    )

    meter = SpendMeter(budget_usd=100.0)
    provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
        spend_meter=meter,
    )

    # Fallback rate $5/MTok input. All 1M prompt tokens were cached → bill at
    # 0.5x → $2.50. Without the cache fix the meter would charge $5.00.
    assert meter.total_cost_usd == pytest.approx(2.50, rel=1e-3)


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_no_cached_tokens_uses_full_input_rate(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When cached_tokens == 0 the meter charges the regular input rate end-to-end."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.chat.completions.create.return_value = _mk_chat_response(
        content="done",
        tool_calls=None,
        finish_reason="stop",
        prompt_tokens=1_000_000,
        completion_tokens=0,
        cached_tokens=0,
    )

    meter = SpendMeter(budget_usd=100.0)
    provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
        spend_meter=meter,
    )

    assert meter.total_cost_usd == pytest.approx(5.00, rel=1e-3)


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_prompt_caching_true_is_noop_log_only(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prompt_caching=True on OpenAI: SDK call is unchanged (no cache_control marker)."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.chat.completions.create.return_value = _mk_chat_response(
        content="done", tool_calls=None, finish_reason="stop"
    )

    provider.run_agent(
        system="sys",
        user="hi",
        tools=[_simple_tool_spec()],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
        prompt_caching=True,
    )

    create_kwargs = mock_client.chat.completions.create.call_args.kwargs
    # System message stays at messages[0] as a plain dict — no cache_control field.
    assert create_kwargs["messages"][0]["role"] == "system"
    assert create_kwargs["messages"][0]["content"] == "sys"
    # Tools array is unchanged — no cache_control marker.
    for tool in create_kwargs["tools"]:
        assert "cache_control" not in tool


# ---------------------------------------------------------------------------
# Sliding-window history
# ---------------------------------------------------------------------------


def _mk_tool_response(call_id: str) -> MagicMock:
    """Build a ChatCompletion response that requests a tool call with given id."""
    tc = _mk_tool_call_mock(call_id=call_id, name="get_info", arguments="{}")
    return _mk_chat_response(content=None, tool_calls=[tc], finish_reason="tool_calls")


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_above_threshold_history_is_compressed(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At iteration 12 with threshold 10 the OpenAI history collapses too."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    sequence: list[MagicMock] = []
    for i in range(12):
        sequence.append(_mk_tool_response(call_id=f"tc-{i:03d}"))
    sequence.append(_mk_chat_response(content="done", tool_calls=None, finish_reason="stop"))
    mock_client.chat.completions.create.side_effect = sequence

    provider.run_agent(
        system="sys",
        user="hi",
        tools=[_simple_tool_spec()],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
        max_iterations=20,
        max_history_iterations=10,
    )

    final_msgs = mock_client.chat.completions.create.call_args_list[-1].kwargs["messages"]
    summary_count = sum(
        1
        for m in final_msgs
        if isinstance(m.get("content"), str) and "Compressed earlier" in m["content"]
    )
    assert summary_count == 1, "expected exactly one summary marker"

    # System prompt is always preserved at index 0.
    assert final_msgs[0]["role"] == "system"
    assert final_msgs[0]["content"] == "sys"


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_sliding_window_keeps_tool_call_id_pairs(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every surviving tool_call_id has its matching role=tool message and vice versa."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    sequence: list[MagicMock] = []
    for i in range(15):
        sequence.append(_mk_tool_response(call_id=f"tc-{i:03d}"))
    sequence.append(_mk_chat_response(content="done", tool_calls=None, finish_reason="stop"))
    mock_client.chat.completions.create.side_effect = sequence

    provider.run_agent(
        system="sys",
        user="hi",
        tools=[_simple_tool_spec()],
        tool_executor=_passthrough_executor,
        model="gpt-5.4",
        max_iterations=20,
        max_history_iterations=10,
    )

    final_msgs = mock_client.chat.completions.create.call_args_list[-1].kwargs["messages"]

    assistant_tool_call_ids: set[str] = set()
    tool_role_call_ids: set[str] = set()
    for msg in final_msgs:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                if tc_id:
                    assistant_tool_call_ids.add(tc_id)
        elif msg.get("role") == "tool":
            tool_role_call_ids.add(str(msg["tool_call_id"]))

    assert assistant_tool_call_ids == tool_role_call_ids
