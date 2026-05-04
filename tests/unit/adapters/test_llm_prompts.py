# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Smoke tests for the shared LLM system prompts module.

Both Anthropic and OpenAI adapters import the same constants from
``adapters.llm_prompts``. These tests guard against:
- accidental drift (constants reintroduced as local copies in a provider)
- trailing whitespace creeping back in
- the narration prompt losing its ``{concepts_introduced}`` placeholder
"""

from __future__ import annotations

import re

from wiedunflow.adapters import anthropic_provider, openai_provider
from wiedunflow.adapters.llm_prompts import (
    DESCRIBE_SYSTEM_PROMPT,
    NARRATE_SYSTEM_PROMPT,
    PLAN_SYSTEM_PROMPT,
)


def test_prompts_non_empty() -> None:
    assert PLAN_SYSTEM_PROMPT.strip()
    assert NARRATE_SYSTEM_PROMPT.strip()
    assert DESCRIBE_SYSTEM_PROMPT.strip()


def test_no_trailing_whitespace() -> None:
    """Trailing spaces caused subtle adapter drift in v0.9.4 — guard against it."""
    for name, prompt in (
        ("PLAN", PLAN_SYSTEM_PROMPT),
        ("NARRATE", NARRATE_SYSTEM_PROMPT),
        ("DESCRIBE", DESCRIBE_SYSTEM_PROMPT),
    ):
        for i, line in enumerate(prompt.splitlines(), start=1):
            assert line == line.rstrip(), (
                f"{name}_SYSTEM_PROMPT line {i} has trailing whitespace: {line!r}"
            )


def test_narrate_prompt_has_concepts_placeholder() -> None:
    """Adapters call ``.format(concepts_introduced=...)`` -- placeholder must exist."""
    assert "{concepts_introduced}" in NARRATE_SYSTEM_PROMPT
    # Smoke check the placeholder substitution renders cleanly.
    rendered = NARRATE_SYSTEM_PROMPT.format(concepts_introduced="X, Y, Z")
    assert "X, Y, Z" in rendered
    assert "{concepts_introduced}" not in rendered


def test_no_other_format_placeholders_in_plan_or_describe() -> None:
    """Plan/describe prompts are sent as-is — no ``str.format()`` substitution."""
    placeholder = re.compile(r"\{[a-z_][a-z0-9_]*\}")
    assert not placeholder.search(PLAN_SYSTEM_PROMPT)
    assert not placeholder.search(DESCRIBE_SYSTEM_PROMPT)


def test_anthropic_provider_uses_shared_constants() -> None:
    """Provider module references the canonical objects (no copy)."""
    assert anthropic_provider.PLAN_SYSTEM_PROMPT is PLAN_SYSTEM_PROMPT
    assert anthropic_provider.NARRATE_SYSTEM_PROMPT is NARRATE_SYSTEM_PROMPT
    assert anthropic_provider.DESCRIBE_SYSTEM_PROMPT is DESCRIBE_SYSTEM_PROMPT


def test_openai_provider_uses_shared_constants() -> None:
    assert openai_provider.PLAN_SYSTEM_PROMPT is PLAN_SYSTEM_PROMPT
    assert openai_provider.NARRATE_SYSTEM_PROMPT is NARRATE_SYSTEM_PROMPT
    assert openai_provider.DESCRIBE_SYSTEM_PROMPT is DESCRIBE_SYSTEM_PROMPT
