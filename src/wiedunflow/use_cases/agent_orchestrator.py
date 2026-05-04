# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Michał Kamiński
"""Per-lesson multi-agent orchestration pipeline.

Orchestrator (LLM) -> Researcher x N (8 tools) -> Writer -> Reviewer
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from wiedunflow.entities.lesson import Lesson
from wiedunflow.entities.lesson_manifest import LessonSpec
from wiedunflow.entities.skipped_lesson import SkippedLesson
from wiedunflow.entities.word_count import fatal_floor_for_span, floor_for_span
from wiedunflow.interfaces.ports import (
    AgentResult,
    LLMProvider,
    SpendMeterProto,
    ToolCall,
    ToolResult,
    ToolSpec,
)
from wiedunflow.use_cases.agents.loader import compile_card
from wiedunflow.use_cases.workspace import RunWorkspace

logger = logging.getLogger(__name__)

ToolFn = Callable[[dict[str, Any]], str]

# Reviewer-accessible subset of the researcher tool palette.
_REVIEWER_TOOLS = {"read_symbol_body", "search_docs", "read_tests", "grep_usages"}

_DEFAULT_TARGET_AUDIENCE = "mid-level Python developer"

# Default model IDs by role (OpenAI provider; override via models= arg).
_DEFAULT_MODELS: dict[str, str] = {
    "orchestrator": "gpt-5.4",
    "researcher": "gpt-5.4-mini",
    "writer": "gpt-5.4",
    "reviewer": "gpt-5.4-mini",
}


@dataclasses.dataclass
class _OrchestratorState:
    """Shared mutable state across dispatch tool closures within one lesson."""

    lesson_id: str
    result: Lesson | SkippedLesson | None = None
    research_counter: int = 0
    writer_counter: int = 0
    writer_retries: int = 0
    """Number of additional Writer dispatches beyond the first (= retries).

    A Writer rerun signals the Reviewer rejected the previous draft. The
    pipeline surfaces this through ``RunLessonOutcome`` so ``RunReport`` can
    report meaningful retry totals to the user.
    """
    research_paths: list[str] = dataclasses.field(default_factory=list)
    last_draft_path: str | None = None


@dataclasses.dataclass(frozen=True)
class RunLessonOutcome:
    """Return value of :func:`run_lesson` and :func:`run_closing_lesson`.

    Wraps the lesson result with pipeline metrics that are not part of the
    domain entity ``Lesson`` (which only describes what the reader will learn).
    """

    result: Lesson | SkippedLesson
    writer_retries: int = 0


def _make_tool_executor(tool_registry: dict[str, ToolFn]) -> Callable[[ToolCall], ToolResult]:
    """Wrap a tool_registry dict into a ToolCall executor for run_agent."""

    def _execute(call: ToolCall) -> ToolResult:
        fn = tool_registry.get(call.name)
        if fn is None:
            return ToolResult(
                tool_call_id=call.id,
                content=f"[error] Unknown tool: {call.name}",
                is_error=True,
            )
        try:
            content = fn(call.arguments)
        except Exception as exc:
            logger.warning("tool_error tool=%s exc=%r", call.name, exc)
            content = f"[error] Tool '{call.name}' raised: {exc}"
        return ToolResult(tool_call_id=call.id, content=str(content))

    return _execute


def _tool_spec_from_schema(schema: dict[str, Any]) -> ToolSpec:
    """Convert a loaded tool JSON schema dict to a ToolSpec."""
    return ToolSpec(
        name=schema["name"],
        description=schema["description"],
        input_schema=schema["parameters"],
    )


def _run_researcher(
    *,
    symbol: str,
    research_brief: str,
    budget_usd: float,
    lesson_id: str,
    concepts_introduced: tuple[str, ...],
    llm: LLMProvider,
    tool_registry: dict[str, ToolFn],
    workspace: RunWorkspace,
    state: _OrchestratorState,
    model: str,
    spend_meter: SpendMeterProto | None,
    agents_dir: Path | None,
) -> str:
    """Run a Researcher sub-agent and save notes to workspace.

    Returns a short summary string for the Orchestrator's context.
    """
    state.research_counter += 1
    ref_num = f"{state.research_counter:03d}"
    out_path = workspace.lesson_dir(lesson_id, "processing") / f"research-{ref_num}.md"

    card = compile_card(
        "researcher",
        kwargs={
            "lesson_id": lesson_id,
            "primary_symbol": symbol,
            "research_brief": research_brief,
            "concepts_introduced": str(list(concepts_introduced)),
            "budget_remaining_usd": f"{budget_usd:.2f}",
        },
        agents_dir=agents_dir,
    )
    tool_specs = [_tool_spec_from_schema(s) for s in card.tools]
    executor = _make_tool_executor(tool_registry)

    result: AgentResult = llm.run_agent(
        system=card.system_prompt,
        user=(
            f"Investigate symbol `{symbol}` for lesson `{lesson_id}`.\n"
            f"Brief: {research_brief}\n"
            f"Write research notes following the required output format."
        ),
        tools=tool_specs,
        tool_executor=executor,
        model=model,
        max_iterations=card.budgets.max_iterations,
        max_cost_usd=budget_usd,
        spend_meter=spend_meter,
    )

    notes = result.final_text or ""
    if not notes.strip():
        notes = f"[Researcher produced no output for {symbol} — stop_reason={result.stop_reason}]"

    workspace.write_atomic(out_path, notes)
    rel = str(out_path.relative_to(workspace.base_dir))
    state.research_paths.append(rel)
    logger.info(
        "researcher_done lesson=%s symbol=%s ref=%s stop=%s",
        lesson_id,
        symbol,
        ref_num,
        result.stop_reason,
    )
    return f"Research notes saved to {rel} (stop_reason={result.stop_reason})."


_SYMBOL_BLOCKLIST: frozenset[str] = frozenset(
    {
        # Python literals
        "None",
        "True",
        "False",
        # Built-in types
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "tuple",
        "set",
        "bytes",
        "bytearray",
        "memoryview",
        "type",
        "object",
        # Common exceptions
        "Exception",
        "ValueError",
        "TypeError",
        "KeyError",
        "AttributeError",
        "RuntimeError",
        "StopIteration",
        # Common stdlib top-level names
        "Path",
        "os",
        "re",
        "json",
        "logging",
        "sys",
        # typing
        "Any",
        "Optional",
        "Union",
        "Callable",
        "Iterator",
        "Generator",
        "Sequence",
        "Mapping",
        "typing",
    }
)


def _extract_research_symbols(text: str) -> set[str]:
    """Return the set of backtick-wrapped identifiers found in *text*.

    Used as a heuristic to build the grounding reference set from research notes.
    Matches ``foo``, ``module.sub.foo``, etc.  Common builtins and stdlib names
    are filtered via :data:`_SYMBOL_BLOCKLIST` to avoid inflating the grounding
    reference set with non-project symbols.
    """
    raw = {m.group(1) for m in re.finditer(r"`([\w.]+(?:\.\w+)*)`", text)}
    return raw - _SYMBOL_BLOCKLIST


def _assemble_draft_markdown(draft_holder: dict[str, Any]) -> tuple[str, list[str]]:
    """Assemble structured markdown body and callouts from *draft_holder*.

    Returns ``(body_markdown, callout_lines)`` so the caller can decide
    how to combine them (body + callouts appended as a final section).
    """
    overview = str(draft_holder.get("overview", "") or "")
    how_it_works = str(draft_holder.get("how_it_works", "") or "")
    key_details = str(draft_holder.get("key_details", "") or "")
    what_to_watch = str(draft_holder.get("what_to_watch_for", "") or "")
    uncertain_regions: list[Any] = list(draft_holder.get("uncertain_regions", []) or [])

    sections: list[str] = []
    if overview.strip():
        sections.append(f"## Overview\n\n{overview}")
    if how_it_works.strip():
        sections.append(f"## How It Works\n\n{how_it_works}")
    if key_details.strip():
        sections.append(f"## Key Details\n\n{key_details}")
    if what_to_watch.strip():
        sections.append(f"## What To Watch For\n\n{what_to_watch}")

    callouts: list[str] = []
    for region in uncertain_regions:
        if isinstance(region, dict):
            sym = str(region.get("symbol", ""))
            callout_text = str(region.get("callout", ""))
            if sym and callout_text:
                callouts.append(f"> [!note] {sym}\n> {callout_text}")
    if callouts:
        sections.append("\n\n".join(callouts))

    return "\n\n".join(sections), callouts


def _run_writer(
    *,
    research_refs: list[str],
    lesson_spec_json: str,
    lesson_id: str,
    lesson_title: str,
    lesson_teaches: str,
    primary_symbol: str,
    concepts_introduced: tuple[str, ...],
    llm: LLMProvider,
    workspace: RunWorkspace,
    state: _OrchestratorState,
    model: str,
    budget_usd: float,
    spend_meter: SpendMeterProto | None,
    agents_dir: Path | None,
    target_audience: str,
    reviewer_feedback: str = "",
) -> str:
    """Run a Writer sub-agent and save the draft to workspace.

    Fix D: Writer now submits structured output via ``submit_lesson_draft`` tool
    instead of raw markdown prose. The tool call enforces the 4-section schema
    (overview / how_it_works / key_details / what_to_watch_for) plus
    ``cited_symbols`` and ``uncertain_regions``. The Orchestrator assembles the
    final markdown here in Python — no regex parsing of free-form prose.
    """
    state.writer_counter += 1
    if state.writer_counter > 1:
        state.writer_retries += 1
    draft_num = f"{state.writer_counter:03d}"
    draft_path = workspace.lesson_dir(lesson_id, "processing") / f"draft-{draft_num}.md"

    # Concatenate all research notes so the Writer gets full context in its prompt.
    combined_notes_parts: list[str] = []
    # Heuristic symbol extraction: backtick-wrapped identifiers from research notes.
    research_symbols: set[str] = set()
    for ref in research_refs:
        full = workspace.base_dir / ref
        if full.exists():
            content = full.read_text(encoding="utf-8")
            combined_notes_parts.append(content)
            research_symbols.update(_extract_research_symbols(content))
        else:
            combined_notes_parts.append(f"[Research file not found: {ref}]")
    combined_notes = "\n\n---\n\n".join(combined_notes_parts)

    card = compile_card(
        "writer",
        kwargs={
            "lesson_id": lesson_id,
            "lesson_title": lesson_title,
            "lesson_teaches": lesson_teaches,
            "primary_symbol": primary_symbol,
            "concepts_introduced": str(list(concepts_introduced)),
            "research_notes": combined_notes,
            "target_audience": target_audience,
            "budget_remaining_usd": f"{budget_usd:.2f}",
        },
        agents_dir=agents_dir,
    )

    draft_holder: dict[str, Any] = {}

    def _submit_lesson_draft(args: dict[str, Any]) -> str:
        # Terminal tool: capture structured draft and acknowledge.
        # Provider enforces JSON schema so args are pre-validated.
        draft_holder.clear()
        draft_holder.update(args)
        return "Draft submitted. Conclude your turn."

    writer_registry: dict[str, ToolFn] = {"submit_lesson_draft": _submit_lesson_draft}
    tool_specs = [_tool_spec_from_schema(s) for s in card.tools]
    executor = _make_tool_executor(writer_registry)

    user_msg = (
        f"Write the full tutorial lesson for `{lesson_id}` ({lesson_title}).\n"
        f"Lesson spec:\n{lesson_spec_json}\n\n"
    )
    if reviewer_feedback:
        user_msg += (
            f"REVIEWER FEEDBACK FROM PRIOR ATTEMPT (address all points before submitting):\n"
            f"{reviewer_feedback}\n\n"
        )
    user_msg += (
        "Submit your draft via the submit_lesson_draft tool. "
        "Do not write prose outside the tool call."
    )

    result: AgentResult = llm.run_agent(
        system=card.system_prompt,
        user=user_msg,
        tools=tool_specs,
        tool_executor=executor,
        model=model,
        max_iterations=card.budgets.max_iterations,
        max_cost_usd=budget_usd,
        spend_meter=spend_meter,
    )

    if draft_holder:
        # --- Programmatic sanity check: cited_symbols ⊂ research_symbols ---
        cited: list[str] = list(draft_holder.get("cited_symbols", []) or [])
        # Heuristic suffix match: "foo" is grounded if "module.submodule.foo" in research_symbols.
        ungrounded = [
            s
            for s in cited
            if s not in research_symbols
            and not any(rs == s or rs.endswith("." + s) for rs in research_symbols)
        ]

        # --- Assemble markdown from 4 structured sections + uncertain callouts ---
        uncertain_regions: list[Any] = list(draft_holder.get("uncertain_regions", []) or [])
        draft_body, _callouts = _assemble_draft_markdown(draft_holder)

        # Frontmatter for audit trail (cited_symbols, ungrounded_cited, uncertainty count)
        frontmatter_lines = [
            "---",
            "agent: writer",
            f"lesson_id: {lesson_id}",
            f"draft: {draft_num}",
            f"cited_symbols: {json.dumps(cited)}",
            f"ungrounded_cited: {json.dumps(ungrounded)}",
            f"uncertain_regions_count: {len(uncertain_regions)}",
            "---",
            "",
        ]
        draft_with_meta = "\n".join(frontmatter_lines) + draft_body
        workspace.write_atomic(draft_path, draft_with_meta)

        if ungrounded:
            logger.warning(
                "writer_ungrounded_cited lesson=%s draft=%s ungrounded=%s",
                lesson_id,
                draft_num,
                ungrounded,
            )
    else:
        # Fallback: model did not call submit_lesson_draft — save raw final_text with error marker.
        draft_body = result.final_text or ""
        if not draft_body.strip():
            draft_body = (
                f"[Writer produced no output and did not call submit_lesson_draft"
                f" — stop_reason={result.stop_reason}]"
            )
        workspace.write_atomic(draft_path, draft_body)
        logger.warning(
            "writer_no_structured_output lesson=%s draft=%s stop=%s",
            lesson_id,
            draft_num,
            result.stop_reason,
        )

    rel = str(draft_path.relative_to(workspace.base_dir))
    state.last_draft_path = rel
    logger.info(
        "writer_done lesson=%s draft=%s stop=%s structured=%s",
        lesson_id,
        draft_num,
        result.stop_reason,
        bool(draft_holder),
    )
    return f"Draft saved to {rel}."


def _run_reviewer(
    *,
    draft_path: str,
    research_refs: list[str],
    lesson_id: str,
    primary_symbol: str,
    concepts_introduced: tuple[str, ...],
    llm: LLMProvider,
    tool_registry: dict[str, ToolFn],
    workspace: RunWorkspace,
    model: str,
    budget_usd: float,
    spend_meter: SpendMeterProto | None,
    agents_dir: Path | None,
    word_count_floor: int,
    word_count_fatal_floor: int,
) -> str:
    """Run a Reviewer sub-agent and return its JSON verdict as a string."""
    full_draft = workspace.base_dir / draft_path
    draft_text = full_draft.read_text(encoding="utf-8") if full_draft.exists() else ""

    combined_notes_parts: list[str] = []
    for ref in research_refs:
        full_ref = workspace.base_dir / ref
        if full_ref.exists():
            combined_notes_parts.append(full_ref.read_text(encoding="utf-8"))
    combined_notes = "\n\n---\n\n".join(combined_notes_parts)

    card = compile_card(
        "reviewer",
        kwargs={
            "lesson_id": lesson_id,
            "draft_narrative": draft_text,
            "primary_symbol": primary_symbol,
            "research_notes": combined_notes,
            "concepts_introduced": str(list(concepts_introduced)),
            "word_count_floor": str(word_count_floor),
            "word_count_fatal_floor": str(word_count_fatal_floor),
        },
        agents_dir=agents_dir,
    )
    reviewer_registry: dict[str, ToolFn] = {
        k: v for k, v in tool_registry.items() if k in _REVIEWER_TOOLS
    }
    verdict_holder: dict[str, Any] = {}

    def _submit_verdict(args: dict[str, Any]) -> str:
        # Terminal tool: capture the structured verdict and acknowledge.
        # Provider enforces JSON schema, so args are pre-validated.
        verdict_holder.clear()
        verdict_holder.update(args)
        return "Verdict submitted. Conclude your turn."

    reviewer_registry["submit_verdict"] = _submit_verdict

    tool_specs = [_tool_spec_from_schema(s) for s in card.tools]
    executor = _make_tool_executor(reviewer_registry)

    result: AgentResult = llm.run_agent(
        system=card.system_prompt,
        user=(
            "Review the draft narrative provided in your system prompt.\n"
            "Run any verification tool calls you need, then call `submit_verdict` "
            "exactly once with your structured verdict. Do not write the verdict "
            "as plain text — only the tool arguments are read."
        ),
        tools=tool_specs,
        tool_executor=executor,
        model=model,
        max_iterations=card.budgets.max_iterations,
        max_cost_usd=budget_usd,
        spend_meter=spend_meter,
    )

    if verdict_holder:
        verdict_text = json.dumps(verdict_holder, ensure_ascii=False)
    else:
        verdict_text = json.dumps(
            {
                "verdict": "warn",
                "checks": [],
                "feedback": (
                    "Reviewer did not call submit_verdict; defaulting to warn so the "
                    "Orchestrator can decide whether to retry or accept."
                ),
            }
        )

    review_path = workspace.lesson_dir(lesson_id, "processing") / "review.md"
    workspace.write_atomic(review_path, verdict_text)

    logger.info(
        "reviewer_done lesson=%s stop=%s structured=%s",
        lesson_id,
        result.stop_reason,
        bool(verdict_holder),
    )
    return verdict_text


def _build_dispatch_tools(
    *,
    state: _OrchestratorState,
    spec: LessonSpec,
    concepts_introduced: tuple[str, ...],
    llm: LLMProvider,
    tool_registry: dict[str, ToolFn],
    workspace: RunWorkspace,
    models: dict[str, str],
    spend_meter: SpendMeterProto | None,
    agents_dir: Path | None,
    target_audience: str,
) -> dict[str, ToolFn]:
    """Return the 5 dispatch tool callables wired to sub-agents / state updates."""
    lesson_id = state.lesson_id
    primary_symbol = spec.code_refs[0].symbol if spec.code_refs else spec.id
    lesson_spec_json = json.dumps(
        {
            "lesson_id": lesson_id,
            "lesson_title": spec.title,
            "lesson_teaches": spec.teaches,
            "primary_symbol": primary_symbol,
            "code_refs": [r.symbol for r in spec.code_refs],
            "concepts_introduced": list(concepts_introduced),
        }
    )

    def _dispatch_researcher(args: dict[str, Any]) -> str:
        return _run_researcher(
            symbol=str(args.get("symbol", primary_symbol)),
            research_brief=str(args.get("research_brief", f"Understand {primary_symbol}")),
            budget_usd=float(args.get("budget_usd", 0.10)),
            lesson_id=lesson_id,
            concepts_introduced=concepts_introduced,
            llm=llm,
            tool_registry=tool_registry,
            workspace=workspace,
            state=state,
            model=models["researcher"],
            spend_meter=spend_meter,
            agents_dir=agents_dir,
        )

    def _dispatch_writer(args: dict[str, Any]) -> str:
        refs = list(args.get("research_refs", state.research_paths))
        ls_json = str(args.get("lesson_spec", lesson_spec_json))
        reviewer_fb = str(args.get("reviewer_feedback", "")).strip()
        return _run_writer(
            research_refs=refs,
            lesson_spec_json=ls_json,
            lesson_id=lesson_id,
            lesson_title=spec.title,
            lesson_teaches=spec.teaches,
            primary_symbol=primary_symbol,
            concepts_introduced=concepts_introduced,
            llm=llm,
            workspace=workspace,
            state=state,
            model=models["writer"],
            budget_usd=float(args.get("budget_usd", 0.30)),
            spend_meter=spend_meter,
            agents_dir=agents_dir,
            target_audience=target_audience,
            reviewer_feedback=reviewer_fb,
        )

    def _dispatch_reviewer(args: dict[str, Any]) -> str:
        draft = str(args.get("draft_path", state.last_draft_path or ""))
        refs = list(args.get("research_refs", state.research_paths))
        _span = (
            spec.code_refs[0].line_end - spec.code_refs[0].line_start + 1 if spec.code_refs else 1
        )
        return _run_reviewer(
            draft_path=draft,
            research_refs=refs,
            lesson_id=lesson_id,
            primary_symbol=primary_symbol,
            concepts_introduced=concepts_introduced,
            llm=llm,
            tool_registry=tool_registry,
            workspace=workspace,
            model=models["reviewer"],
            budget_usd=float(args.get("budget_usd", 0.15)),
            spend_meter=spend_meter,
            agents_dir=agents_dir,
            word_count_floor=floor_for_span(_span),
            word_count_fatal_floor=fatal_floor_for_span(_span),
        )

    def _mark_lesson_done(args: dict[str, Any]) -> str:
        narrative = str(args.get("final_narrative", ""))
        if not narrative.strip() and state.last_draft_path:
            full = workspace.base_dir / state.last_draft_path
            if full.exists():
                narrative = full.read_text(encoding="utf-8")

        lesson = Lesson(
            id=lesson_id,
            title=spec.title,
            narrative=narrative or f"Lesson {lesson_id} — narrative pending.",
            code_refs=tuple(r.symbol for r in spec.code_refs),
            status="generated",
        )
        workspace.write_json_atomic(
            workspace.lesson_dir(lesson_id, "finished") / "lesson.json",
            lesson.model_dump(),
        )
        state.result = lesson
        logger.info("lesson_done lesson=%s", lesson_id)
        return f"Lesson {lesson_id} marked as done."

    def _skip_lesson(args: dict[str, Any]) -> str:
        reason = str(args.get("reason", "Orchestrator called skip_lesson without reason"))
        skipped = SkippedLesson(
            lesson_id=lesson_id,
            title=spec.title,
            missing_symbols=(primary_symbol,),
            reason=reason,
        )
        _persist_skipped_lesson(workspace, lesson_id, skipped)
        state.result = skipped
        logger.info("lesson_skipped lesson=%s reason=%s", lesson_id, reason)
        return f"Lesson {lesson_id} skipped: {reason}"

    return {
        "dispatch_researcher": _dispatch_researcher,
        "dispatch_writer": _dispatch_writer,
        "dispatch_reviewer": _dispatch_reviewer,
        "mark_lesson_done": _mark_lesson_done,
        "skip_lesson": _skip_lesson,
    }


def _persist_skipped_lesson(
    workspace: RunWorkspace,
    lesson_id: str,
    skipped: SkippedLesson,
) -> None:
    """Write a ``finished/lesson.json`` sentinel for a skipped lesson.

    Idempotent — uses ``write_json_atomic`` (os.replace) so re-runs overwrite
    with the latest reason rather than failing on an already-existing file.

    Args:
        workspace: Filesystem workspace for this run.
        lesson_id: The lesson identifier (e.g. ``"lesson-001"``).
        skipped: The :class:`SkippedLesson` instance whose reason to persist.
    """
    workspace.write_json_atomic(
        workspace.lesson_dir(lesson_id, "finished") / "lesson.json",
        {"skipped": True, "reason": skipped.reason, "lesson_id": skipped.lesson_id},
    )


_WRITER_SECTIONS: tuple[str, ...] = (
    "overview",
    "how_it_works",
    "key_details",
    "in_context",
    "what_to_watch_for",
)


def _assemble_narrative_from_structured(text: str) -> str:
    """Defensive fix: closing-lesson Writer is given ``tools=[]`` and may emit a
    JSON blob (matching ``submit_lesson_draft`` schema) as plain text instead of
    markdown. Parse it and stitch the four sections into a single narrative.

    Returns ``text`` unchanged when it does not look like a structured payload.
    """
    stripped = text.strip()
    # Strip code-fence wrapper (```json ... ```) that some models add when forced
    # into plain text mode.
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1).strip()
    if not stripped.startswith("{"):
        return text
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return text
    if not isinstance(data, dict):
        return text
    sections = [
        str(data[key]).strip()
        for key in _WRITER_SECTIONS
        if isinstance(data.get(key), str) and str(data[key]).strip()
    ]
    return "\n\n".join(sections) if sections else text


def run_closing_lesson(
    spec: LessonSpec,
    *,
    workspace: RunWorkspace,
    llm: LLMProvider,
    concepts_introduced: tuple[str, ...] = (),
    models: dict[str, str] | None = None,
    budget_remaining_usd: float = 1.0,
    spend_meter: SpendMeterProto | None = None,
    agents_dir: Path | None = None,
    target_audience: str = _DEFAULT_TARGET_AUDIENCE,
) -> RunLessonOutcome:
    """Lightweight single-writer pass for the synthetic closing lesson.

    The closing lesson has ``code_refs=()`` — there is no symbol to research.
    Skip the Orchestrator/Researcher/Reviewer pipeline; call the Writer once
    with ``spec.teaches`` as context.

    Args:
        spec: The synthetic ``LessonSpec`` with ``is_closing=True``.
        workspace: Filesystem workspace for this run.
        llm: LLM provider implementing ``run_agent``.
        concepts_introduced: All concepts taught in prior regular lessons.
        models: ``{role: model_id}`` override; uses ``_DEFAULT_MODELS`` as base.
        budget_remaining_usd: Budget cap for the single Writer call.
        spend_meter: Optional cumulative cost tracker.
        agents_dir: Override for agent cards directory (useful in tests).
        target_audience: Audience label forwarded to the Writer prompt.

    Returns:
        :class:`RunLessonOutcome` carrying either :class:`Lesson` or
        :class:`SkippedLesson` plus pipeline metrics (always
        ``writer_retries=0`` here — closing lesson never retries).
    """
    resolved_models = {**_DEFAULT_MODELS, **(models or {})}
    lesson_id = spec.id

    if workspace.is_finished(lesson_id):
        finished_path = workspace.base_dir / "finished" / lesson_id / "lesson.json"
        try:
            data = workspace.read_json(finished_path)
            if isinstance(data, dict) and not data.get("skipped"):
                return RunLessonOutcome(result=Lesson.model_validate(data))
        except (json.JSONDecodeError, OSError, ValidationError):
            logger.warning(
                "closing_lesson_resume_parse_error lesson=%s",
                lesson_id,
                exc_info=True,
            )

    closing_notes = (
        f"This is the closing 'Where to go next' lesson.\n\n"
        f"Teaching objective: {spec.teaches}\n\n"
        f"Write a helpful closing section for a developer who has just read the entire tutorial."
    )
    card = compile_card(
        "writer",
        kwargs={
            "lesson_id": lesson_id,
            "lesson_title": spec.title,
            "lesson_teaches": spec.teaches,
            "primary_symbol": "closing",
            "concepts_introduced": str(list(concepts_introduced)),
            "research_notes": closing_notes,
            "target_audience": target_audience,
            "budget_remaining_usd": f"{budget_remaining_usd:.2f}",
        },
        agents_dir=agents_dir,
    )

    result: AgentResult = llm.run_agent(
        system=card.system_prompt,
        user=(
            f"Write the closing 'Where to go next' lesson for the tutorial.\n"
            f"Teaching objective: {spec.teaches}\n\n"
            f"Focus on helping the reader continue exploring the codebase independently."
        ),
        tools=[],
        tool_executor=lambda tc: ToolResult(tool_call_id=tc.id, content="no tools", is_error=True),
        model=resolved_models["writer"],
        max_iterations=1,
        max_cost_usd=budget_remaining_usd,
        spend_meter=spend_meter,
    )

    narrative = _assemble_narrative_from_structured(result.final_text or "")
    if not narrative.strip():
        skipped = SkippedLesson(
            lesson_id=lesson_id,
            title=spec.title,
            missing_symbols=(),
            reason="Closing lesson Writer produced no output",
        )
        _persist_skipped_lesson(workspace, lesson_id, skipped)
        return RunLessonOutcome(result=skipped)

    lesson = Lesson(
        id=lesson_id,
        title=spec.title,
        narrative=narrative,
        code_refs=(),
        status="generated",
    )
    workspace.write_json_atomic(
        workspace.lesson_dir(lesson_id, "finished") / "lesson.json",
        lesson.model_dump(),
    )
    return RunLessonOutcome(result=lesson)


def run_lesson(
    spec: LessonSpec,
    *,
    workspace: RunWorkspace,
    llm: LLMProvider,
    tool_registry: dict[str, ToolFn],
    concepts_introduced: tuple[str, ...] = (),
    models: dict[str, str] | None = None,
    budget_remaining_usd: float = 5.0,
    spend_meter: SpendMeterProto | None = None,
    agents_dir: Path | None = None,
    target_audience: str = _DEFAULT_TARGET_AUDIENCE,
) -> RunLessonOutcome:
    """Run the full per-lesson multi-agent pipeline.

    Orchestrates Researcher x N -> Writer -> Reviewer agents for a single lesson.
    The Orchestrator LLM drives the loop via tool calls; Python dispatch tools
    execute sub-agents synchronously and persist results to the workspace.

    Args:
        spec: The ``LessonSpec`` from Stage 4 (planning) for this lesson.
        workspace: Filesystem workspace for this run (artefact I/O).
        llm: LLM provider implementing ``run_agent``.
        tool_registry: Pre-built ``{name: fn}`` map from
            :func:`~wiedunflow.use_cases.agent_tools.build_tool_registry`.
        concepts_introduced: Tuple of concept names already taught in prior
            lessons — propagated into every sub-agent prompt.
        models: ``{role: model_id}`` override map.  Missing roles fall back to
            :data:`_DEFAULT_MODELS`.
        budget_remaining_usd: Soft per-lesson budget cap passed to the
            Orchestrator.  Sub-agent calls deduct from the global spend_meter.
        spend_meter: Optional :class:`SpendMeterProto` for cumulative cost
            tracking across the entire run.
        agents_dir: Override for the agent cards directory (useful in tests).
        target_audience: Audience label forwarded to the Writer prompt.

    Returns:
        :class:`RunLessonOutcome` wrapping either a
        :class:`~wiedunflow.entities.lesson.Lesson` (Orchestrator called
        ``mark_lesson_done``) or
        :class:`~wiedunflow.entities.skipped_lesson.SkippedLesson` (skip /
        budget exhaustion / fallback), plus the count of additional Writer
        dispatches beyond the first (= retries).
    """
    resolved_models = {**_DEFAULT_MODELS, **(models or {})}
    lesson_id = spec.id
    primary_symbol = spec.code_refs[0].symbol if spec.code_refs else spec.id

    # Resume check — skip if already finished in a prior run.
    if workspace.is_finished(lesson_id):
        finished_path = workspace.base_dir / "finished" / lesson_id / "lesson.json"
        try:
            data = workspace.read_json(finished_path)
            if isinstance(data, dict) and data.get("skipped"):
                return RunLessonOutcome(
                    result=SkippedLesson(
                        lesson_id=lesson_id,
                        title=spec.title,
                        missing_symbols=(primary_symbol,),
                        reason=str(data.get("reason", "skipped in prior run")),
                    )
                )
            return RunLessonOutcome(result=Lesson.model_validate(data))
        except Exception as exc:
            logger.warning("resume_parse_error lesson=%s exc=%r — re-running", lesson_id, exc)

    state = _OrchestratorState(lesson_id=lesson_id)
    dispatch = _build_dispatch_tools(
        state=state,
        spec=spec,
        concepts_introduced=concepts_introduced,
        llm=llm,
        tool_registry=tool_registry,
        workspace=workspace,
        models=resolved_models,
        spend_meter=spend_meter,
        agents_dir=agents_dir,
        target_audience=target_audience,
    )

    orchestrator_card = compile_card(
        "orchestrator",
        kwargs={
            "lesson_id": lesson_id,
            "lesson_title": spec.title,
            "lesson_teaches": spec.teaches,
            "primary_symbol": primary_symbol,
            "code_refs": str([r.symbol for r in spec.code_refs]),
            "concepts_introduced": str(list(concepts_introduced)),
            "budget_remaining_usd": f"{budget_remaining_usd:.2f}",
        },
        agents_dir=agents_dir,
    )
    tool_specs = [_tool_spec_from_schema(s) for s in orchestrator_card.tools]
    orch_executor = _make_tool_executor(dispatch)

    orch_result: AgentResult = llm.run_agent(
        system=orchestrator_card.system_prompt,
        user=(
            f"Run the research-write-review pipeline for lesson `{lesson_id}`: {spec.title}.\n"
            f"Teaching: {spec.teaches}\n"
            f"Primary symbol: `{primary_symbol}`\n"
            f"Budget: ${budget_remaining_usd:.2f} USD\n"
            f"Begin by dispatching at least one Researcher, then Writer, then Reviewer."
        ),
        tools=tool_specs,
        tool_executor=orch_executor,
        model=resolved_models["orchestrator"],
        max_iterations=orchestrator_card.budgets.max_iterations,
        max_cost_usd=budget_remaining_usd,
        spend_meter=spend_meter,
    )

    if state.result is not None:
        return RunLessonOutcome(result=state.result, writer_retries=state.writer_retries)

    # Orchestrator exited without calling mark_lesson_done or skip_lesson.
    # Fall back: use the last draft if available, otherwise skip.
    logger.warning(
        "orchestrator_no_decision lesson=%s stop=%s — fallback",
        lesson_id,
        orch_result.stop_reason,
    )
    if state.last_draft_path:
        full_draft = workspace.base_dir / state.last_draft_path
        if full_draft.exists():
            narrative = full_draft.read_text(encoding="utf-8")
            if narrative.strip():
                lesson = Lesson(
                    id=lesson_id,
                    title=spec.title,
                    narrative=narrative,
                    code_refs=tuple(r.symbol for r in spec.code_refs),
                    status="generated",
                )
                workspace.write_json_atomic(
                    workspace.lesson_dir(lesson_id, "finished") / "lesson.json",
                    lesson.model_dump(),
                )
                return RunLessonOutcome(result=lesson, writer_retries=state.writer_retries)

    skipped = SkippedLesson(
        lesson_id=lesson_id,
        title=spec.title,
        missing_symbols=(primary_symbol,),
        reason=(f"Orchestrator finished without decision (stop_reason={orch_result.stop_reason})"),
    )
    _persist_skipped_lesson(workspace, lesson_id, skipped)
    return RunLessonOutcome(result=skipped, writer_retries=state.writer_retries)
