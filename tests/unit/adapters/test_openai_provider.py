# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Unit tests for OpenAIProvider."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import httpx
import openai
import pydantic
import pytest

from wiedunflow.adapters.openai_provider import (
    OpenAIProvider,
    _uses_max_completion_tokens,
)
from wiedunflow.entities.lesson_manifest import LessonManifest
from wiedunflow.interfaces.ports import LLMProvider

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


# ---------------------------------------------------------------------------
# Test: __init__
# ---------------------------------------------------------------------------


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_requires_api_key_without_base_url(mock_cls, monkeypatch):
    """No api_key arg, no base_url, no env var → ValueError mentioning OPENAI_API_KEY."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
        OpenAIProvider(api_key=None, base_url=None)


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_no_api_key_with_base_url_uses_placeholder(mock_cls, monkeypatch):
    """No api_key + base_url set → provider created with api_key='not-needed'."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    mock_cls.return_value = MagicMock()
    provider = OpenAIProvider(api_key=None, base_url="http://localhost:11434/v1")
    assert provider is not None
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["api_key"] == "not-needed"
    assert call_kwargs["base_url"] == "http://localhost:11434/v1"


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_uses_env_key(mock_cls, monkeypatch):
    """OPENAI_API_KEY env var is picked up when api_key= is not passed."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-test")
    mock_cls.return_value = MagicMock()
    provider = OpenAIProvider()
    assert provider is not None
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["api_key"] == "sk-env-test"


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_explicit_key_wins_over_env(mock_cls, monkeypatch):
    """Explicit api_key= overrides OPENAI_API_KEY env var."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    mock_cls.return_value = MagicMock()
    OpenAIProvider(api_key="sk-explicit")
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["api_key"] == "sk-explicit"


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_sdk_created_with_max_retries_zero(mock_cls, monkeypatch):
    """OpenAI SDK must be initialised with max_retries=0 — tenacity owns retry logic."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_cls.return_value = MagicMock()
    OpenAIProvider()
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["max_retries"] == 0


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_base_url_forwarded_to_sdk(mock_cls, monkeypatch):
    """base_url constructor arg is forwarded to the OpenAI SDK constructor."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    mock_cls.return_value = MagicMock()
    OpenAIProvider(base_url="http://localhost:11434/v1")
    call_kwargs = mock_cls.call_args.kwargs
    assert call_kwargs["base_url"] == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# Test: __init__ HTTP read timeout (config > env > base_url-derived auto)
# ---------------------------------------------------------------------------


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_default_cloud_timeout_is_55s(mock_cls, monkeypatch):
    """Without base_url and without overrides, cloud read timeout stays 55s."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("WIEDUNFLOW_HTTP_READ_TIMEOUT", raising=False)
    mock_cls.return_value = MagicMock()
    OpenAIProvider()
    timeout = mock_cls.call_args.kwargs["timeout"]
    assert timeout.read == 55.0


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_oss_base_url_auto_bumps_timeout_to_600s(mock_cls, monkeypatch):
    """Setting base_url (Ollama / LM Studio / vLLM) auto-bumps read timeout to 600s.

    Cloud's 55s is fine for hosted APIs but cuts off a Stage 5 planning call
    against a 13B+ model running on CPU before it can stream anything back.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WIEDUNFLOW_HTTP_READ_TIMEOUT", raising=False)
    mock_cls.return_value = MagicMock()
    OpenAIProvider(base_url="http://localhost:11434/v1")
    timeout = mock_cls.call_args.kwargs["timeout"]
    assert timeout.read == 600.0


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_explicit_param_overrides_auto(mock_cls, monkeypatch):
    """An explicit http_read_timeout_s wins over both env var and base_url auto-bump."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("WIEDUNFLOW_HTTP_READ_TIMEOUT", "999")
    mock_cls.return_value = MagicMock()
    OpenAIProvider(base_url="http://localhost:11434/v1", http_read_timeout_s=120)
    timeout = mock_cls.call_args.kwargs["timeout"]
    assert timeout.read == 120.0


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_env_var_overrides_auto_when_no_explicit_param(mock_cls, monkeypatch):
    """The env var overrides auto-detection but loses to an explicit param."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("WIEDUNFLOW_HTTP_READ_TIMEOUT", "200")
    mock_cls.return_value = MagicMock()
    OpenAIProvider()  # cloud + env var, no explicit param
    timeout = mock_cls.call_args.kwargs["timeout"]
    assert timeout.read == 200.0


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_init_invalid_env_var_raises_value_error(mock_cls, monkeypatch):
    """A non-numeric WIEDUNFLOW_HTTP_READ_TIMEOUT must surface a clear ValueError."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("WIEDUNFLOW_HTTP_READ_TIMEOUT", "abc")
    mock_cls.return_value = MagicMock()
    with pytest.raises(ValueError, match="WIEDUNFLOW_HTTP_READ_TIMEOUT"):
        OpenAIProvider()


# ---------------------------------------------------------------------------
# Test: LLMProvider protocol
# ---------------------------------------------------------------------------


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_implements_llm_provider_protocol(mock_cls, monkeypatch):
    """OpenAIProvider satisfies the runtime-checkable LLMProvider Protocol."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_cls.return_value = MagicMock()
    provider = OpenAIProvider()
    assert isinstance(provider, LLMProvider)


