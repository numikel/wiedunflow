# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""OpenAIProvider — LLMProvider adapter backed by the official OpenAI Python SDK.

Single adapter covers OpenAI default (base_url=None) + OSS endpoints
(Ollama, LM Studio, vLLM) via base_url override.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
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

from wiedunflow import __version__
from wiedunflow.entities.code_symbol import CodeSymbol
from wiedunflow.entities.lesson import Lesson
from wiedunflow.entities.lesson_manifest import (
    LessonManifest,
    LessonSpec,
    ManifestMetadata,
)

logger = structlog.get_logger(__name__)


class OpenAIProvider:
    """LLMProvider via OpenAI SDK — supports OpenAI default and OSS endpoints via base_url.

    plan() uses model_plan (default: gpt-4o).
    narrate() uses model_narrate (default: gpt-4o).
    describe_symbol() uses model_describe (default: gpt-4o-mini).
    Retries on RateLimitError/APITimeoutError with exponential backoff + jitter (tenacity).

    The consent check is intentionally NOT performed here — it belongs in the
    CLI layer, which has TTY awareness (US-051).
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_plan: str = "gpt-4o",
        model_narrate: str = "gpt-4o",
        model_describe: str = "gpt-4o-mini",
        max_retries: int = 5,
        max_wait_s: int = 60,
        max_tokens_plan: int = 8000,
        max_tokens_narrate: int = 4000,
        max_tokens_describe: int = 300,
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
        timeout = httpx.Timeout(60.0, read=55.0, write=10.0, connect=2.0)
        self._client = OpenAI(
            api_key=resolved_key,
            base_url=base_url,
            max_retries=0,  # CRITICAL: disable SDK retry; tenacity owns retry logic
            timeout=timeout,
        )
        self._base_url = base_url
        self._model_plan = model_plan
        self._model_narrate = model_narrate
        self._model_describe = model_describe
        self._max_retries = max_retries
        self._max_wait_s = max_wait_s
        self._max_tokens_plan = max_tokens_plan
        self._max_tokens_narrate = max_tokens_narrate
        self._max_tokens_describe = max_tokens_describe
        logger.info(
            "openai_provider_init",
            base_url=base_url or "default(openai)",
            model_plan=model_plan,
            model_narrate=model_narrate,
            model_describe=model_describe,
            max_retries=max_retries,
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
            system=_PLAN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": outline}],
            response_format={"type": "json_object"},
        )
        return _parse_plan_response(raw)

    def describe_symbol(self, symbol: CodeSymbol, context: str) -> str:
        """Produce a short natural-language description of a leaf symbol.

        Args:
            symbol: Target ``CodeSymbol`` (function, class, method, …).
            context: Surrounding source / docstring / AST metadata used for grounding.

        Returns:
            Markdown description (~2-4 sentences). No JSON envelope, no fences.

        Raises:
            openai.RateLimitError: After exhausting all retry attempts.
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
            openai.RateLimitError: After exhausting all retry attempts.
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
            retry=retry_if_exception_type((openai.RateLimitError, openai.APITimeoutError)),
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
        codeguide_version=__version__,
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


_PLAN_SYSTEM_PROMPT = """You are CodeGuide, a tutorial planner. Given a ranked call-graph outline, produce a JSON lesson manifest.

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


_NARRATE_SYSTEM_PROMPT = """You are CodeGuide, a narrator writing a single tutorial lesson in Markdown.

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
- `**bold**` for the first mention of a key term; `*italic*` for emphasis.
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


_DESCRIBE_SYSTEM_PROMPT = """You are CodeGuide, producing concise leaf-symbol descriptions for a tutorial.

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
