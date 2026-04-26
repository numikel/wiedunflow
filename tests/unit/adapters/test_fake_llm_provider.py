# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for FakeLLMProvider — deterministic stub used in e2e tests."""

from __future__ import annotations

from pathlib import Path

from wiedunflow.adapters.fake_llm_provider import FakeLLMProvider
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.interfaces.ports import LLMProvider


def _mk_symbol(
    name: str = "calculator.add",
    kind: str = "function",
    docstring: str | None = "Add two integers together.",
) -> CodeSymbol:
    return CodeSymbol(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        file_path=Path("calculator.py"),
        lineno=1,
        docstring=docstring,
    )


def test_fake_satisfies_llm_provider_protocol() -> None:
    """FakeLLMProvider must structurally match the LLMProvider Protocol."""
    fake = FakeLLMProvider()
    assert isinstance(fake, LLMProvider)


def test_describe_symbol_returns_deterministic_description() -> None:
    """describe_symbol() returns the same text for the same symbol across calls."""
    fake = FakeLLMProvider()
    symbol = _mk_symbol()
    a = fake.describe_symbol(symbol, context="irrelevant context")
    b = fake.describe_symbol(symbol, context="different context")
    assert a == b


def test_describe_symbol_mentions_symbol_name_and_kind() -> None:
    """The stub description surfaces the symbol's qualified name and kind."""
    fake = FakeLLMProvider()
    description = fake.describe_symbol(_mk_symbol(name="pkg.mod.foo"), context="")
    assert "pkg.mod.foo" in description
    assert "function" in description


def test_describe_symbol_handles_missing_docstring() -> None:
    """Symbols without a docstring still produce a stable description."""
    fake = FakeLLMProvider()
    symbol = _mk_symbol(docstring=None)
    description = fake.describe_symbol(symbol, context="")
    assert "no docstring available" in description


def test_describe_symbol_embeds_first_docstring_line() -> None:
    """Multi-line docstrings are truncated to the first line in the stub."""
    fake = FakeLLMProvider()
    symbol = _mk_symbol(docstring="First summary line.\n\nExtended description.")
    description = fake.describe_symbol(symbol, context="")
    assert "First summary line." in description
    assert "Extended description." not in description
