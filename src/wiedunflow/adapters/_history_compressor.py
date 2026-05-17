# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Sliding-window history compression for agent-loop message lists.

Long agent loops (≥10 iterations) replay the full conversation on every
provider call. Tool results are the biggest contributor: a single
``search_docs`` or ``read_symbol_body`` response routinely runs 5-8 KB, and
the Orchestrator hits 15 iterations in steady-state. Without compression the
fifteenth call sends ~30-50 KB of conversation as input — input cost grows
quadratically with iteration count.

The compressor keeps the first 5 and the last 5 iterations verbatim, and
collapses every iteration in between into a one-line summary. Tool_use and
tool_result blocks are pruned as **pairs** because Anthropic's Messages API
returns ``400 Bad Request`` if a ``tool_use_id`` referenced in an assistant
turn is missing its matching ``tool_result`` in the next user message.

Both adapters (Anthropic and OpenAI) call ``compress_history`` after appending
new turns; below the threshold the function is a no-op so the steady-state
path stays cheap.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# Number of full iterations preserved at the start (system + initial user are
# always kept separately and not counted here). Five turns gives the model a
# stable footing in the early reconnaissance phase.
_KEEP_FIRST_ITERATIONS = 5

# Number of full iterations preserved at the tail. The model relies most
# heavily on the most-recent tool results when deciding the next call.
_KEEP_LAST_ITERATIONS = 5

# Truncation width for tool_result summaries. 80 characters fits one line
# in a terminal transcript and still surfaces enough signal to remind the
# model which tool was called and roughly what came back.
_SUMMARY_BODY_CHARS = 80


def _shorten(text: str, limit: int = _SUMMARY_BODY_CHARS) -> str:
    """Trim *text* to at most ``limit`` characters with an ellipsis when cut."""
    flat = " ".join(text.split())  # collapse newlines/tabs into single spaces
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "..."