# ---------------------------------------------------------------------------
# Test: plan()
# ---------------------------------------------------------------------------


@patch("wiedunflow.adapters.openai_provider.OpenAI")
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
    assert kwargs["model"] == "gpt-5.4"
    # gpt-5.4 is a newer OpenAI family → uses max_completion_tokens, not max_tokens
    assert kwargs["max_completion_tokens"] == 8000
    assert kwargs["response_format"] == {"type": "json_object"}
    assert isinstance(manifest, LessonManifest)
    assert len(manifest.lessons) == 1


@patch("wiedunflow.adapters.openai_provider.OpenAI")
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


@patch("wiedunflow.adapters.openai_provider.OpenAI")
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
# Test: retry behaviour
# ---------------------------------------------------------------------------


@patch("wiedunflow.adapters.openai_provider.OpenAI")
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
        "wiedunflow.adapters.openai_provider._log_backoff",
        side_effect=lambda rs: logged_events.append("backoff"),
    ):
        provider = OpenAIProvider(max_retries=5, max_wait_s=1)
        manifest = provider.plan("outline")

    assert isinstance(manifest, LessonManifest)
    assert mock_client.chat.completions.create.call_count == 3
    assert len(logged_events) == 2, "Expected two backoff log calls"


@patch("wiedunflow.adapters.openai_provider.OpenAI")
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

    with patch("wiedunflow.adapters.openai_provider._log_backoff"):
        provider = OpenAIProvider(max_retries=5, max_wait_s=1)
        manifest = provider.plan("outline")

    assert isinstance(manifest, LessonManifest)
    assert mock_client.chat.completions.create.call_count == 3


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_retry_exhausted_reraises_rate_limit(mock_cls, monkeypatch):
    """After max_retries RateLimitErrors tenacity reraises the final exception."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    err = _fake_rate_limit_error()
    mock_client.chat.completions.create.side_effect = err
    mock_cls.return_value = mock_client

    provider = OpenAIProvider(max_retries=5, max_wait_s=1)

    with (
        patch("wiedunflow.adapters.openai_provider._log_backoff"),
        pytest.raises(openai.RateLimitError),
    ):
        provider.plan("outline")

    assert mock_client.chat.completions.create.call_count == 5


@patch("wiedunflow.adapters.openai_provider.OpenAI")
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


# ---------------------------------------------------------------------------
# Test: max_completion_tokens vs max_tokens routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4o", False),
        ("gpt-4o-mini", False),
        ("gpt-4-turbo", False),
        ("gpt-3.5-turbo", False),
        ("o1", True),
        ("o1-preview", True),
        ("o3-mini", True),
        ("o4-mini", True),
        ("gpt-5", True),
        ("gpt-5.4", True),
        ("gpt-5.4-mini", True),
        ("GPT-5.4-MINI", True),  # case-insensitive
        ("  o1-preview  ", True),  # whitespace-tolerant
    ],
)
def test_uses_max_completion_tokens_detection(model: str, expected: bool) -> None:
    """Newer OpenAI families (o1/o3/o4/gpt-5) require max_completion_tokens."""
    assert _uses_max_completion_tokens(model) is expected


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_plan_gpt5_uses_max_completion_tokens(mock_cls, monkeypatch):
    """plan() with gpt-5* swaps max_tokens → max_completion_tokens (avoids 400 BadRequest)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _mk_response(_valid_manifest_json())
    mock_cls.return_value = mock_client

    provider = OpenAIProvider(model_plan="gpt-5.4-mini")
    provider.plan("outline")

    kwargs = mock_client.chat.completions.create.call_args.kwargs
    assert "max_completion_tokens" in kwargs
    assert kwargs["max_completion_tokens"] == 8000
    assert "max_tokens" not in kwargs


