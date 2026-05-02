# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from wiedunflow.use_cases.agents.loader import (
    AgentCardBudgets,
    CompiledCard,
    compile_card,
    load_agent_card,
    load_tool_schema,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_CARD = """\
---
schema_version: 1
name: test_agent
description: A test agent
suggested_model_role: small_fast
tools: []
budgets:
  max_iterations: 5
  max_cost_usd: 0.10
  prompt_caching: false
input_schema:
  lesson_id: str
  symbol: str
output_contract:
  format: text
  description: Returns text
---

# Test Agent

Hello {{lesson_id}} and {{symbol}}
"""

_TOOL_SCHEMA: dict = {
    "name": "test_tool",
    "description": "A test tool",
    "parameters": {
        "type": "object",
        "properties": {"arg": {"type": "string", "description": "An arg"}},
        "required": ["arg"],
    },
}


def _write_card(tmp_path: Path, content: str, name: str = "test_agent") -> None:
    (tmp_path / f"{name}.md").write_text(content, encoding="utf-8")


def _write_tool(tmp_path: Path, name: str = "test_tool") -> None:
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir(exist_ok=True)
    (tools_dir / f"{name}.json").write_text(json.dumps(_TOOL_SCHEMA), encoding="utf-8")


# ---------------------------------------------------------------------------
# load_agent_card
# ---------------------------------------------------------------------------


def test_load_agent_card_parses_frontmatter(tmp_path: Path) -> None:
    _write_card(tmp_path, _MINIMAL_CARD)
    fm, _body = load_agent_card("test_agent", agents_dir=tmp_path)

    assert fm.name == "test_agent"
    assert fm.description == "A test agent"
    assert fm.suggested_model_role == "small_fast"
    assert fm.budgets.max_iterations == 5
    assert fm.budgets.max_cost_usd == pytest.approx(0.10)
    assert fm.budgets.prompt_caching is False
    assert fm.input_schema == {"lesson_id": "str", "symbol": "str"}
    assert fm.output_contract.format == "text"
    assert fm.schema_version == 1


def test_load_agent_card_body_contains_placeholders(tmp_path: Path) -> None:
    _write_card(tmp_path, _MINIMAL_CARD)
    _, body = load_agent_card("test_agent", agents_dir=tmp_path)

    assert "{{lesson_id}}" in body
    assert "{{symbol}}" in body
    assert "Hello" in body


def test_load_agent_card_not_found_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Agent card not found"):
        load_agent_card("nonexistent", agents_dir=tmp_path)


def test_load_agent_card_missing_frontmatter_delimiters_raises(tmp_path: Path) -> None:
    bad_card = "# No frontmatter at all\n\nJust body text."
    _write_card(tmp_path, bad_card)

    with pytest.raises(ValueError, match="missing frontmatter delimiters"):
        load_agent_card("test_agent", agents_dir=tmp_path)


def test_load_agent_card_tools_empty_list(tmp_path: Path) -> None:
    _write_card(tmp_path, _MINIMAL_CARD)
    fm, _ = load_agent_card("test_agent", agents_dir=tmp_path)
    assert fm.tools == []


def test_load_agent_card_tools_list(tmp_path: Path) -> None:
    card_with_tools = _MINIMAL_CARD.replace("tools: []", "tools:\n  - tool_a\n  - tool_b")
    _write_card(tmp_path, card_with_tools)
    fm, _ = load_agent_card("test_agent", agents_dir=tmp_path)
    assert fm.tools == ["tool_a", "tool_b"]


def test_load_agent_card_budgets_defaults(tmp_path: Path) -> None:
    """Cards without explicit budgets block should use AgentCardBudgets defaults."""
    card_no_budgets = """\
---
schema_version: 1
name: test_agent
description: Minimal
suggested_model_role: quality_writer
tools: []
input_schema: {}
output_contract:
  format: markdown_with_frontmatter
  description: output
---

Body
"""
    _write_card(tmp_path, card_no_budgets)
    fm, _ = load_agent_card("test_agent", agents_dir=tmp_path)
    assert fm.budgets.max_iterations == 15
    assert fm.budgets.max_cost_usd == pytest.approx(0.50)
    assert fm.budgets.prompt_caching is True
    assert fm.budgets.max_retries == 1


def test_load_agent_card_all_suggested_model_roles(tmp_path: Path) -> None:
    for role in ("smart_long_context", "small_fast", "quality_writer"):
        card = _MINIMAL_CARD.replace(
            "suggested_model_role: small_fast", f"suggested_model_role: {role}"
        )
        _write_card(tmp_path, card)
        fm, _ = load_agent_card("test_agent", agents_dir=tmp_path)
        assert fm.suggested_model_role == role