def _summarize_tool_results_anthropic(content_blocks: list[dict[str, Any]]) -> str:
    """Produce a one-line summary for an Anthropic user-role tool_result message."""
    parts: list[str] = []
    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            body = block.get("content", "")
            if not isinstance(body, str):
                # tool_result content can be a list of text blocks; flatten
                # by concatenating any ``text`` fields we find.
                body = " ".join(
                    b.get("text", "")
                    for b in body
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            parts.append(_shorten(str(body)))
    if not parts:
        return "[tool result summary]"
    return " | ".join(parts)


def _summarize_assistant_tool_calls(tool_calls: Iterable[Any]) -> str:
    """Render the tool names from an assistant turn for the summary line."""
    names: list[str] = []
    for call in tool_calls:
        # SDK-native ToolUseBlock has ``.name``; Anthropic dicts have ``["name"]``.
        name = getattr(call, "name", None)
        if name is None and isinstance(call, dict):
            name = call.get("name") or (call.get("function") or {}).get("name")
        if name:
            names.append(str(name))
    return ", ".join(names) if names else "no-tools"


def compress_anthropic_history(
    messages: list[dict[str, Any]],
    *,
    iteration: int,
    max_history_iterations: int,
) -> list[dict[str, Any]]:
    """Return a compressed copy of *messages* if the threshold has been crossed.

    Anthropic message-list shape per :func:`AnthropicProvider.run_agent`:

    * ``messages[0]`` is the initial ``role="user"`` turn (the system prompt
      lives outside ``messages``).
    * Each iteration after that appends two entries: ``role="assistant"`` with
      the SDK ``response.content`` list (text + tool_use blocks), then
      ``role="user"`` carrying ``tool_result`` blocks for the same tool_use ids.

    The compressor keeps ``messages[0]``, the first
    ``_KEEP_FIRST_ITERATIONS`` iteration pairs, a one-line synthetic
    ``role="user"`` summary line standing in for the middle iterations, and
    the last ``_KEEP_LAST_ITERATIONS`` iteration pairs verbatim. When the
    middle band is empty the original list is returned unchanged.

    Args:
        messages: The provider message list. Never mutated.
        iteration: The 0-based iteration counter from the agent loop.
        max_history_iterations: Threshold above which compression kicks in.

    Returns:
        Either *messages* unchanged (below threshold or already compact) or a
        new list with the middle band replaced by a summary placeholder.
    """
    if iteration + 1 <= max_history_iterations:
        return messages

    # Drop any prior synthetic summary turn so the window is recomputed from
    # real assistant/tool_result pairs only. Without this every iteration
    # would accrete another summary.
    messages = [
        m
        for m in messages
        if not (
            m.get("role") == "user"
            and isinstance(m.get("content"), str)
            and m["content"].startswith(_ANTHROPIC_SUMMARY_PREFIX)
        )
    ]

    # Iteration count starts at 0; messages[0] is the seed user turn, so each
    # iteration contributes two further entries.
    keep_first_entries = 1 + 2 * _KEEP_FIRST_ITERATIONS
    keep_last_entries = 2 * _KEEP_LAST_ITERATIONS
    if keep_first_entries + keep_last_entries >= len(messages):
        return messages

    head = messages[:keep_first_entries]
    tail = messages[-keep_last_entries:]
    middle = messages[keep_first_entries : len(messages) - keep_last_entries]

    summary_lines: list[str] = []
    for idx in range(0, len(middle), 2):
        assistant_msg = middle[idx] if idx < len(middle) else None
        tool_result_msg = middle[idx + 1] if idx + 1 < len(middle) else None
        if assistant_msg is None:
            continue
        # Iteration number relative to the original loop: head covered
        # iterations 1.._KEEP_FIRST_ITERATIONS, so middle starts at 6.
        iter_no = _KEEP_FIRST_ITERATIONS + 1 + idx // 2
        tools_called = _summarize_assistant_tool_calls(assistant_msg.get("content", []) or [])
        if tool_result_msg is not None:
            result_blocks = tool_result_msg.get("content") or []
            if isinstance(result_blocks, list):
                tool_results_summary = _summarize_tool_results_anthropic(result_blocks)
            else:
                tool_results_summary = _shorten(str(result_blocks))
        else:
            tool_results_summary = "[no tool_result captured]"
        summary_lines.append(f"[iter {iter_no}: tools=({tools_called}) -> {tool_results_summary}]")

    if not summary_lines:
        return messages

    synthetic = {
        "role": "user",
        "content": (
            "[Compressed earlier iterations to keep context bounded — "
            "summaries below preserve which tools ran and the gist of their "
            "outputs; replay the workspace transcript if exact details are "
            "needed.]\n" + "\n".join(summary_lines)
        ),
    }

    return [*head, synthetic, *tail]


def _summarize_tool_results_openai(messages: list[dict[str, Any]]) -> dict[str, str]:
    """Build a ``tool_call_id → short summary`` map from a slice of OpenAI messages."""
    summaries: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        tc_id = msg.get("tool_call_id")
        if tc_id is None:
            continue
        summaries[str(tc_id)] = _shorten(str(msg.get("content", "")))
    return summaries


_OPENAI_SUMMARY_PREFIX = "[Compressed earlier iterations to keep context bounded"
_ANTHROPIC_SUMMARY_PREFIX = _OPENAI_SUMMARY_PREFIX  # identical wording across providers


def compress_openai_history(
    messages: list[dict[str, Any]],
    *,
    iteration: int,
    max_history_iterations: int,
) -> list[dict[str, Any]]:
    """Compress a Chat Completions message list using the same window policy.

    Differences from the Anthropic variant:

    * ``messages[0]`` is the ``role="system"`` turn (always kept) and
      ``messages[1]`` is the initial ``role="user"`` turn.
    * Each iteration appends one ``role="assistant"`` entry (with optional
      ``tool_calls`` array) followed by zero or more ``role="tool"`` entries —
      one per tool_call_id. Window pruning treats the assistant + matching
      tool entries as one unit so ``tool_call_id`` references stay valid.

    The summary message is appended as a ``role="user"`` turn (Chat
    Completions accepts free-form roles in any order). Below the threshold
    the function is a no-op. Repeated invocations are idempotent: any
    previously-inserted summary line is replaced with a fresh one rather
    than accumulating.
    """
    if iteration + 1 <= max_history_iterations:
        return messages

    # Drop any synthetic summary inserted by a prior compression pass so the
    # window is recomputed from real iteration turns only. Otherwise each
    # iteration would stack another summary on top of the last.
    messages = [
        m
        for m in messages
        if not (
            m.get("role") == "user"
            and isinstance(m.get("content"), str)
            and m["content"].startswith(_OPENAI_SUMMARY_PREFIX)
        )
    ]

    # Locate iteration boundaries: every ``role="assistant"`` message that
    # carries ``tool_calls`` marks the start of an iteration block. The
    # following ``role="tool"`` messages belong to that block.
    boundaries: list[int] = []
    for i, msg in enumerate(messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            boundaries.append(i)
    if len(boundaries) <= _KEEP_FIRST_ITERATIONS + _KEEP_LAST_ITERATIONS:
        return messages

    head_end = boundaries[_KEEP_FIRST_ITERATIONS]  # first index in the middle band
    tail_start = boundaries[-_KEEP_LAST_ITERATIONS]  # first index in the tail band

    head = messages[:head_end]
    tail = messages[tail_start:]

    summary_lines: list[str] = []
    middle_boundaries = [i for i in boundaries if head_end <= i < tail_start]
    for slot, asst_idx in enumerate(middle_boundaries):
        next_asst_idx = (
            middle_boundaries[slot + 1] if slot + 1 < len(middle_boundaries) else tail_start
        )
        block = messages[asst_idx:next_asst_idx]
        assistant_msg = block[0]
        tool_msgs = block[1:]
        iter_no = _KEEP_FIRST_ITERATIONS + 1 + slot
        tools_called = _summarize_assistant_tool_calls(assistant_msg.get("tool_calls") or [])
        result_map = _summarize_tool_results_openai(tool_msgs)
        if result_map:
            results_summary = " | ".join(result_map.values())
        else:
            results_summary = "[no tool messages captured]"
        summary_lines.append(f"[iter {iter_no}: tools=({tools_called}) -> {results_summary}]")

    if not summary_lines:
        return messages

    synthetic = {
        "role": "user",
        "content": (
            "[Compressed earlier iterations to keep context bounded — "
            "summaries below preserve which tools ran and the gist of their "
            "outputs; replay the workspace transcript if exact details are "
            "needed.]\n" + "\n".join(summary_lines)
        ),
    }

    return [*head, synthetic, *tail]