# ---------------------------------------------------------------------------
# Test: run_agent inner-loop retry via _create_with_retry_raw
# ---------------------------------------------------------------------------


def _fake_internal_server_error() -> openai.InternalServerError:
    """Construct a minimal InternalServerError without a real HTTP response."""
    fake_response = httpx.Response(
        status_code=500,
        headers={"x-request-id": "test"},
        content=b'{"error": {"type": "server_error", "message": "internal server error"}}',
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )
    return openai.InternalServerError(
        message="internal server error",
        response=fake_response,
        body={"error": {"type": "server_error", "message": "internal server error"}},
    )


def _mk_agent_response(text: str = "ok") -> MagicMock:
    """Build a minimal mock ChatCompletion for run_agent loop iteration."""
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = text
    resp.choices[0].message.tool_calls = None
    resp.choices[0].finish_reason = "stop"
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    resp.usage.prompt_tokens_details = None
    return resp


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_retries_rate_limit(mock_cls, monkeypatch):
    """RateLimitError mid-run_agent iteration → retried transparently without re-raise."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    err = _fake_rate_limit_error()
    # First call raises 429, second call succeeds.
    mock_client.chat.completions.create.side_effect = [err, _mk_agent_response("done")]
    mock_cls.return_value = mock_client

    from wiedunflow.interfaces.ports import ToolResult

    provider = OpenAIProvider(max_retries=3, max_wait_s=1)

    with patch("wiedunflow.adapters.openai_provider._log_backoff"):
        result = provider.run_agent(
            system="sys",
            user="user",
            tools=[],
            tool_executor=lambda tc: ToolResult(tool_call_id=tc.id, content="x", is_error=False),
            model="gpt-5.4-mini",
            max_iterations=5,
        )

    assert result.stop_reason == "end_turn"
    assert mock_client.chat.completions.create.call_count == 2


@patch("wiedunflow.adapters.openai_provider.OpenAI")
def test_run_agent_retries_internal_server_error(mock_cls, monkeypatch):
    """InternalServerError mid-run_agent iteration → retried transparently."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    mock_client = MagicMock()
    err = _fake_internal_server_error()
    mock_client.chat.completions.create.side_effect = [err, _mk_agent_response("done")]
    mock_cls.return_value = mock_client

    from wiedunflow.interfaces.ports import ToolResult

    provider = OpenAIProvider(max_retries=3, max_wait_s=1)

    with patch("wiedunflow.adapters.openai_provider._log_backoff"):
        result = provider.run_agent(
            system="sys",
            user="user",
            tools=[],
            tool_executor=lambda tc: ToolResult(tool_call_id=tc.id, content="x", is_error=False),
            model="gpt-5.4-mini",
            max_iterations=5,
        )

    assert result.stop_reason == "end_turn"
    assert mock_client.chat.completions.create.call_count == 2
