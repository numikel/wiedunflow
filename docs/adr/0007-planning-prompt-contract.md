# ADR-0007 — Planning prompt contract (Stage 4)

Status: Accepted (revised 2026-04-25 for v0.2.1)
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
- ADR-0012 (tutorial quality enforcement) — extends this contract additively.
- Code: `src/codeguide/use_cases/plan_lesson_manifest.py`,
  `src/codeguide/entities/lesson_manifest.py`.

## Revision log

### v0.2.1 (2026-04-25) — additive `source_excerpt` + happy-path heuristic

Two additive changes that do NOT break the planning contract:

1. **`code_refs[*].source_excerpt`** — new optional field, `str | None`,
   max 4000 chars. Populated post-planning by
   `use_cases/inject_source_excerpts.py` from the AST snapshot for every
   primary `code_ref` whose body span is <30 lines. The planning LLM does
   not produce this field — it is downstream enrichment for the narration
   stage, which now requires verbatim signature quoting from
   `source_excerpt` (gated by `narration.snippet_validation`). Schema
   version remains `1.0.0`: the field is optional, older cache JSON
   deserialises unchanged.

2. **Happy-path lesson ordering** — the planning prompt now instructs the
   LLM to place the entry-point lesson at position 1 (lessons 2..N-2 keep
   leaves→roots, N-1 = top-level orchestration, N = closing). A
   post-planning reorder hook
   (`use_cases/plan_lesson_manifest._apply_entry_point_first`) acts as
   safety net when the LLM ignores the instruction. Entry points are
   detected by `use_cases/entry_point_detector.detect_entry_points`
   (heuristics: `def main`/`def cli`/`def run_*`,
   `if __name__ == "__main__":` blocks, `@click.command`/`@app.command`
   decorators, `__main__.py` modules). The reorder hook is configurable
   via `planning.entry_point_first: auto|always|never` (default `auto`,
   no-op when no entry point is detected). The grounding invariant and
   1-retry policy are unchanged.
