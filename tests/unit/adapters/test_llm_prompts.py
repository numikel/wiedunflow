# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Smoke tests for the shared LLM system prompts module.

Both Anthropic and OpenAI adapters import the same constants from
``adapters.llm_prompts``. These tests guard against:
- accidental drift (constants reintroduced as local copies in a provider)
- trailing whitespace creeping back in
"""

from __future__ import annotations

import re

from wiedunflow.adapters import anthropic_provider, openai_provider
from wiedunflow.adapters.llm_prompts import PLAN_SYSTEM_PROMPT


def test_plan_prompt_non_empty() -> None:
    assert PLAN_SYSTEM_PROMPT.strip()


def test_no_trailing_whitespace() -> None:
    """Trailing spaces caused subtle adapter drift in v0.9.4 — guard against it."""
    for i, line in enumerate(PLAN_SYSTEM_PROMPT.splitlines(), start=1):
        assert line == line.rstrip(), (
            f"PLAN_SYSTEM_PROMPT line {i} has trailing whitespace: {line!r}"
        )


def test_no_format_placeholders_in_plan() -> None:
    """Plan prompt is sent as-is — no ``str.format()`` substitution."""
    placeholder = re.compile(r"\{[a-z_][a-z0-9_]*\}")
    assert not placeholder.search(PLAN_SYSTEM_PROMPT)


def test_anthropic_provider_uses_shared_plan_constant() -> None:
    """Provider module references the canonical object (no copy)."""
    assert anthropic_provider.PLAN_SYSTEM_PROMPT is PLAN_SYSTEM_PROMPT


def test_openai_provider_uses_shared_plan_constant() -> None:
    assert openai_provider.PLAN_SYSTEM_PROMPT is PLAN_SYSTEM_PROMPT
