# ADR-0007 — Planning prompt contract (Stage 4)

Status: Accepted
Date: 2026-04-20
Sprint: 3

## Context

Stage 4 (Planning) is the only place where the pipeline asks the LLM for
*structure* — everything else is free-text narration. The planning contract
must be stable because every downstream stage (5/6/7) depends on it: lesson
ids, the leaves-to-roots ordering, and the symbols in `code_refs` determine
what gets rendered.

## Decision

1. **Single LLM call**: Claude Sonnet 4.6 with `max_tokens=8000`. Sonnet is
   chosen for cost and speed; Opus is reserved for narration (FR-64).
2. **Prompt shape**: a system prompt with "STRICT RULES" (JSON only, no prose,
   grounded, leaves-first, max 30 lessons), followed by a user prompt
   containing the outline and the allowed-symbols list.
3. **JSON schema versioning**: `metadata.schema_version: "1.0.0"` (FR-56).
   A schema change requires a major version bump.
4. **Grounding invariant** (hard rule): every `code_refs[*].symbol` MUST exist
   in `allowed_symbols` — derived from `RankedGraph`, minus `is_uncertain`,
   `is_dynamic_import`, and cyclic SCC members. Validation is performed in the
   entities layer via `validate_against_graph(manifest, allowed_symbols)`.
5. **Retry budget**: 1 retry with a reinforcement prompt (2 LLM calls total).
   The reinforcement prompt appends the error message, the list of invalid
   symbols from the previous response, and the top-N allowed symbols as a
   reminder.
6. **Fatal fail**: when both attempts fail, `PlanningFatalError` is raised,
   exit code 1 is returned, and the run-report is
   `{status: "failed", stage: "planning", attempts: 2, last_error: ...}`.
   There is no Stage 5 fallback — planning is foundational.

## Consequences

- **Positive**: deterministic contract, measurable grounding rate (FR-36/37
  eval metric = 0 % hallucinated symbols), small retry budget keeps cost
  within the $8/tutorial hard cap.
- **Negative**: no graceful degradation. An uncorrectable planning failure
  produces no tutorial. The alternative ("partial tutorial with N lessons")
  was rejected: the user cannot distinguish partial from incomplete, and the
  narrative-coherence invariant (lesson N must not re-teach concepts 1..N-1)
  breaks silently when lessons are missing.
- **Cost**: worst case 2 × `max_tokens=8000` ≈ $0.24 per failed run
  (Sonnet 4.6 pricing, April 2026). Acceptable.

## Alternatives considered

- **Multi-call planning** (outline pass + detail pass): rejected — doubles
  cost with no demonstrated quality improvement.
- **3+ retries**: rejected — diminishing returns; a third failure almost
  certainly indicates a systematic prompt or context problem, not a fluke.
- **Degraded fallback** (skip failed lessons): rejected — violates the
  `concepts_introduced` coherence invariant, producing subtly broken output
  that is harder to diagnose than an explicit failure.

## Related

- FR-32 (lesson structure), FR-36/37 (grounding), FR-56 (schema versioning),
  US-033 (fatal fail on planning), US-048 (schema_version in output JSON).
- ADR-0001 (LLM stack), ADR-0002 (RAG), ADR-0006 (AST snapshot schema).
- Code: `src/codeguide/use_cases/plan_lesson_manifest.py`,
  `src/codeguide/entities/lesson_manifest.py`.
