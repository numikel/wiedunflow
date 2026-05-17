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
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> MagicMock:
    """Build a minimal mock anthropic.Message with a TextBlock.

    Cache token fields must be set explicitly on the MagicMock because
    auto-attribute proxies return MagicMock objects, not int 0, and the
    arithmetic ``cache_read * input_price`` would silently produce garbage.
    """
    resp = MagicMock()
    resp.content = [TextBlock(type="text", text=text)]
    resp.stop_reason = stop_reason
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    resp.usage.cache_creation_input_tokens = cache_creation_input_tokens
    resp.usage.cache_read_input_tokens = cache_read_input_tokens
    return resp


def _mk_tool_use_response(
    tool_use_id: str,
    tool_name: str,
    tool_input: dict,  # type: ignore[type-arg]
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> MagicMock:
    """Build a mock anthropic.Message containing a ToolUseBlock."""
    resp = MagicMock()
    resp.content = [ToolUseBlock(type="tool_use", id=tool_use_id, name=tool_name, input=tool_input)]
    resp.stop_reason = "tool_use"
    resp.usage.input_tokens = input_tokens
    resp.usage.output_tokens = output_tokens
    resp.usage.cache_creation_input_tokens = cache_creation_input_tokens
    resp.usage.cache_read_input_tokens = cache_read_input_tokens
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


# ---------------------------------------------------------------------------
# Prompt caching wiring
# ---------------------------------------------------------------------------


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_prompt_caching_true_system_is_list_with_cache_control(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prompt_caching=True wraps the system prompt in a TextBlockParam with cache_control."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = _mk_text_response(stop_reason="end_turn")

    provider.run_agent(
        system="long system prompt for caching",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        prompt_caching=True,
    )

    create_kwargs = mock_client.messages.create.call_args.kwargs
    system_param = create_kwargs["system"]
    assert isinstance(system_param, list)
    assert system_param[0] == {
        "type": "text",
        "text": "long system prompt for caching",
        "cache_control": {"type": "ephemeral"},
    }


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_prompt_caching_false_system_stays_str(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """prompt_caching=False preserves the legacy string wire format for system."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = _mk_text_response(stop_reason="end_turn")

    provider.run_agent(
        system="plain string",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        prompt_caching=False,
    )

    create_kwargs = mock_client.messages.create.call_args.kwargs
    assert create_kwargs["system"] == "plain string"


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_prompt_caching_marks_last_tool(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When caching is on, only the last tool schema receives cache_control."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = _mk_text_response(stop_reason="end_turn")

    tools = [
        ToolSpec(name="tool_a", description="A", input_schema={"type": "object"}),
        ToolSpec(name="tool_b", description="B", input_schema={"type": "object"}),
    ]
    provider.run_agent(
        system="sys",
        user="hi",
        tools=tools,
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        prompt_caching=True,
    )

    create_kwargs = mock_client.messages.create.call_args.kwargs
    sent_tools = create_kwargs["tools"]
    assert "cache_control" not in sent_tools[0]
    assert sent_tools[-1]["cache_control"] == {"type": "ephemeral"}


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_cache_creation_tokens_charged_to_meter(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache write tokens reach the meter and bill at 1.25x the input rate."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    # 1M cache-write tokens, 0 regular input, 0 output — clean isolation.
    mock_client.messages.create.return_value = _mk_text_response(
        stop_reason="end_turn",
        input_tokens=0,
        output_tokens=0,
        cache_creation_input_tokens=1_000_000,
    )

    meter = SpendMeter(budget_usd=100.0)
    provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        spend_meter=meter,
    )

    # Fallback price is $5/MTok input → cache write = 5.0 * 1.25 = $6.25.
    assert meter.total_cost_usd == pytest.approx(6.25, rel=1e-3)


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_cache_read_tokens_charged_to_meter(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache read tokens reach the meter and bill at 0.1x the input rate."""
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value
    mock_client.messages.create.return_value = _mk_text_response(
        stop_reason="end_turn",
        input_tokens=0,
        output_tokens=0,
        cache_read_input_tokens=1_000_000,
    )

    meter = SpendMeter(budget_usd=100.0)
    provider.run_agent(
        system="sys",
        user="hi",
        tools=[],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        spend_meter=meter,
    )

    # Fallback $5/MTok input → cache read = 5.0 * 0.1 = $0.50.
    assert meter.total_cost_usd == pytest.approx(0.50, rel=1e-3)


# ---------------------------------------------------------------------------
# Sliding-window history compression
# ---------------------------------------------------------------------------


def _build_tool_loop_provider(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch, iterations: int
) -> AnthropicProvider:
    """Return a provider whose mock client emits *iterations* tool_use rounds
    before signalling end_turn.

    Each round produces a fresh tool_use_id so the pair-aware sliding window
    has unambiguous targets to prune.
    """
    provider = _mk_provider(monkeypatch, mock_cls)
    mock_client = mock_cls.return_value

    sequence: list[MagicMock] = []
    for i in range(iterations):
        sequence.append(
            _mk_tool_use_response(
                tool_use_id=f"tu-{i:03d}",
                tool_name="fetch_data",
                tool_input={"i": i},
                input_tokens=10,
                output_tokens=5,
            )
        )
    # Final response: end_turn so the loop terminates cleanly.
    sequence.append(_mk_text_response(text="done", stop_reason="end_turn"))
    mock_client.messages.create.side_effect = sequence
    return provider


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_below_threshold_history_grows_unchanged(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Below max_history_iterations the compressor is a no-op."""
    provider = _build_tool_loop_provider(mock_cls, monkeypatch, iterations=4)
    mock_client = mock_cls.return_value

    provider.run_agent(
        system="sys",
        user="hi",
        tools=[_simple_tool_spec()],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        max_iterations=20,
        max_history_iterations=10,
    )

    # 4 tool-use rounds + the final end_turn call = 5 messages.create() calls.
    # The last call's message list should contain: seed user + 4 * (assistant + tool_result)
    # = 9 entries. Below threshold: no synthetic compression message inserted.
    last_kwargs = mock_client.messages.create.call_args_list[-1].kwargs
    messages = last_kwargs["messages"]
    assert len(messages) == 9
    # No "Compressed earlier iterations" marker.
    user_messages = [m for m in messages if m.get("role") == "user"]
    assert all(
        not (isinstance(m.get("content"), str) and "Compressed earlier" in m["content"])
        for m in user_messages
    )


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_above_threshold_compresses_middle(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At iteration 12 with threshold 10 the middle band is summarized."""
    provider = _build_tool_loop_provider(mock_cls, monkeypatch, iterations=12)
    mock_client = mock_cls.return_value

    provider.run_agent(
        system="sys",
        user="hi",
        tools=[_simple_tool_spec()],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        max_iterations=20,
        max_history_iterations=10,
    )

    # Final call (end_turn) sees the compressed history.
    final_kwargs = mock_client.messages.create.call_args_list[-1].kwargs
    final_messages = final_kwargs["messages"]
    # Expected shape: seed user + 5 head iters (10 entries) + summary + 5 tail iters (10 entries) = 22.
    # Without compression it would be seed + 12 * 2 = 25.
    assert len(final_messages) < 25, f"compression did not trigger: {len(final_messages)} >= 25"
    summary_msgs = [
        m
        for m in final_messages
        if m.get("role") == "user"
        and isinstance(m.get("content"), str)
        and "Compressed earlier" in m["content"]
    ]
    assert len(summary_msgs) == 1, "expected exactly one synthetic summary marker"


@patch("wiedunflow.adapters.anthropic_provider.anthropic.Anthropic")
def test_run_agent_sliding_window_preserves_tool_use_id_pairs(
    mock_cls: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every tool_use_id in head/tail bands must have its matching tool_result."""
    provider = _build_tool_loop_provider(mock_cls, monkeypatch, iterations=15)
    mock_client = mock_cls.return_value

    provider.run_agent(
        system="sys",
        user="hi",
        tools=[_simple_tool_spec()],
        tool_executor=_passthrough_executor,
        model="claude-sonnet-4-6",
        max_iterations=20,
        max_history_iterations=10,
    )

    final_messages = mock_client.messages.create.call_args_list[-1].kwargs["messages"]

    surviving_tool_use_ids: set[str] = set()
    surviving_tool_result_ids: set[str] = set()
    for msg in final_messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                # SDK ToolUseBlock instances appear in assistant messages.
                if isinstance(block, ToolUseBlock):
                    surviving_tool_use_ids.add(block.id)
                elif isinstance(block, dict) and block.get("type") == "tool_result":
                    surviving_tool_result_ids.add(block["tool_use_id"])

    # Every surviving tool_use has its matching tool_result and vice versa —
    # Anthropic's API would return 400 if a pair were split.
    assert surviving_tool_use_ids == surviving_tool_result_ids