def test_load_agent_card_invalid_model_role_raises(tmp_path: Path) -> None:
    bad_card = _MINIMAL_CARD.replace(
        "suggested_model_role: small_fast", "suggested_model_role: invalid_role"
    )
    _write_card(tmp_path, bad_card)

    with pytest.raises(ValidationError):
        load_agent_card("test_agent", agents_dir=tmp_path)


def test_load_agent_card_all_output_formats(tmp_path: Path) -> None:
    for fmt in ("text", "markdown_with_frontmatter", "json"):
        card = _MINIMAL_CARD.replace("format: text", f"format: {fmt}")
        _write_card(tmp_path, card)
        fm, _ = load_agent_card("test_agent", agents_dir=tmp_path)
        assert fm.output_contract.format == fmt


# ---------------------------------------------------------------------------
# load_tool_schema
# ---------------------------------------------------------------------------


def test_load_tool_schema_returns_dict(tmp_path: Path) -> None:
    _write_tool(tmp_path)
    schema = load_tool_schema("test_tool", agents_dir=tmp_path)
    assert schema["name"] == "test_tool"
    assert "parameters" in schema


def test_load_tool_schema_not_found_raises(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    with pytest.raises(FileNotFoundError, match="Tool schema not found"):
        load_tool_schema("missing_tool", agents_dir=tmp_path)


def test_load_tool_schema_returns_full_schema(tmp_path: Path) -> None:
    _write_tool(tmp_path)
    schema = load_tool_schema("test_tool", agents_dir=tmp_path)
    assert schema["description"] == "A test tool"
    assert schema["parameters"]["type"] == "object"
    assert "arg" in schema["parameters"]["properties"]


# ---------------------------------------------------------------------------
# compile_card
# ---------------------------------------------------------------------------


def test_compile_card_formats_placeholders(tmp_path: Path) -> None:
    _write_card(tmp_path, _MINIMAL_CARD)
    result = compile_card(
        "test_agent",
        kwargs={"lesson_id": "lesson-01", "symbol": "module.func"},
        agents_dir=tmp_path,
    )
    assert isinstance(result, CompiledCard)
    assert "lesson-01" in result.system_prompt
    assert "module.func" in result.system_prompt
    assert "{{lesson_id}}" not in result.system_prompt
    assert "{{symbol}}" not in result.system_prompt


def test_compile_card_name_matches_frontmatter(tmp_path: Path) -> None:
    _write_card(tmp_path, _MINIMAL_CARD)
    result = compile_card(
        "test_agent",
        kwargs={"lesson_id": "x", "symbol": "y"},
        agents_dir=tmp_path,
    )
    assert result.name == "test_agent"


def test_compile_card_raises_on_missing_input_schema_key(tmp_path: Path) -> None:
    _write_card(tmp_path, _MINIMAL_CARD)
    # Only provide lesson_id, missing 'symbol'
    with pytest.raises(ValueError, match="Missing input_schema keys"):
        compile_card(
            "test_agent",
            kwargs={"lesson_id": "lesson-01"},
            agents_dir=tmp_path,
        )


def test_compile_card_extra_kwargs_allowed(tmp_path: Path) -> None:
    """Extra kwargs beyond input_schema are passed through without error."""
    _write_card(tmp_path, _MINIMAL_CARD)
    # extra key 'unused' is fine — substitution ignores keys not referenced in body
    result = compile_card(
        "test_agent",
        kwargs={"lesson_id": "lesson-01", "symbol": "fn", "unused": "value"},
        agents_dir=tmp_path,
    )
    assert "lesson-01" in result.system_prompt


def test_compile_card_loads_tool_schemas(tmp_path: Path) -> None:
    card_with_tool = _MINIMAL_CARD.replace("tools: []", "tools:\n  - test_tool")
    _write_card(tmp_path, card_with_tool)
    _write_tool(tmp_path)

    result = compile_card(
        "test_agent",
        kwargs={"lesson_id": "lesson-02", "symbol": "pkg.mod.fn"},
        agents_dir=tmp_path,
    )
    assert len(result.tools) == 1
    assert result.tools[0]["name"] == "test_tool"


def test_compile_card_no_tools_gives_empty_list(tmp_path: Path) -> None:
    _write_card(tmp_path, _MINIMAL_CARD)
    result = compile_card(
        "test_agent",
        kwargs={"lesson_id": "a", "symbol": "b"},
        agents_dir=tmp_path,
    )
    assert result.tools == []


def test_compile_card_missing_tool_schema_raises(tmp_path: Path) -> None:
    card_with_tool = _MINIMAL_CARD.replace("tools: []", "tools:\n  - missing_tool")
    _write_card(tmp_path, card_with_tool)
    # tools/ dir exists but missing_tool.json does not
    (tmp_path / "tools").mkdir()

    with pytest.raises(FileNotFoundError, match="Tool schema not found"):
        compile_card(
            "test_agent",
            kwargs={"lesson_id": "a", "symbol": "b"},
            agents_dir=tmp_path,
        )


def test_compile_card_multiple_tools(tmp_path: Path) -> None:
    # Create two tool schemas
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    for tool_name in ("tool_alpha", "tool_beta"):
        schema = {**_TOOL_SCHEMA, "name": tool_name}
        (tools_dir / f"{tool_name}.json").write_text(json.dumps(schema), encoding="utf-8")

    card = _MINIMAL_CARD.replace("tools: []", "tools:\n  - tool_alpha\n  - tool_beta")
    _write_card(tmp_path, card)

    result = compile_card(
        "test_agent",
        kwargs={"lesson_id": "a", "symbol": "b"},
        agents_dir=tmp_path,
    )
    assert len(result.tools) == 2
    tool_names = {t["name"] for t in result.tools}
    assert tool_names == {"tool_alpha", "tool_beta"}


def test_compile_card_budgets_propagated(tmp_path: Path) -> None:
    _write_card(tmp_path, _MINIMAL_CARD)
    result = compile_card(
        "test_agent",
        kwargs={"lesson_id": "a", "symbol": "b"},
        agents_dir=tmp_path,
    )
    assert isinstance(result.budgets, AgentCardBudgets)
    assert result.budgets.max_iterations == 5
    assert result.budgets.max_cost_usd == pytest.approx(0.10)
    assert result.budgets.prompt_caching is False


def test_compile_card_output_contract_propagated(tmp_path: Path) -> None:
    _write_card(tmp_path, _MINIMAL_CARD)
    result = compile_card(
        "test_agent",
        kwargs={"lesson_id": "a", "symbol": "b"},
        agents_dir=tmp_path,
    )
    assert result.output_contract.format == "text"
    assert result.output_contract.description == "Returns text"


def test_compile_card_literal_json_in_body_does_not_raise(tmp_path: Path) -> None:
    """Regression: bodies with literal JSON examples (single ``{`` / ``}``)
    must not be mis-interpreted as placeholders. Earlier ``str.format()``-based
    substitution raised ``KeyError`` on bodies like ``{"verdict": "pass"}``.
    """
    card_with_json = _MINIMAL_CARD.replace(
        "Hello {{lesson_id}} and {{symbol}}",
        'Example output:\n```json\n{\n  "verdict": "pass",\n  "checks": []\n}\n```\n'
        "Lesson: {{lesson_id}} symbol: {{symbol}}",
    )
    _write_card(tmp_path, card_with_json)
    result = compile_card(
        "test_agent",
        kwargs={"lesson_id": "abc", "symbol": "fn"},
        agents_dir=tmp_path,
    )
    assert '"verdict": "pass"' in result.system_prompt
    assert "Lesson: abc symbol: fn" in result.system_prompt


# ---------------------------------------------------------------------------
# Integration: real agent cards + tools round-trip
# ---------------------------------------------------------------------------


def test_real_orchestrator_card_loads(tmp_path: Path) -> None:
    """Smoke test: the actual orchestrator.md parses without error."""
    real_agents_dir = (
        Path(__file__).parent.parent.parent.parent / "src" / "wiedunflow" / "use_cases" / "agents"
    )
    if not (real_agents_dir / "orchestrator.md").exists():
        pytest.skip("Real agent cards not present in test environment")

    fm, _body = load_agent_card("orchestrator", agents_dir=real_agents_dir)
    assert fm.name == "orchestrator"
    assert fm.suggested_model_role == "smart_long_context"
    assert "dispatch_researcher" in fm.tools
    assert "mark_lesson_done" in fm.tools
    assert fm.budgets.max_iterations == 20


def test_real_researcher_card_loads(tmp_path: Path) -> None:
    real_agents_dir = (
        Path(__file__).parent.parent.parent.parent / "src" / "wiedunflow" / "use_cases" / "agents"
    )
    if not (real_agents_dir / "researcher.md").exists():
        pytest.skip("Real agent cards not present in test environment")

    fm, _body = load_agent_card("researcher", agents_dir=real_agents_dir)
    assert fm.name == "researcher"
    assert fm.suggested_model_role == "small_fast"
    assert "read_symbol_body" in fm.tools
    assert fm.output_contract.format == "markdown_with_frontmatter"


def test_real_writer_card_loads(tmp_path: Path) -> None:
    real_agents_dir = (
        Path(__file__).parent.parent.parent.parent / "src" / "wiedunflow" / "use_cases" / "agents"
    )
    if not (real_agents_dir / "writer.md").exists():
        pytest.skip("Real agent cards not present in test environment")

    fm, _body = load_agent_card("writer", agents_dir=real_agents_dir)
    assert fm.name == "writer"
    assert fm.suggested_model_role == "quality_writer"
    # Fix D: writer now has submit_lesson_draft tool (no longer empty)
    assert "submit_lesson_draft" in fm.tools
    assert fm.budgets.max_iterations == 3


def test_real_writer_card_loads_with_submit_lesson_draft_tool(tmp_path: Path) -> None:
    """Fix D regression: real writer.md must reference submit_lesson_draft tool."""
    real_agents_dir = (
        Path(__file__).parent.parent.parent.parent / "src" / "wiedunflow" / "use_cases" / "agents"
    )
    if not (real_agents_dir / "writer.md").exists():
        pytest.skip("Real agent cards not present in test environment")

    fm, body = load_agent_card("writer", agents_dir=real_agents_dir)
    assert "submit_lesson_draft" in fm.tools, (
        "writer.md frontmatter must list submit_lesson_draft in tools"
    )
    # The tool schema must also be loadable (not just named in frontmatter)
    schema = load_tool_schema("submit_lesson_draft", agents_dir=real_agents_dir)
    assert schema["name"] == "submit_lesson_draft"
    assert "parameters" in schema
    required = schema["parameters"].get("required", [])
    assert set(required) == {
        "overview",
        "how_it_works",
        "key_details",
        "what_to_watch_for",
        "cited_symbols",
        "uncertain_regions",
    }, f"submit_lesson_draft required fields mismatch: {required}"
    # Output format must be json (structured tool output)
    assert fm.output_contract.format == "json"
    # Body must contain the Output Format section
    assert "submit_lesson_draft" in body


def test_real_reviewer_card_loads(tmp_path: Path) -> None:
    real_agents_dir = (
        Path(__file__).parent.parent.parent.parent / "src" / "wiedunflow" / "use_cases" / "agents"
    )
    if not (real_agents_dir / "reviewer.md").exists():
        pytest.skip("Real agent cards not present in test environment")

    fm, _body = load_agent_card("reviewer", agents_dir=real_agents_dir)
    assert fm.name == "reviewer"
    assert fm.suggested_model_role == "small_fast"
    assert fm.output_contract.format == "json"
    assert "read_symbol_body" in fm.tools
    assert "grep_usages" in fm.tools


def test_real_tool_schemas_load(tmp_path: Path) -> None:
    """Smoke test: all 13 tool JSON schemas parse without error."""
    real_agents_dir = (
        Path(__file__).parent.parent.parent.parent / "src" / "wiedunflow" / "use_cases" / "agents"
    )
    if not (real_agents_dir / "tools").exists():
        pytest.skip("Real tool schemas not present in test environment")

    expected_tools = [
        "read_symbol_body",
        "get_callers",
        "get_callees",
        "search_docs",
        "read_tests",
        "grep_usages",
        "list_files_in_dir",
        "read_lines",
        "dispatch_researcher",
        "dispatch_writer",
        "dispatch_reviewer",
        "mark_lesson_done",
        "skip_lesson",
        "submit_verdict",
        "submit_lesson_draft",
    ]
    for tool_name in expected_tools:
        schema = load_tool_schema(tool_name, agents_dir=real_agents_dir)
        assert schema["name"] == tool_name, f"Tool {tool_name} has mismatched name field"
        assert "description" in schema
        assert "parameters" in schema
        assert schema["parameters"]["type"] == "object"


def test_real_compile_orchestrator_card(tmp_path: Path) -> None:
    """Compile the real orchestrator card with valid kwargs — checks all tool schemas resolve."""
    real_agents_dir = (
        Path(__file__).parent.parent.parent.parent / "src" / "wiedunflow" / "use_cases" / "agents"
    )
    if not (real_agents_dir / "orchestrator.md").exists():
        pytest.skip("Real agent cards not present in test environment")

    result = compile_card(
        "orchestrator",
        kwargs={
            "lesson_id": "lesson-01",
            "lesson_title": "Entry Point",
            "lesson_teaches": "How the CLI parses arguments",
            "primary_symbol": "cli.main.main",
            "code_refs": ["src/wiedunflow/cli/main.py:42"],
            "concepts_introduced": ["click", "argparse"],
            "budget_remaining_usd": 0.75,
        },
        agents_dir=real_agents_dir,
    )
    assert result.name == "orchestrator"
    assert "lesson-01" in result.system_prompt
    assert "0.75" in result.system_prompt
    assert len(result.tools) == 5
