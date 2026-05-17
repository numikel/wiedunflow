# ADR-0016: Multi-agent narration pipeline (Stage 5/6)

**Status:** Accepted (2026-05-02)
**Supersedes:** ADR-0007 (planning prompt contract — narrative parts), partial supersedes of v0.2.1 single-shot generation in `use_cases/grounding_retry.py`.
**Successors:** ADR-0017 (cost reporting wire-through), ADR-0018 (Jedi heuristic fallback).

## Context

WiedunFlow v0.7.0 used a single-shot LLM call per lesson: `narrate(spec_json, concepts_introduced) → Lesson`. The model received only a packed lesson spec with `source_excerpt` (v0.2.1) and was expected to produce the full narrative in one turn. Empirical findings on the 5-repo eval corpus (2026-04-30/05-01):

- **Narrative stays close to excerpt** but loses "why does this exist" context (no callers, no documentation, no tests).
- **Reviewer-retry** (`grounding_retry.py`) operates only on signature regex — cannot verify business logic claims.
- **Trivial helpers** consume the same compute as critical lessons (flat compute distribution).

## Decision

Replace single-shot narration with **per-lesson multi-agent pipeline**:

```
Stage 5 Planning (Python orchestration, single LLM call) → lesson_manifest.json
Stage 6 Multi-Agent (per-lesson, sequential):
  Orchestrator (LLM, smart, dispatching)
    ├── dispatch_researcher(symbol, brief) ──→ Researcher agent (8 tools)
    ├── dispatch_writer(research_refs)    ──→ Writer agent (submit_lesson_draft)
    ├── dispatch_reviewer(draft, refs)    ──→ Reviewer agent (submit_verdict)
    ├── mark_lesson_done()
    └── skip_lesson(reason)
```

**Sequential per-lesson invariant**: lesson N+1 starts only after lesson N hits `finished/` — `concepts_introduced` stays coherent, no race conditions.

**Filesystem-mediated message bus** at `~/.wiedunflow/runs/<run_id>/`:
- `processing/lesson-N/{research-NNN.md, draft-NNN.md, review.md}` — in-flight artefacts.
- `finished/lesson-N/lesson.json` — atomic checkpoint via `os.replace`.
- `transcript/lesson-N/*.jsonl` — full audit trail.

**Structured output for Writer and Reviewer** via terminal tools (`submit_lesson_draft`, `submit_verdict`) with JSON Schema enforced natively by OpenAI Structured Outputs and Anthropic tool use. Eliminates malformed-JSON failure mode entirely.

**Cost guard triple-backstop**: pre-flight estimator → live `SpendMeter` per-call → per-lesson `max_cost_usd` cap.

**Cost-tiered model split**:

| Role | OpenAI default | Anthropic BYOK |
|------|----------------|----------------|
| Orchestrator | `gpt-5.4` | `claude-sonnet-4-6` |
| Researcher | `gpt-5.4-mini` | `claude-haiku-4-5` |
| Writer | `gpt-5.4` | `claude-opus-4-7` |
| Reviewer | `gpt-5.4-mini` | `claude-haiku-4-5` |

## Alternatives considered

1. **LangChain/LangGraph supervisor pattern** — rejected per ADR-0001 (no LangChain dependency). Manual tool loops on native SDKs preserve the no-LangChain invariant.
2. **`anthropic.beta.messages.tool_runner()`** — rejected: beta API, no parity with OpenAI function calling, would lock us to one provider.
3. **Single-agent-per-lesson (no Researcher/Writer/Reviewer split)** — rejected: monolithic prompt cannot enforce verbatim citation discipline OR multi-stage tool exploration. The split lets each role optimize for one objective.
4. **Free-form Writer output (no `submit_lesson_draft`)** — rejected: empirically (eval lesson-005, 007) Writer hallucinates plausible-sounding class names without forced cited_symbols schema.

## Consequences

**Positive:**
- Zero hallucinated symbols in eval (precision 100%).
- Cited-symbols sanity check programmatic — Reviewer can fail fast.
- Filesystem audit trail enables replay debugging.
- Resume support via `finished/` scan.
- Provider-agnostic (same pipeline on OpenAI and Anthropic).

**Negative:**
- Latency increased: 25 min for 16 lessons (cold-start) vs ~10 min for v0.7.0 single-shot.
- Cost per lesson ~$0.10-0.15 vs $0.05-0.08 v0.7.0 (recovered by 0 hallucinations — no manual rework needed).
- `LLMProvider.narrate()` and `describe_symbol()` removed (BREAKING for any external integrators — none yet, pre-public).

## References

- Plan blueprint: `~/.claude/plans/hej-naszym-celem-jest-polished-wren.md`
- Related ADRs: ADR-0001 (no LangChain), ADR-0007 (planning contract), ADR-0014 (PricingCatalog), ADR-0015 (default provider).
- Successor ADRs: ADR-0017, ADR-0018.

## Cleanup completion (v0.10.0)

The original v0.9.0 ADR landed the multi-agent pipeline but left the predecessor symbols in place behind a "BREAKING for any external integrators — none yet" note. v0.10.0 closes that loop:

- **`LLMProvider` Protocol shrunk** to `plan()` + `run_agent()`. `narrate()` and `describe_symbol()` removed entirely from the port and from all three adapters (`AnthropicProvider`, `OpenAIProvider`, `FakeLLMProvider`). Adapter constructor params `max_tokens_narrate`, `max_tokens_describe`, `model_narrate`, `model_describe` removed.
- **`adapters/llm_prompts.py`** pared down to `PLAN_SYSTEM_PROMPT` only. `NARRATE_SYSTEM_PROMPT` and `DESCRIBE_SYSTEM_PROMPT` deleted.
- **`use_cases/grounding_retry.py` (438 lines) deleted** — the last caller of `llm.narrate()`. Its companion `use_cases/snippet_validator.py` (155 lines) deleted too — it was used only by `grounding_retry`. The Reviewer rubric in the new pipeline subsumes both grounding validation and snippet checking.
- **Cost estimator rewritten** for the v0.9.0+ multi-agent reality. The old v0.7.0 formula (`symbols × 500 + lessons × 8000`) under-estimated typical runs by ~15× because it modeled a single narration call per lesson. The new model has per-role token ceilings derived from the agent cards (Orchestrator + Researcher × N + Writer + Reviewer per lesson) and a per-role `RoleCost` breakdown surfaced in the cost-gate prompt (5-row table) and the menu Summary panel.
- **CLI surface preserved**: legacy `--model-narrate` flag and `llm_model_narrate` config field stay as aliases that map onto the Writer role (the primary narration agent in the multi-agent pipeline), so existing configs and scripts continue to work. Per-role override is available through the multi-agent provider constructors (`model_orchestrator`, `model_researcher`, `model_writer`, `model_reviewer`).
- **Stale references fixed** in `use_cases/generate_tutorial.py`, `entities/skipped_lesson.py` (including the default `reason` value, which was the literal string `"grounding_retry_exhausted"`), and `tests/integration/test_sprint4_e2e.py`.
- **~30 test cases removed** (narrate/describe_symbol coverage in adapter test suites and the entire `test_grounding_retry.py` + `test_snippet_validator.py` files); ~38 new test cases added covering the per-role cost estimator and the 5-row cost gate.
