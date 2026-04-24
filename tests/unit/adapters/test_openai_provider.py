# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for OpenAIProvider."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import openai
import pydantic
import pytest

from codeguide.adapters.openai_provider import OpenAIProvider
from codeguide.entities.code_symbol import CodeSymbol
from codeguide.entities.lesson_manifest import LessonManifest
from codeguide.interfaces.ports import LLMProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_response(text: str) -> MagicMock:
    """Build a mock openai ChatCompletion with a single message content."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
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


def _fake_rate_limit_error() -> openai.RateLimitError:
    """Construct a minimal RateLimitError without a real HTTP response."""
    fake_response = httpx.Response(
        status_code=429,
        headers={"x-request-id": "test"},
        content=b'{"error": {"type": "rate_limit_error", "message": "rate limited"}}',
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    return openai.RateLimitError(
        message="rate limited",
        response=fake_response,
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )


def _fake_timeout_error() -> openai.APITimeoutError:
    """Construct a minimal APITimeoutError."""
    fake_request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    return openai.APITimeoutError(request=fake_request)


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


# ---------------------------------------------------------------------------
# Test: __init__
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_init_requires_api_key_without_base_url(mock_cls, monkeypatch):
    """No api_key arg, no base_url, no env var → ValueError mentioning OPENAI_API_KEY."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
        OpenAIProvider(api_key=None, base_url=None)


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_init_no_api_key_with_base_url_uses_placeholder(mock_cls, monkeypatch):
    """No api_key + base_url set → provider created with api_key='not-needed'."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    mock_cls.return_value = MagicMock()
    provider = OpenAIProvider(api_key=None, base_url="http://localhost:11434/v1")
    assert provider is not None
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["api_key"] == "not-needed"
    assert call_kwargs["base_url"] == "http://localhost:11434/v1"


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_init_uses_env_key(mock_cls, monkeypatch):
    """OPENAI_API_KEY env var is picked up when api_key= is not passed."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-test")
    mock_cls.return_value = MagicMock()
    provider = OpenAIProvider()
    assert provider is not None
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["api_key"] == "sk-env-test"


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_init_explicit_key_wins_over_env(mock_cls, monkeypatch):
    """Explicit api_key= overrides OPENAI_API_KEY env var."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    mock_cls.return_value = MagicMock()
    OpenAIProvider(api_key="sk-explicit")
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["api_key"] == "sk-explicit"


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_init_sdk_created_with_max_retries_zero(mock_cls, monkeypatch):
    """OpenAI SDK must be initialised with max_retries=0 — tenacity owns retry logic."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_cls.return_value = MagicMock()
    OpenAIProvider()
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["max_retries"] == 0


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_init_base_url_forwarded_to_sdk(mock_cls, monkeypatch):
    """base_url constructor arg is forwarded to the OpenAI SDK constructor."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    mock_cls.return_value = MagicMock()
    OpenAIProvider(base_url="http://localhost:11434/v1")
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["base_url"] == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# Test: LLMProvider protocol
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_implements_llm_provider_protocol(mock_cls, monkeypatch):
    """OpenAIProvider satisfies the runtime-checkable LLMProvider Protocol."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_cls.return_value = MagicMock()
    provider = OpenAIProvider()
    assert isinstance(provider, LLMProvider)


