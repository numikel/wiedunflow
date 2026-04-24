# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for AnthropicProvider."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pydantic
import pytest
from anthropic.types import TextBlock

from codeguide.adapters.anthropic_provider import AnthropicProvider
from codeguide.entities.code_symbol import CodeSymbol
from codeguide.entities.lesson_manifest import LessonManifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_response(text: str) -> MagicMock:
    """Build a mock anthropic.Message with a single real TextBlock."""
    resp = MagicMock()
    resp.content = [TextBlock(type="text", text=text)]
    return resp


def _valid_manifest_json() -> str:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "lessons": [
                {
                    "id": "lesson-001",
                    "title": "Hello",
                    "teaches": "basics",
                    "prerequisites": [],
                    "code_refs": [],
                    "external_context_needed": False,
                }
            ],
        }
    )


def _fake_rate_limit_error() -> anthropic.RateLimitError:
    """Construct a minimal RateLimitError without a real HTTP response."""
    fake_response = httpx.Response(
        status_code=429,
        headers={"x-request-id": "test"},
        content=b'{"error": {"type": "rate_limit_error", "message": "rate limited"}}',
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    return anthropic.RateLimitError(
        message="rate limited",
        response=fake_response,
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )


# ---------------------------------------------------------------------------
# Test: __init__
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_init_requires_api_key(mock_cls, monkeypatch):
    """No api_key arg and no env var → ValueError."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is required"):
        AnthropicProvider(api_key=None)


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_init_uses_env_key(mock_cls, monkeypatch):
    """ANTHROPIC_API_KEY env var is picked up when api_key= is not passed."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env-test")
    mock_cls.return_value = MagicMock()
    provider = AnthropicProvider()
    mock_cls.assert_called_once_with(api_key="sk-env-test")
    assert provider is not None


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_init_explicit_key_wins(mock_cls, monkeypatch):
    """Explicit api_key= overrides ANTHROPIC_API_KEY env var."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    mock_cls.return_value = MagicMock()
    AnthropicProvider(api_key="sk-explicit")
    mock_cls.assert_called_once_with(api_key="sk-explicit")


# ---------------------------------------------------------------------------
# Test: plan()
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_plan_uses_sonnet_model(mock_cls, monkeypatch):
    """plan() calls messages.create with the plan model and correct max_tokens."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response(_valid_manifest_json())
    mock_cls.return_value = mock_client

    provider = AnthropicProvider()
    manifest = provider.plan("some outline text")

    assert mock_client.messages.create.call_count == 1
    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 8000
    assert kwargs["messages"] == [{"role": "user", "content": "some outline text"}]
    assert isinstance(manifest, LessonManifest)
    assert len(manifest.lessons) == 1


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_plan_custom_model(mock_cls, monkeypatch):
    """model_plan= constructor arg is forwarded to messages.create."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response(_valid_manifest_json())
    mock_cls.return_value = mock_client

    provider = AnthropicProvider(model_plan="claude-sonnet-4-5")
    provider.plan("outline")

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-5"


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_plan_invalid_json_raises(mock_cls, monkeypatch):
    """Malformed JSON response from plan() propagates pydantic.ValidationError."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response("not valid json at all")
    mock_cls.return_value = mock_client

    provider = AnthropicProvider()
    with pytest.raises((pydantic.ValidationError, ValueError)):
        provider.plan("outline")


