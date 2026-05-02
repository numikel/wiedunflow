# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

_AGENTS_DIR = Path(__file__).parent

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def _safe_substitute(template: str, kwargs: dict[str, Any]) -> str:
    """Substitute ``{{name}}`` placeholders without mangling literal ``{`` or ``}``.

    Unlike :py:meth:`str.format`, this leaves single curly braces (e.g. JSON
    examples in agent prompt bodies) untouched. Only the ``{{name}}`` syntax
    (Mustache-/Jinja-like) is treated as a placeholder.

    Raises:
        KeyError: If a placeholder references a key not present in ``kwargs``.
    """

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in kwargs:
            raise KeyError(key)
        return str(kwargs[key])

    return _PLACEHOLDER_RE.sub(_replace, template)


class AgentCardBudgets(BaseModel):
    max_iterations: int = 15
    max_cost_usd: float = 0.50
    prompt_caching: bool = True
    max_retries: int = 1


class AgentCardOutputContract(BaseModel):
    format: Literal["text", "markdown_with_frontmatter", "json"]
    description: str = ""


class AgentCardFrontmatter(BaseModel):
    schema_version: int = 1
    name: str
    description: str
    suggested_model_role: Literal["smart_long_context", "small_fast", "quality_writer"]
    tools: list[str] = []
    budgets: AgentCardBudgets = AgentCardBudgets()
    input_schema: dict[str, str] = {}
    output_contract: AgentCardOutputContract


class CompiledCard(BaseModel):
    name: str
    system_prompt: str  # body after str.format(**kwargs)
    tools: list[dict[str, Any]]  # JSON schemas for API (OpenAI/Anthropic format)
    budgets: AgentCardBudgets
    output_contract: AgentCardOutputContract


def load_agent_card(
    name: str, *, agents_dir: Path | None = None
) -> tuple[AgentCardFrontmatter, str]:
    """Parse agent card file, return (frontmatter, raw_body_template).

    Args:
        name: Agent name (without .md extension).
        agents_dir: Override directory; defaults to the package's agents/ folder.

    Raises:
        FileNotFoundError: If the .md card file does not exist.
        ValueError: If the file lacks valid frontmatter delimiters or YAML is malformed.
    """
    base = agents_dir or _AGENTS_DIR
    card_path = base / f"{name}.md"
    if not card_path.exists():
        raise FileNotFoundError(f"Agent card not found: {card_path}")
    content = card_path.read_text(encoding="utf-8")
    # Split on first two --- markers; content is "---\n<fm>\n---\n<body>"
    # 3 parts expected: pre-marker (empty), frontmatter, body
    parts = content.split("---", 2)
    if len(parts) < 3:  # noqa: PLR2004
        raise ValueError(
            f"Invalid agent card format in {card_path}: missing frontmatter delimiters"
        )
    raw_fm = parts[1].strip()
    body = parts[2].strip()
    fm_dict = yaml.safe_load(raw_fm)
    frontmatter = AgentCardFrontmatter.model_validate(fm_dict)
    return frontmatter, body


def load_tool_schema(tool_name: str, *, agents_dir: Path | None = None) -> dict[str, Any]:
    """Load a single tool JSON schema from agents/tools/<name>.json.

    Args:
        tool_name: Tool name (without .json extension).
        agents_dir: Override directory; defaults to the package's agents/ folder.

    Raises:
        FileNotFoundError: If the tool schema file does not exist.
    """
    base = agents_dir or _AGENTS_DIR
    schema_path = base / "tools" / f"{tool_name}.json"
    if not schema_path.exists():
        raise FileNotFoundError(f"Tool schema not found: {schema_path}")
    return json.loads(schema_path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def compile_card(
    name: str,
    *,
    kwargs: dict[str, Any],
    agents_dir: Path | None = None,
) -> CompiledCard:
    """Load, validate, and format an agent card for use in an LLM call.

    Substitutes ``{{placeholder}}`` markers in the card body with provided
    kwargs values. Single curly braces (e.g. literal JSON examples in prompt
    bodies) are left intact. All keys declared in input_schema must be
    present in kwargs.

    Args:
        name: Agent name (matches <name>.md in agents_dir).
        kwargs: Values for every key declared in the card's input_schema.
        agents_dir: Override directory; defaults to the package's agents/ folder.

    Raises:
        ValueError: If any input_schema key is missing from kwargs.
        FileNotFoundError: If the card file or any referenced tool schema is missing.
        KeyError: If the body template references a placeholder not present in kwargs.
    """
    frontmatter, body_template = load_agent_card(name, agents_dir=agents_dir)
    # Validate that kwargs cover all declared input_schema keys
    missing = set(frontmatter.input_schema.keys()) - set(kwargs.keys())
    if missing:
        raise ValueError(f"Missing input_schema keys for agent '{name}': {missing}")
    system_prompt = _safe_substitute(body_template, kwargs)
    # Load tool JSON schemas referenced by this card
    tool_schemas = [
        load_tool_schema(tool_name, agents_dir=agents_dir) for tool_name in frontmatter.tools
    ]
    return CompiledCard(
        name=frontmatter.name,
        system_prompt=system_prompt,
        tools=tool_schemas,
        budgets=frontmatter.budgets,
        output_contract=frontmatter.output_contract,
    )