# ---------------------------------------------------------------------------
# Test: plan()
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_plan_uses_model_plan(mock_cls, monkeypatch):
    """plan() calls chat.completions.create with model_plan and json_object response_format."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response(_valid_manifest_json())
    mock_cls.return_value = mock_client

    provider = OpenAIProvider()
    manifest = provider.plan("some outline text")

    assert mock_client.chat.completions.create.call_count == 1
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["max_tokens"] == 8000
    assert kwargs["response_format"] == {"type": "json_object"}
    assert isinstance(manifest, LessonManifest)
    assert len(manifest.lessons) == 1


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_plan_user_message_contains_outline(mock_cls, monkeypatch):
    """plan() user message includes the provided outline text."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response(_valid_manifest_json())
    mock_cls.return_value = mock_client

    provider = OpenAIProvider()
    provider.plan("my outline text")

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    user_messages = [m for m in kwargs["messages"] if m["role"] == "user"]
    assert len(user_messages) == 1
    assert "my outline text" in user_messages[0]["content"]


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_plan_invalid_json_raises(mock_cls, monkeypatch):
    """Malformed JSON response from plan() propagates pydantic.ValidationError or ValueError."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response("not valid json at all")
    mock_cls.return_value = mock_client

    provider = OpenAIProvider()
    with pytest.raises((pydantic.ValidationError, ValueError)):
        provider.plan("outline")


# ---------------------------------------------------------------------------
# Test: describe_symbol()
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_describe_symbol_uses_model_describe(mock_cls, monkeypatch):
    """describe_symbol() calls chat.completions.create with model_describe and tight max_tokens."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response(
        "A simple addition helper for two integers."
    )
    mock_cls.return_value = mock_client

    provider = OpenAIProvider()
    description = provider.describe_symbol(_mk_symbol(), context="def add(a, b): return a + b")

    assert mock_client.chat.completions.create.call_count == 1
    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["max_tokens"] == 300
    assert description == "A simple addition helper for two integers."


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_describe_symbol_no_response_format(mock_cls, monkeypatch):
    """describe_symbol() does NOT pass response_format (plain prose, not JSON)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response("desc")
    mock_cls.return_value = mock_client

    provider = OpenAIProvider()
    provider.describe_symbol(_mk_symbol(), context="ctx")

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert "response_format" not in kwargs


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_describe_symbol_prompt_includes_symbol_metadata(mock_cls, monkeypatch):
    """describe_symbol() user prompt embeds symbol name, kind, file, docstring."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response("desc")
    mock_cls.return_value = mock_client

    symbol = _mk_symbol(name="pkg.mod.foo", kind="function", docstring="Does foo.")
    provider = OpenAIProvider()
    provider.describe_symbol(symbol, context="<source snippet>")

    user_messages = [
        m
        for m in mock_client.chat.completions.create.call_args.kwargs["messages"]
        if m["role"] == "user"
    ]
    assert len(user_messages) == 1
    prompt = user_messages[0]["content"]
    assert "pkg.mod.foo" in prompt
    assert "function" in prompt
    assert "Does foo." in prompt
    assert "<source snippet>" in prompt


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_describe_symbol_flags_dynamic_and_uncertain(mock_cls, monkeypatch):
    """describe_symbol() surfaces is_dynamic_import / is_uncertain flags in the prompt."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response("desc")
    mock_cls.return_value = mock_client

    symbol = _mk_symbol(is_dynamic_import=True, is_uncertain=True)
    provider = OpenAIProvider()
    provider.describe_symbol(symbol, context="ctx")

    user_messages = [
        m
        for m in mock_client.chat.completions.create.call_args.kwargs["messages"]
        if m["role"] == "user"
    ]
    prompt = user_messages[0]["content"]
    assert "dynamic-import" in prompt
    assert "uncertain-resolution" in prompt


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_describe_symbol_strips_whitespace(mock_cls, monkeypatch):
    """Leading/trailing whitespace in the model response is stripped."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response("\n\n  actual text  \n\n")
    mock_cls.return_value = mock_client

    provider = OpenAIProvider()
    description = provider.describe_symbol(_mk_symbol(), context="ctx")

    assert description == "actual text"