# ---------------------------------------------------------------------------
# Test: narrate()
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_narrate_uses_opus_model(mock_cls, monkeypatch):
    """narrate() calls messages.create with the narrate model and correct max_tokens."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response("## Lesson narrative here")
    mock_cls.return_value = mock_client

    spec = json.dumps({"id": "lesson-001", "title": "Test Lesson", "code_refs": ["module.func"]})
    provider = AnthropicProvider()
    lesson = provider.narrate(spec, concepts_introduced=("concept_a",))

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-4-7"
    assert kwargs["max_tokens"] == 4000
    assert lesson.id == "lesson-001"
    assert lesson.title == "Test Lesson"
    assert lesson.narrative == "## Lesson narrative here"
    assert "module.func" in lesson.code_refs


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_narrate_system_prompt_includes_concepts(mock_cls, monkeypatch):
    """narrate() injects concepts_introduced into the system prompt."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response("## narrative")
    mock_cls.return_value = mock_client

    spec = json.dumps({"id": "l-1", "title": "T", "code_refs": []})
    provider = AnthropicProvider()
    provider.narrate(spec, concepts_introduced=("alpha", "beta"))

    system_prompt = mock_client.messages.create.call_args.kwargs["system"]
    assert "alpha" in system_prompt
    assert "beta" in system_prompt


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_narrate_no_concepts_uses_placeholder(mock_cls, monkeypatch):
    """narrate() with empty concepts_introduced uses '<none yet>' placeholder."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response("## narrative")
    mock_cls.return_value = mock_client

    spec = json.dumps({"id": "l-1", "title": "T", "code_refs": []})
    provider = AnthropicProvider()
    provider.narrate(spec, concepts_introduced=())

    system_prompt = mock_client.messages.create.call_args.kwargs["system"]
    assert "<none yet>" in system_prompt


# ---------------------------------------------------------------------------
# Test: describe_symbol()
# ---------------------------------------------------------------------------


def _mk_symbol(
    name: str = "calculator.add",
    kind: str = "function",
    docstring: str | None = "Add two integers.",
    is_dynamic_import: bool = False,
    is_uncertain: bool = False,
) -> CodeSymbol:
    """Build a CodeSymbol for describe_symbol tests."""
    return CodeSymbol(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        file_path=Path("calculator.py"),
        lineno=1,
        docstring=docstring,
        is_dynamic_import=is_dynamic_import,
        is_uncertain=is_uncertain,
    )


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_describe_symbol_uses_haiku_model(mock_cls, monkeypatch):
    """describe_symbol() calls messages.create with the describe model and tight max_tokens."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response(
        "A simple addition helper for two integers."
    )
    mock_cls.return_value = mock_client

    provider = AnthropicProvider()
    description = provider.describe_symbol(_mk_symbol(), context="def add(a, b): return a + b")

    assert mock_client.messages.create.call_count == 1
    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["max_tokens"] == 300
    assert description == "A simple addition helper for two integers."


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_describe_symbol_custom_model(mock_cls, monkeypatch):
    """model_describe= constructor arg is forwarded to messages.create."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response("desc")
    mock_cls.return_value = mock_client

    provider = AnthropicProvider(model_describe="claude-haiku-4-6")
    provider.describe_symbol(_mk_symbol(), context="ctx")

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-6"


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_describe_symbol_prompt_includes_symbol_metadata(mock_cls, monkeypatch):
    """describe_symbol() user prompt embeds symbol name, kind, file, docstring."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response("desc")
    mock_cls.return_value = mock_client

    symbol = _mk_symbol(name="pkg.mod.foo", kind="function", docstring="Does foo.")
    provider = AnthropicProvider()
    provider.describe_symbol(symbol, context="<source snippet>")

    user_prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "pkg.mod.foo" in user_prompt
    assert "function" in user_prompt
    assert "Does foo." in user_prompt
    assert "<source snippet>" in user_prompt


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_describe_symbol_flags_dynamic_and_uncertain(mock_cls, monkeypatch):
    """describe_symbol() surfaces is_dynamic_import / is_uncertain flags in the prompt."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response("desc")
    mock_cls.return_value = mock_client

    symbol = _mk_symbol(is_dynamic_import=True, is_uncertain=True)
    provider = AnthropicProvider()
    provider.describe_symbol(symbol, context="ctx")

    user_prompt = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "dynamic-import" in user_prompt
    assert "uncertain-resolution" in user_prompt


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_describe_symbol_strips_whitespace(mock_cls, monkeypatch):
    """Leading/trailing whitespace in the model response is stripped."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _mk_response("\n\n  actual text  \n\n")
    mock_cls.return_value = mock_client

    provider = AnthropicProvider()
    description = provider.describe_symbol(_mk_symbol(), context="ctx")

    assert description == "actual text"


# ---------------------------------------------------------------------------
# Test: retry behaviour
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_retry_on_rate_limit_succeeds(mock_cls, monkeypatch):
    """Two RateLimitErrors followed by a success → returns result, logs backoffs."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    err = _fake_rate_limit_error()
    mock_client.messages.create.side_effect = [
        err,
        err,
        _mk_response(_valid_manifest_json()),
    ]
    mock_cls.return_value = mock_client

    logged_events: list[str] = []

    with patch(
        "codeguide.adapters.anthropic_provider._log_backoff",
        side_effect=lambda rs: logged_events.append("backoff"),
    ):
        # Use tiny wait so the test doesn't actually sleep long
        provider = AnthropicProvider(max_retries=5, max_wait_s=1)
        manifest = provider.plan("outline")

    assert isinstance(manifest, LessonManifest)
    assert mock_client.messages.create.call_count == 3
    assert len(logged_events) == 2, "Expected two backoff log calls"


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_retry_exhausted_reraises(mock_cls, monkeypatch):
    """After max_retries RateLimitErrors tenacity reraises the final exception."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()
    err = _fake_rate_limit_error()
    # Always raise — will exhaust 5 attempts
    mock_client.messages.create.side_effect = err
    mock_cls.return_value = mock_client

    provider = AnthropicProvider(max_retries=5, max_wait_s=1)

    with (
        patch("codeguide.adapters.anthropic_provider._log_backoff"),
        pytest.raises(anthropic.RateLimitError),
    ):
        provider.plan("outline")

    assert mock_client.messages.create.call_count == 5


# ---------------------------------------------------------------------------
# Test: multi-block response concatenation
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.anthropic_provider.anthropic.Anthropic")
def test_multiple_text_blocks_concatenated(mock_cls, monkeypatch):
    """Response with multiple text blocks are concatenated in order."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    mock_client = MagicMock()

    resp = MagicMock()
    resp.content = [
        TextBlock(type="text", text='{"schema_version":"1.0.0","lessons":['),
        TextBlock(type="text", text="]}"),
    ]
    mock_client.messages.create.return_value = resp
    mock_cls.return_value = mock_client

    provider = AnthropicProvider()
    manifest = provider.plan("outline")
    assert isinstance(manifest, LessonManifest)
    assert manifest.lessons == ()
