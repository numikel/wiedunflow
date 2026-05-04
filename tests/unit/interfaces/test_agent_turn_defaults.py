# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""``AgentTurn`` Pydantic defaults isolate per-instance lists.

Pydantic v2 protects against the classic mutable-default-argument trap that
catches plain Python dataclasses, but the convention in this repo is to be
explicit with ``Field(default_factory=...)`` for collection fields. These
tests guard against a regression where the explicit factory is dropped and
two newly-constructed instances accidentally share a list reference.
"""

from __future__ import annotations

from wiedunflow.interfaces.ports import AgentTurn, ToolCall, ToolResult


def test_default_tool_calls_are_distinct_lists() -> None:
    a = AgentTurn(role="assistant")
    b = AgentTurn(role="assistant")
    assert a.tool_calls is not b.tool_calls
    a.tool_calls.append(ToolCall(id="t1", name="x", arguments={}))
    assert b.tool_calls == []  # appending to a must NOT bleed into b


def test_default_tool_results_are_distinct_lists() -> None:
    a = AgentTurn(role="tool")
    b = AgentTurn(role="tool")
    assert a.tool_results is not b.tool_results
    a.tool_results.append(ToolResult(tool_call_id="t1", content="x"))
    assert b.tool_results == []