# ---------------------------------------------------------------------------
# Test: narrate()
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_narrate_uses_model_narrate(mock_cls, monkeypatch):
    """narrate() calls chat.completions.create with model_narrate and correct max_tokens."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response("## Lesson narrative here")
    mock_cls.return_value = mock_client

    spec = json.dumps({"id": "lesson-001", "title": "Test Lesson", "code_refs": ["module.func"]})
    provider = OpenAIProvider()
    lesson = provider.narrate(spec, concepts_introduced=("concept_a",))

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["max_tokens"] == 4000
    assert lesson.id == "lesson-001"
    assert lesson.title == "Test Lesson"
    assert lesson.narrative == "## Lesson narrative here"
    assert "module.func" in lesson.code_refs


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_narrate_system_prompt_includes_concepts(mock_cls, monkeypatch):
    """narrate() injects concepts_introduced into the system prompt."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response("## narrative")
    mock_cls.return_value = mock_client

    spec = json.dumps({"id": "l-1", "title": "T", "code_refs": []})
    provider = OpenAIProvider()
    provider.narrate(spec, concepts_introduced=("alpha", "beta"))

    system_messages = [
        m
        for m in mock_client.chat.completions.create.call_args.kwargs["messages"]
        if m["role"] == "system"
    ]
    system_prompt = system_messages[0]["content"]
    assert "alpha" in system_prompt
    assert "beta" in system_prompt


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_narrate_no_concepts_uses_placeholder(mock_cls, monkeypatch):
    """narrate() with empty concepts_introduced uses '<none yet>' placeholder."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response("## narrative")
    mock_cls.return_value = mock_client

    spec = json.dumps({"id": "l-1", "title": "T", "code_refs": []})
    provider = OpenAIProvider()
    provider.narrate(spec, concepts_introduced=())

    system_messages = [
        m
        for m in mock_client.chat.completions.create.call_args.kwargs["messages"]
        if m["role"] == "system"
    ]
    system_prompt = system_messages[0]["content"]
    assert "<none yet>" in system_prompt


# ---------------------------------------------------------------------------
# Test: retry behaviour
# ---------------------------------------------------------------------------


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_retry_on_rate_limit_succeeds(mock_cls, monkeypatch):
    """Two RateLimitErrors followed by a success → returns result, logs backoffs."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    err = _fake_rate_limit_error()
    mock_client.chat.completions.create.side_effect = [
        err,
        err,
        _mk_response(_valid_manifest_json()),
    ]
    mock_cls.return_value = mock_client

    logged_events: list[str] = []

    with patch(
        "codeguide.adapters.openai_provider._log_backoff",
        side_effect=lambda rs: logged_events.append("backoff"),
    ):
        provider = OpenAIProvider(max_retries=5, max_wait_s=1)
        manifest = provider.plan("outline")

    assert isinstance(manifest, LessonManifest)
    assert mock_client.chat.completions.create.call_count == 3
    assert len(logged_events) == 2, "Expected two backoff log calls"


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_retry_on_timeout_succeeds(mock_cls, monkeypatch):
    """Two APITimeoutErrors followed by a success → returns result."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    err = _fake_timeout_error()
    mock_client.chat.completions.create.side_effect = [
        err,
        err,
        _mk_response(_valid_manifest_json()),
    ]
    mock_cls.return_value = mock_client

    with patch("codeguide.adapters.openai_provider._log_backoff"):
        provider = OpenAIProvider(max_retries=5, max_wait_s=1)
        manifest = provider.plan("outline")

    assert isinstance(manifest, LessonManifest)
    assert mock_client.chat.completions.create.call_count == 3


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_retry_exhausted_reraises_rate_limit(mock_cls, monkeypatch):
    """After max_retries RateLimitErrors tenacity reraises the final exception."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    err = _fake_rate_limit_error()
    mock_client.chat.completions.create.side_effect = err
    mock_cls.return_value = mock_client

    provider = OpenAIProvider(max_retries=5, max_wait_s=1)

    with (
        patch("codeguide.adapters.openai_provider._log_backoff"),
        pytest.raises(openai.RateLimitError),
    ):
        provider.plan("outline")

    assert mock_client.chat.completions.create.call_count == 5


@patch("codeguide.adapters.openai_provider.OpenAI")
def test_auth_error_not_retried(mock_cls, monkeypatch):
    """AuthenticationError is NOT retried — auth failures are not transient."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    fake_response = httpx.Response(
        status_code=401,
        headers={"x-request-id": "test"},
        content=b'{"error": {"type": "invalid_request_error", "message": "Invalid API key"}}',
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    auth_err = openai.AuthenticationError(
        message="Invalid API key",
        response=fake_response,
        body={"error": {"type": "invalid_request_error", "message": "Invalid API key"}},
    )
    mock_client.chat.completions.create.side_effect = auth_err
    mock_cls.return_value = mock_client

    provider = OpenAIProvider(max_retries=5, max_wait_s=1)

    with pytest.raises(openai.AuthenticationError):
        provider.plan("outline")

    # Auth errors must NOT be retried — exactly 1 call
    assert mock_client.chat.completions.create.call_count == 1
