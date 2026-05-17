# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""AnthropicProvider — LLMProvider adapter backed by the official Anthropic Python SDK."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import anthropic
import structlog
from anthropic.types import TextBlock, ToolUseBlock
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from wiedunflow.adapters._history_compressor import compress_anthropic_history
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


class AnthropicProvider:
    """Implementation of LLMProvider via official Anthropic Python SDK.

    plan() uses Sonnet 4.6. Multi-agent pipeline uses run_agent() with
    per-call model selection (orchestrator/researcher/writer/reviewer).
    Retries on RateLimitError with exponential backoff + jitter (tenacity).

    The consent check is intentionally NOT performed here — it belongs in the
    CLI layer, which has TTY awareness (US-051).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_plan: str = "claude-sonnet-4-6",
        model_orchestrator: str = "claude-sonnet-4-6",
        model_researcher: str = "claude-haiku-4-5",
        model_writer: str = "claude-sonnet-4-6",
        model_reviewer: str = "claude-haiku-4-5",
        max_retries: int = 5,
        max_wait_s: int = 60,
        max_tokens_plan: int = 8000,
        max_tokens_agent: int = 4000,
    ) -> None:
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError("ANTHROPIC_API_KEY is required (pass api_key= or set env var)")
        self._client = anthropic.Anthropic(api_key=resolved_key)
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
            "anthropic_provider_init",
            model_plan=model_plan,
            model_orchestrator=model_orchestrator,
            model_researcher=model_researcher,
            model_writer=model_writer,
            model_reviewer=model_reviewer,
            max_retries=max_retries,
        )

    def plan(self, outline: str) -> LessonManifest:
        """Call the planning model and return a structured LessonManifest.

        The LLM is expected to return a JSON object with a ``lessons`` array.
        Provider builds the required ``ManifestMetadata`` (version, timestamp,
        counts) from the parsed lessons rather than asking the LLM to produce it.

        Args:
            outline: Ranked call-graph outline produced by Stage 3 (graph).

        Returns:
            A validated LessonManifest with metadata attached.

        Raises:
            pydantic.ValidationError: If the LLM returns malformed JSON.
            anthropic.RateLimitError: After exhausting all retry attempts.
        """
        response = self._create_with_retry(
            model=self._model_plan,
            max_tokens=self._max_tokens_plan,
            system=PLAN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": outline}],
        )
        parts: list[str] = []
        for block in response.content:
            if isinstance(block, TextBlock):
                parts.append(block.text)
        return parse_plan_response("".join(parts))

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
        """Run a tool-use agent loop against the Anthropic messages API.

        Calls the model repeatedly until it signals ``end_turn`` (no pending tool calls),
        ``max_iterations`` is reached, or the ``spend_meter`` signals budget exhaustion.
        Tools are executed synchronously via ``tool_executor`` between turns.

        The Anthropic message format differs from OpenAI: tool results are sent as
        a ``user`` message with ``tool_result`` content blocks, and assistant turns
        with tool calls are appended as the raw SDK response content list.

        When ``prompt_caching`` is True the system prompt is wrapped in a
        ``TextBlockParam`` carrying ``cache_control={"type": "ephemeral"}`` and
        the last tool schema receives the same marker. Anthropic charges the
        first call at 1.25x input rate to populate the cache; subsequent calls
        within the 5-minute TTL pay only 10% of the regular input rate for
        cache hits.

        Args:
            system: System prompt for the agent.
            user: Initial user message.
            tools: Tool specifications to advertise to the model.
            tool_executor: Synchronous callback that executes a :class:`ToolCall`.
            model: Anthropic model identifier.
            max_iterations: Hard upper bound on loop iterations.
            max_cost_usd: Unused in this adapter (budget enforcement delegated to
                ``spend_meter``); kept for Protocol conformance.
            spend_meter: Optional spend tracker; loop aborts when
                ``would_exceed()`` returns True.
            prompt_caching: Wire ``cache_control: ephemeral`` markers on system
                + last tool schema. Requires the system prompt to exceed
                Anthropic's per-model minimum (~1024 tokens) to take effect.
            max_history_iterations: After this many iterations the middle band
                of the conversation collapses into one-line summaries to keep
                input cost growth linear instead of quadratic.

        Returns:
            :class:`AgentResult` with the final text, transcript, token totals, and
            a ``stop_reason`` of ``"end_turn"``, ``"max_iterations"``, or ``"max_cost"``.
        """
        anthropic_tools: list[dict[str, Any]] = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]
        # Cache the tail of the tools array. Anthropic caches every block up to
        # and including the one with the marker, so a single cache_control on
        # the last tool covers the entire tools section for subsequent calls.
        if prompt_caching and anthropic_tools:
            anthropic_tools[-1]["cache_control"] = {"type": "ephemeral"}

        # Anthropic accepts ``system`` as either a string or a list of
        # ``TextBlockParam`` dicts. The list form is required to attach
        # cache_control; the string form stays the default to preserve the
        # wire format for callers that have not opted in.
        system_param: str | list[dict[str, Any]]
        if prompt_caching:
            system_param = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        else:
            system_param = system

        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        transcript: list[AgentTurn] = []
        total_input = total_output = 0
        total_cache_creation = total_cache_read = 0
        # Capture the meter snapshot at the start so AgentResult.total_cost_usd
        # carries the per-call delta. Cumulative spend stays on the meter.
        cost_at_start = spend_meter.total_cost_usd if spend_meter is not None else 0.0

        def _delta_cost() -> float:
            return (spend_meter.total_cost_usd - cost_at_start) if spend_meter is not None else 0.0

        for iteration in range(max_iterations):
            messages = compress_anthropic_history(
                messages,
                iteration=iteration,
                max_history_iterations=max_history_iterations,
            )
            extra: dict[str, Any] = {}
            if anthropic_tools:
                extra["tools"] = anthropic_tools

            response = self._create_with_retry(
                model=model,
                max_tokens=self._max_tokens_agent,
                system=system_param,
                messages=messages,
                extra_kwargs=extra,
            )
            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            # The SDK may return ``None`` (no cache activity) or omit the
            # field entirely on older mock responses; collapse both to 0.
            cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            total_input += in_tok
            total_output += out_tok
            total_cache_creation += cache_creation
            total_cache_read += cache_read

            logger.info(
                "agent_iteration",
                provider="anthropic",
                model=model,
                iteration=iteration + 1,
                message_count=len(messages),
                input_tokens=in_tok,
                output_tokens=out_tok,
                cache_creation_input_tokens=cache_creation,
                cache_read_input_tokens=cache_read,
            )

            # Extract text and tool_use blocks from the response
            final_text: str | None = None
            turn_calls: list[ToolCall] = []
            for block in response.content:
                if isinstance(block, TextBlock):
                    final_text = block.text
                elif isinstance(block, ToolUseBlock):
                    turn_calls.append(
                        ToolCall(
                            id=block.id,
                            name=block.name,
                            arguments=dict(block.input),
                        )
                    )

            transcript.append(
                AgentTurn(
                    role="assistant",
                    text=final_text,
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
                    cache_creation_input_tokens=cache_creation,
                    cache_read_input_tokens=cache_read,
                    provider="anthropic",
                )
                if spend_meter.would_exceed():
                    return AgentResult(
                        final_text=final_text,
                        transcript=transcript,
                        total_input_tokens=total_input,
                        total_output_tokens=total_output,
                        total_cost_usd=_delta_cost(),
                        stop_reason="max_cost",
                        iterations=iteration + 1,
                    )

            # Stop if the model signalled end_turn or issued no tool calls
            if response.stop_reason == "end_turn" or not turn_calls:
                return AgentResult(
                    final_text=final_text,
                    transcript=transcript,
                    total_input_tokens=total_input,
                    total_output_tokens=total_output,
                    total_cost_usd=_delta_cost(),
                    stop_reason="end_turn",
                    iterations=iteration + 1,
                )

            # Append assistant turn (raw SDK content list for correct multi-block format)
            messages.append({"role": "assistant", "content": response.content})

            # Execute each tool and build the user-role tool_result message
            tool_result_blocks: list[dict[str, Any]] = []
            for call in turn_calls:
                result = tool_executor(call)
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": result.content,
                    }
                )
            messages.append({"role": "user", "content": tool_result_blocks})

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
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        extra_kwargs: dict[str, Any] | None = None,
    ) -> Any:
        """Call messages.create with tenacity retry on transient API errors.

        Retries on rate-limit (429), internal server errors (500), and
        connection-level failures so that a single dropped TCP connection does
        not abort an entire lesson.

        Uses exponential backoff with jitter, capped at max_wait_s seconds.
        Logs each backoff via structlog at WARNING level.

        Note: prompt caching is wired only inside ``run_agent``. The single
        remaining caller of this helper via ``plan()`` passes a plain string
        system prompt whose token count is below Anthropic's ~1024-token cache
        threshold, so the cache_control path is a no-op there.
        """
        _extra = extra_kwargs or {}

        @retry(
            retry=retry_if_exception_type(
                (
                    anthropic.RateLimitError,
                    anthropic.InternalServerError,
                    anthropic.APIConnectionError,
                )
            ),
            wait=wait_exponential_jitter(initial=2, max=self._max_wait_s, jitter=1),
            stop=stop_after_attempt(self._max_retries),
            before_sleep=_log_backoff,
            reraise=True,
        )
        def _call() -> Any:
            return self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,  # type: ignore[arg-type]
                messages=messages,  # type: ignore[arg-type]
                **_extra,
            )

        return _call()


def _log_backoff(retry_state: RetryCallState) -> None:
    """Structlog warning emitted before each retry sleep."""
    logger.warning(
        "anthropic_backoff",
        attempt=retry_state.attempt_number,
        wait_s=round(retry_state.upcoming_sleep, 2),
    )
