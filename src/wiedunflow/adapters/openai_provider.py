# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""OpenAIProvider — LLMProvider adapter backed by the official OpenAI Python SDK.

Single adapter covers OpenAI default (base_url=None) + OSS endpoints
(Ollama, LM Studio, vLLM) via base_url override.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

import httpx
import openai
import structlog
from openai import OpenAI
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from wiedunflow.adapters._history_compressor import compress_openai_history
from wiedunflow.adapters._plan_parser import parse_plan_response
from wiedunflow.adapters.llm_prompts import PLAN_SYSTEM_PROMPT
from wiedunflow.entities.lesson_manifest import LessonManifest
from wiedunflow.interfaces.ports import (
    AgentResult,
    AgentTurn,
    SpendMeterProto,
    ToolCall,
    ToolResult,
    ToolSpec,
)

logger = structlog.get_logger(__name__)


class OpenAIProvider:
    """LLMProvider via OpenAI SDK — supports OpenAI default and OSS endpoints via base_url.

    plan() uses model_plan (default: gpt-5.4). Multi-agent pipeline uses run_agent()
    with per-call model selection (orchestrator/researcher/writer/reviewer).
    Retries on RateLimitError/APITimeoutError with exponential backoff + jitter (tenacity).

    The consent check is intentionally NOT performed here — it belongs in the
    CLI layer, which has TTY awareness (US-051).

    Defaults updated in v0.7.0 per ADR-0015 (provider switch Anthropic → OpenAI).
    Earlier defaults were ``gpt-4o`` / ``gpt-4o-mini``; ``gpt-5.4`` family is the
    current OpenAI flagship for code-narration workloads (per Sprint 13 eval).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_plan: str = "gpt-5.4",
        model_orchestrator: str = "gpt-5.4",
        model_researcher: str = "gpt-5.4-mini",
        model_writer: str = "gpt-5.4",
        model_reviewer: str = "gpt-5.4-mini",
        max_retries: int = 5,
        max_wait_s: int = 60,
        max_tokens_plan: int = 8000,
        max_tokens_agent: int = 4000,
        http_read_timeout_s: int | None = None,
    ) -> None:
        resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_key:
            # For OSS endpoints (Ollama etc), api_key is ignored but OpenAI SDK
            # requires a non-empty string. Use a placeholder when base_url is set.
            if base_url:
                resolved_key = "not-needed"
            else:
                raise ValueError(
                    "OPENAI_API_KEY is required (pass api_key= or set env var) "
                    "when base_url is not provided"
                )
        # Read-timeout precedence: explicit param > env var > base_url-derived auto.
        # Local inference endpoints (Ollama / LM Studio / vLLM) running 13B+
        # models on CPU need minutes per Stage 5 planning call; 55s cuts off
        # the request before the server can stream anything back. Cloud
        # providers stay on 55s so a hung connection surfaces quickly.
        env_override = os.environ.get("WIEDUNFLOW_HTTP_READ_TIMEOUT")
        if http_read_timeout_s is not None:
            read_timeout = float(http_read_timeout_s)
        elif env_override is not None:
            try:
                read_timeout = float(env_override)
            except ValueError as exc:
                raise ValueError(
                    f"WIEDUNFLOW_HTTP_READ_TIMEOUT must be a number, got {env_override!r}"
                ) from exc
        elif base_url is not None:
            read_timeout = 600.0
        else:
            read_timeout = 55.0
        timeout = httpx.Timeout(60.0, read=read_timeout, write=10.0, connect=2.0)
        self._client = OpenAI(
            api_key=resolved_key,
            base_url=base_url,
            max_retries=0,  # CRITICAL: disable SDK retry; tenacity owns retry logic
            timeout=timeout,
        )
        self._base_url = base_url
        self._model_plan = model_plan
        self._model_orchestrator = model_orchestrator
        self._model_researcher = model_researcher
        self._model_writer = model_writer
        self._model_reviewer = model_reviewer
        self._max_retries = max_retries
        self._max_wait_s = max_wait_s
        self._max_tokens_plan = max_tokens_plan
        self._max_tokens_agent = max_tokens_agent
        logger.info(
            "openai_provider_init",
            base_url=base_url or "default(openai)",
            model_plan=model_plan,
            model_orchestrator=model_orchestrator,
            model_researcher=model_researcher,
            model_writer=model_writer,
            model_reviewer=model_reviewer,
            max_retries=max_retries,
            http_read_timeout_s=read_timeout,
        )

    def plan(self, outline: str) -> LessonManifest:
        """Call the planning model and return a structured LessonManifest.

        Uses json_object response_format to guarantee valid JSON output from the
        model — avoids markdown fences or prose wrappers around the JSON.

        Args:
            outline: Ranked call-graph outline produced by Stage 3 (graph).

        Returns:
            A validated LessonManifest with metadata attached.

        Raises:
            pydantic.ValidationError: If the LLM returns malformed JSON.
            openai.RateLimitError: After exhausting all retry attempts.
        """
        raw = self._create_with_retry(
            model=self._model_plan,
            max_tokens=self._max_tokens_plan,
            system=PLAN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": outline}],
            response_format={"type": "json_object"},
        )
        return parse_plan_response(raw)

    def run_agent(
        self,
        *,
        system: str,
        user: str,
        tools: list[ToolSpec],
        tool_executor: Callable[[ToolCall], ToolResult],
        model: str,
        max_iterations: int = 15,
        max_cost_usd: float = 1.0,
        spend_meter: SpendMeterProto | None = None,
        prompt_caching: bool = False,
        max_history_iterations: int = 10,
    ) -> AgentResult:
        """Run a tool-use agent loop against the OpenAI chat completions API.

        Calls the model repeatedly until it signals ``stop`` (no pending tool calls),
        ``max_iterations`` is reached, or the ``spend_meter`` signals budget exhaustion.
        Tools are executed synchronously via ``tool_executor`` between turns.

        OpenAI provides automatic prefix caching for repeated prompts ≥1024
        tokens long; there is no API hook to opt in. The ``prompt_caching``
        kwarg is honored only to satisfy the Protocol — when True it is logged
        as a no-op since the SDK does not expose a manual cache marker. Cache
        hits surface through ``response.usage.prompt_tokens_details.cached_tokens``
        and are forwarded to the spend meter so cost reporting reflects the
        0.5x cached rate documented by OpenAI.

        Args:
            system: System prompt for the agent.
            user: Initial user message.
            tools: Tool specifications to advertise to the model.
            tool_executor: Synchronous callback that executes a :class:`ToolCall`.
            model: OpenAI model identifier.
            max_iterations: Hard upper bound on loop iterations.
            max_cost_usd: Unused in this adapter (budget enforcement delegated to
                ``spend_meter``); kept for Protocol conformance.
            spend_meter: Optional spend tracker; loop aborts when
                ``would_exceed()`` returns True.
            prompt_caching: Protocol-level flag. Informational on OpenAI — the
                SDK does not expose a cache_control marker, so the kwarg is
                logged once and otherwise ignored.
            max_history_iterations: After this many iterations the middle band
                of the conversation is collapsed into summary lines. The
                system prompt and the most-recent iterations stay verbatim;
                tool_call_id ↔ tool result pairs are pruned together.

        Returns:
            :class:`AgentResult` with the final text, transcript, token totals, and
            a ``stop_reason`` of ``"end_turn"``, ``"max_iterations"``, or ``"max_cost"``.
        """
        if prompt_caching:
            logger.info(
                "openai_prompt_caching_noop",
                reason="openai_uses_automatic_prefix_caching",
                model=model,
            )
        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        token_param = (
            "max_completion_tokens" if _uses_max_completion_tokens(model) else "max_tokens"
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        transcript: list[AgentTurn] = []
        total_input = total_output = 0
        # Capture the meter snapshot at the start so AgentResult.total_cost_usd
        # carries the per-call delta. Cumulative spend stays on the meter.
        cost_at_start = spend_meter.total_cost_usd if spend_meter is not None else 0.0

        def _delta_cost() -> float:
            return (spend_meter.total_cost_usd - cost_at_start) if spend_meter is not None else 0.0

        for iteration in range(max_iterations):
            messages = compress_openai_history(
                messages,
                iteration=iteration,
                max_history_iterations=max_history_iterations,
            )
            kwargs: dict[str, Any] = {
                "model": model,
                token_param: self._max_tokens_agent,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = openai_tools
                kwargs["tool_choice"] = "auto"

            response = self._client.chat.completions.create(**kwargs)
            msg = response.choices[0].message
            usage = response.usage
            in_tok = usage.prompt_tokens if usage else 0
            out_tok = usage.completion_tokens if usage else 0
            # prompt_tokens_details is a sub-object — guard both the parent and
            # the cached_tokens leaf because older SDK responses (and most mocks)
            # omit it. Cached tokens are already included in prompt_tokens per
            # OpenAI accounting, so the spend meter subtracts them downstream.
            cached_tokens = 0
            if usage is not None:
                details = getattr(usage, "prompt_tokens_details", None)
                if details is not None:
                    cached_tokens = getattr(details, "cached_tokens", 0) or 0
            total_input += in_tok
            total_output += out_tok

            logger.info(
                "agent_iteration",
                provider="openai",
                model=model,
                iteration=iteration + 1,
                message_count=len(messages),
                input_tokens=in_tok,
                output_tokens=out_tok,
                cached_tokens=cached_tokens,
            )

            # Collect tool calls from this turn
            turn_calls: list[ToolCall] = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    turn_calls.append(
                        ToolCall(
                            id=tc.id,
                            name=tc.function.name,
                            arguments=json.loads(tc.function.arguments or "{}"),
                        )
                    )

            transcript.append(
                AgentTurn(
                    role="assistant",
                    text=msg.content,
                    tool_calls=turn_calls,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                )
            )

            if spend_meter is not None:
                spend_meter.charge(
                    model=model,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cache_read_input_tokens=cached_tokens,
                    provider="openai",
                )
                if spend_meter.would_exceed():
                    return AgentResult(
                        final_text=msg.content,
                        transcript=transcript,
                        total_input_tokens=total_input,
                        total_output_tokens=total_output,
                        total_cost_usd=_delta_cost(),
                        stop_reason="max_cost",
                        iterations=iteration + 1,
                    )

            # Stop if the model issued no tool calls or signalled stop finish_reason
            if not msg.tool_calls or response.choices[0].finish_reason == "stop":
                return AgentResult(
                    final_text=msg.content,
                    transcript=transcript,
                    total_input_tokens=total_input,
                    total_output_tokens=total_output,
                    total_cost_usd=_delta_cost(),
                    stop_reason="end_turn",
                    iterations=iteration + 1,
                )

            # Append assistant turn with tool_calls to the running message list
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            # Execute each tool and append results as tool-role messages
            for tc, call in zip(msg.tool_calls, turn_calls, strict=True):
                result = tool_executor(call)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result.content,
                    }
                )

        return AgentResult(
            final_text=None,
            transcript=transcript,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            total_cost_usd=_delta_cost(),
            stop_reason="max_iterations",
            iterations=max_iterations,
        )

    def _create_with_retry(
        self,
        *,
        model: str,
        max_tokens: int,
        system: str,
        messages: list[dict[str, str]],
        response_format: dict[str, str] | None = None,
    ) -> str:
        """Call chat.completions.create with tenacity retry on rate limits / timeouts.

        Uses exponential backoff with jitter, capped at max_wait_s seconds.
        Logs each backoff via structlog at WARNING level.
        Only retries openai.RateLimitError and openai.APITimeoutError — NOT
        authentication errors (openai.AuthenticationError) or other APIErrors.
        """

        token_param = (
            "max_completion_tokens" if _uses_max_completion_tokens(model) else "max_tokens"
        )

        @retry(
            retry=retry_if_exception_type(
                (openai.RateLimitError, openai.APITimeoutError, openai.InternalServerError)
            ),
            wait=wait_exponential_jitter(initial=2, max=self._max_wait_s, jitter=1),
            stop=stop_after_attempt(self._max_retries),
            before_sleep=_log_backoff,
            reraise=True,
        )
        def _call() -> str:
            kwargs: dict[str, Any] = {
                "model": model,
                token_param: max_tokens,
                "messages": [{"role": "system", "content": system}, *messages],
            }
            if response_format is not None:
                kwargs["response_format"] = response_format
            response = self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""

        return _call()


def _uses_max_completion_tokens(model: str) -> bool:
    """Return True for OpenAI models that reject ``max_tokens``.

    Reasoning models (o1/o3/o4) and the GPT-5 family require
    ``max_completion_tokens``; older chat models (gpt-4o, gpt-3.5, gpt-4-turbo)
    still accept ``max_tokens``. Detection is name-prefix based since OpenAI does
    not expose this capability via the SDK.
    """
    name = model.strip().lower()
    return (
        name.startswith("o1")
        or name.startswith("o3")
        or name.startswith("o4")
        or name.startswith("gpt-5")
    )


def _log_backoff(retry_state: RetryCallState) -> None:
    """Structlog warning emitted before each retry sleep."""
    logger.warning(
        "openai_backoff",
        attempt=retry_state.attempt_number,
        wait_s=round(retry_state.upcoming_sleep, 2),
    )
