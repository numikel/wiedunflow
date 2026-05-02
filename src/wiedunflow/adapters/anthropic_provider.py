# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""AnthropicProvider — LLMProvider adapter backed by the official Anthropic Python SDK."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
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

from wiedunflow import __version__
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.lesson import Lesson
from wiedunflow.entities.lesson_manifest import (
    LessonManifest,
    LessonSpec,
    ManifestMetadata,
)
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

    plan() uses Sonnet 4.6; narrate() uses Opus 4.7 by default.
    Retries on RateLimitError with exponential backoff + jitter (tenacity).

    The consent check is intentionally NOT performed here — it belongs in the
    CLI layer, which has TTY awareness (US-051).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_plan: str = "claude-sonnet-4-6",
        model_narrate: str = "claude-opus-4-7",
        model_describe: str = "claude-haiku-4-5",
        model_orchestrator: str = "claude-sonnet-4-6",
        model_researcher: str = "claude-haiku-4-5",
        model_writer: str = "claude-sonnet-4-6",
        model_reviewer: str = "claude-haiku-4-5",
        max_retries: int = 5,
        max_wait_s: int = 60,
        max_tokens_plan: int = 8000,
        max_tokens_narrate: int = 4000,
        max_tokens_describe: int = 300,
        max_tokens_agent: int = 4000,
    ) -> None:
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError("ANTHROPIC_API_KEY is required (pass api_key= or set env var)")
        self._client = anthropic.Anthropic(api_key=resolved_key)
        self._model_plan = model_plan
        self._model_narrate = model_narrate
        self._model_describe = model_describe
        self._model_orchestrator = model_orchestrator
        self._model_researcher = model_researcher
        self._model_writer = model_writer
        self._model_reviewer = model_reviewer
        self._max_retries = max_retries
        self._max_wait_s = max_wait_s
        self._max_tokens_plan = max_tokens_plan
        self._max_tokens_narrate = max_tokens_narrate
        self._max_tokens_describe = max_tokens_describe
        self._max_tokens_agent = max_tokens_agent
        logger.info(
            "anthropic_provider_init",
            model_plan=model_plan,
            model_narrate=model_narrate,
            model_describe=model_describe,
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
        raw = self._create_with_retry(
            model=self._model_plan,
            max_tokens=self._max_tokens_plan,
            system=_PLAN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": outline}],
        )
        return _parse_plan_response(raw)

    def describe_symbol(self, symbol: CodeSymbol, context: str) -> str:
        """Produce a short natural-language description of a leaf symbol via Haiku.

        Args:
            symbol: Target ``CodeSymbol`` (function, class, method, …).
            context: Surrounding source / docstring / AST metadata used for grounding.

        Returns:
            Markdown description (~2-4 sentences). No JSON envelope, no fences.

        Raises:
            anthropic.RateLimitError: After exhausting all retry attempts.
        """
        user_content = _build_describe_user_prompt(symbol=symbol, context=context)
        raw = self._create_with_retry(
            model=self._model_describe,
            max_tokens=self._max_tokens_describe,
            system=_DESCRIBE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        return raw.strip()

    def narrate(
        self,
        spec_json: str,
        concepts_introduced: tuple[str, ...],
    ) -> Lesson:
        """Call the narration model and return a generated Lesson.

        Args:
            spec_json: JSON-serialised LessonSpec from Stage 5 (planning).
            concepts_introduced: Concepts already taught — must not be re-taught.

        Returns:
            A Lesson with markdown narrative from the model.

        Raises:
            anthropic.RateLimitError: After exhausting all retry attempts.
        """
        concepts_block = ", ".join(concepts_introduced) if concepts_introduced else "<none yet>"
        system_prompt = _NARRATE_SYSTEM_PROMPT.format(concepts_introduced=concepts_block)
        raw = self._create_with_retry(
            model=self._model_narrate,
            max_tokens=self._max_tokens_narrate,
            system=system_prompt,
            messages=[{"role": "user", "content": spec_json}],
        )
        spec: Any = json.loads(spec_json)
        # code_refs in spec may be CodeRef dicts or plain strings — extract symbol name.
        raw_refs: list[Any] = spec.get("code_refs", [])
        code_ref_symbols: tuple[str, ...] = tuple(
            str(r["symbol"]) if isinstance(r, dict) else str(r) for r in raw_refs
        )
        return Lesson(
            id=str(spec.get("id", "lesson-unknown")),
            title=str(spec.get("title", "Untitled")),
            narrative=raw,
            code_refs=code_ref_symbols,
            status="generated",
        )

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
    ) -> AgentResult:
        """Run a tool-use agent loop against the Anthropic messages API.

        Calls the model repeatedly until it signals ``end_turn`` (no pending tool calls),
        ``max_iterations`` is reached, or the ``spend_meter`` signals budget exhaustion.
        Tools are executed synchronously via ``tool_executor`` between turns.

        The Anthropic message format differs from OpenAI: tool results are sent as
        a ``user`` message with ``tool_result`` content blocks, and assistant turns
        with tool calls are appended as the raw SDK response content list.

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

        Returns:
            :class:`AgentResult` with the final text, transcript, token totals, and
            a ``stop_reason`` of ``"end_turn"``, ``"max_iterations"``, or ``"max_cost"``.
        """
        anthropic_tools = [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]

        messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
        transcript: list[AgentTurn] = []
        total_input = total_output = 0
        total_cost = 0.0

        for iteration in range(max_iterations):
            create_kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": self._max_tokens_agent,
                "system": system,
                "messages": messages,
            }
            if tools:
                create_kwargs["tools"] = anthropic_tools

            response = self._client.messages.create(**create_kwargs)
            in_tok = response.usage.input_tokens
            out_tok = response.usage.output_tokens
            total_input += in_tok
            total_output += out_tok

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
                spend_meter.charge(model=model, input_tokens=in_tok, output_tokens=out_tok)
                if spend_meter.would_exceed():
                    return AgentResult(
                        final_text=final_text,
                        transcript=transcript,
                        total_input_tokens=total_input,
                        total_output_tokens=total_output,
                        total_cost_usd=total_cost,
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
                    total_cost_usd=total_cost,
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
            total_cost_usd=total_cost,
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
    ) -> str:
        """Call messages.create with tenacity retry on 429 RateLimitError.

        Uses exponential backoff with jitter, capped at max_wait_s seconds.
        Logs each backoff via structlog at WARNING level.
        """

        @retry(
            retry=retry_if_exception_type(anthropic.RateLimitError),
            wait=wait_exponential_jitter(initial=2, max=self._max_wait_s, jitter=1),
            stop=stop_after_attempt(self._max_retries),
            before_sleep=_log_backoff,
            reraise=True,
        )
        def _call() -> str:
            response = self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,  # type: ignore[arg-type]
            )
            parts: list[str] = []
            for block in response.content:
                if isinstance(block, TextBlock):
                    parts.append(block.text)
            return "".join(parts)

        return _call()


def _parse_plan_response(raw: str) -> LessonManifest:
    """Parse the LLM JSON response into a fully-constructed ``LessonManifest``.

    The LLM returns ``{"schema_version": "1.0.0", "lessons": [...]}`` — a subset
    of the full ``LessonManifest`` schema (``ManifestMetadata`` is server-side
    provenance that the LLM does not produce).  This function:

    1. Validates the ``lessons`` list via ``LessonSpec.model_validate``.
    2. Constructs ``ManifestMetadata`` using the current timestamp and version.
    3. Returns a fully-valid ``LessonManifest``.

    Raises:
        pydantic.ValidationError: On schema mismatch in the LLM output.
        json.JSONDecodeError: On invalid JSON.
    """
    data: Any = json.loads(raw)
    raw_lessons: list[Any] = data.get("lessons", [])
    lessons: tuple[LessonSpec, ...] = tuple(LessonSpec.model_validate(spec) for spec in raw_lessons)
    metadata = ManifestMetadata(
        schema_version="1.0.0",
        wiedunflow_version=__version__,
        total_lessons=len(lessons),
        generated_at=datetime.now(UTC),
        has_readme=True,
        doc_coverage=None,
    )
    return LessonManifest(
        schema_version="1.0.0",
        lessons=lessons,
        metadata=metadata,
    )


def _log_backoff(retry_state: RetryCallState) -> None:
    """Structlog warning emitted before each retry sleep."""
    logger.warning(
        "anthropic_backoff",
        attempt=retry_state.attempt_number,
        wait_s=round(retry_state.upcoming_sleep, 2),
    )


_PLAN_SYSTEM_PROMPT = """You are WiedunFlow, a tutorial planner. Given a ranked call-graph outline, produce a JSON lesson manifest.

STRICT RULES:
- Output ONLY JSON matching the schema (no prose, no markdown fences).
- Every code_refs[*].symbol MUST appear in the allowed symbols list (provided in the user message).
- Every code_refs[*].role MUST be EXACTLY one of: "primary", "referenced", "example".
  Do NOT invent other values like "secondary", "supporting", "auxiliary", "tertiary", "supplementary".
  If a symbol is supportive but not the focus, use "referenced". If it illustrates usage, use "example".
- Order lessons: lesson 1 = entry point (main/CLI orchestrator); lessons 2..N-2 =
  leaves->roots building blocks; lesson N-1 = top-level orchestration; lesson N = closing.
- If no clear entry point exists, fall back to leaves->roots throughout.
- Max 30 lessons.
- Each lesson teaches ONE concept not covered by earlier lessons.

JSON SCHEMA:
{
  "schema_version": "1.0.0",
  "lessons": [
    {
      "id": "lesson-001",
      "title": "...",
      "teaches": "...",
      "prerequisites": [],
      "code_refs": [
        {"file_path": "src/module.py", "symbol": "module.func", "line_start": 1, "line_end": 5, "role": "primary"}
      ],
      "external_context_needed": false
    }
  ]
}"""


_NARRATE_SYSTEM_PROMPT = """You are WiedunFlow, a narrator writing a single tutorial lesson in Markdown.

CONSTRAINTS:
- Audience: mid-level Python developer.
- Do NOT re-teach these already-covered concepts: {concepts_introduced}.
- Ground every claim in the provided code references; do not invent function names.

PROJECT CONTEXT:
- The user message MAY include a `project_context` field with an excerpt of the
  repository README. Use it to anchor narrations in the project's actual purpose
  and vocabulary — say what the project does, not generic Python platitudes.
- Concrete code claims MUST still be grounded in source_excerpt, never in
  project_context narrative. Treat project_context as orientation, not as truth
  about how the function is implemented.

GROUNDING (signature accuracy):
- For every code_refs entry where source_excerpt is not null, narration MUST quote
  the function signature EXACTLY as it appears in source_excerpt.
- Do NOT invent parameter names or return types not present in source_excerpt.
- ```python fenced blocks MUST contain code copied verbatim from source_excerpt
  (you may abbreviate the body with `# ...` comments, but signatures stay exact).

STRUCTURE — use real Markdown, not a wall of paragraphs. The reader sees the
output rendered with proper headings, callouts, and code blocks; flat prose
makes the lesson feel like a notepad. Apply these elements *when they fit the
content* (do not force them):

- `## Subheading` to split logical sections (e.g., one subhead per function or
  per phase of the algorithm). Use `###` for nested points only if needed.
- `> **Note:** …` / `> **Tip:** …` / `> **Warning:** …` blockquotes for
  callouts: edge cases, gotchas, performance notes, version-specific quirks.
- ```python fenced code blocks ``` for concrete examples (3-8 lines max,
  illustrative only — they must NOT introduce new symbols beyond those in
  the provided code references).
- `**bold**` for the first mention of a key term; `*italic* ` for emphasis.
- `- bullet` lists when enumerating ≥3 items; otherwise prefer prose.
- A single `---` horizontal rule to separate "what" from "how" if it helps
  the flow.

LENGTH — narration MUST be proportional to code complexity. A 3-line function
does not need 500 words. Aim for the shortest lesson that teaches what the code
does and why, then stop:
- Trivial (< 10 lines, no control flow, 1 concept):         160-220 words.
- Moderate (10-30 lines, 1-2 control structures):           220-350 words.
- Complex (> 30 lines OR multiple intertwined constructs):  350-500 words.
- Hard ceiling: 500 words. Hard floor: 150 words (validator).

Avoid padding: no tangential digressions, no "did you know" factoids, no
enumeration of every possible Python idiom, no duck-typing essays unless the
code actually relies on duck typing. Prefer one precise example over three
speculative ones.

- Return ONLY the markdown narrative (no JSON wrapper)."""


_DESCRIBE_SYSTEM_PROMPT = """You are WiedunFlow, producing concise leaf-symbol descriptions for a tutorial.

CONSTRAINTS:
- Output plain markdown, 2-4 sentences, ~80 words max.
- Describe what the symbol does, its role in the module, and relevant types.
- Ground every claim in the provided context; do not invent behaviour.
- Do NOT include code fences, JSON wrappers, or headings — prose only."""


def _build_describe_user_prompt(*, symbol: CodeSymbol, context: str) -> str:
    """Render a user prompt for ``describe_symbol`` combining symbol metadata and context."""
    docstring = symbol.docstring or "<none>"
    flags: list[str] = []
    if symbol.is_dynamic_import:
        flags.append("dynamic-import")
    if symbol.is_uncertain:
        flags.append("uncertain-resolution")
    flags_line = ", ".join(flags) if flags else "<none>"
    return (
        f"Symbol: {symbol.name}\n"
        f"Kind: {symbol.kind}\n"
        f"File: {symbol.file_path} (line {symbol.lineno})\n"
        f"Docstring: {docstring}\n"
        f"Flags: {flags_line}\n"
        f"\n"
        f"Context:\n"
        f"{context}\n"
    )
