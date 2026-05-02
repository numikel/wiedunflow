# ADR-0017: Cost reporting wire-through — SpendMeter propagation

- **Status**: Accepted
- **Date**: 2026-05-02
- **Deciders**: Michał Kamiński (product owner)
- **Related ADRs**: ADR-0016 (multi-agent narration pipeline), ADR-0014 (PricingCatalog), ADR-0013 (cost-gate prompt)
- **Relates to**: v0.9.0

## Context

Prior to v0.9.0, `RunReport.total_cost_usd` was hardcoded to `0.0` throughout the pipeline
(`cli/main.py::_write_final_report`). The multi-agent pipeline introduced in ADR-0016 added
`run_agent()` calls in both `OpenAIProvider` and `AnthropicProvider`, each making multiple
LLM API calls per lesson. Without a live cost accumulator, users saw `total_cost: $0.00` in
the CLI success banner regardless of actual spend — defeating the cost-gate promise of
ADR-0013.

The PricingCatalog (ADR-0014) already provides per-model blended prices; it was unused at
runtime beyond the pre-flight cost-gate estimate.

## Decision

Introduce `SpendMeter` (`src/wiedunflow/use_cases/spend_meter.py`) as a single-instance,
thread-safe cost accumulator created in `_run_pipeline` and propagated through the call
chain:

```
_run_pipeline → generate_tutorial → _stage_generation → run_lesson → llm.run_agent
```

`SpendMeter.charge(model_id, input_tokens, output_tokens)` is called inside the adapter
tool-call loops (`anthropic_provider.py` and `openai_provider.py` `run_agent` paths) after
every API response. `would_exceed(max_cost_usd)` is checked before each dispatch to enforce
the per-lesson cost cap, completing the cost-guard triple-backstop:

1. **Pre-flight estimator** — CLI cost gate (existing, ADR-0013).
2. **Live SpendMeter.charge()** per call — new in v0.9.0.
3. **Per-lesson `max_cost_usd` cap** on `run_agent()` — new in v0.9.0.

`RunReport.total_cost_usd` is populated from `SpendMeter.total_cost_usd` at pipeline end.
The CLI success banner now renders `total_cost: $X.XX`.

## Consequences

### Positive
- Accurate real-time cost reporting matching the eval baseline ($3.82 for 25 lessons,
  previously falsely reported as `$0.00`).
- Per-lesson cap enforceable mid-loop — long lessons that overrun their budget abort
  cleanly with `CostExceededError` instead of silently consuming the whole pre-flight
  estimate.
- `SpendMeter.snapshot()` exposes per-stage breakdown for observability tooling.

### Negative
- `SpendMeter` instance must be passed through 4 call frames — adds an optional
  parameter to `generate_tutorial`, `run_lesson`, and `run_agent` signatures (BREAKING
  for any external callers using these as library functions — none exist pre-public).
- Cost accuracy is bounded by `PricingCatalog` freshness; stale prices in the static
  fallback can under- or over-report by 1-5% versus actual provider invoices.

## Alternatives Considered

**1. Module-level / global accumulator** — Rejected: violates Clean Architecture (no
shared mutable state in use cases), makes parallel future runs (multiple repos in one
process) impossible, complicates testing.

**2. Adapter-internal accumulator surfaced via attribute** — Rejected: adapters become
stateful in a way that the `LLMProvider` port does not declare, undermining the
hexagonal boundary.

**3. Post-hoc computation from transcripts** — Rejected: requires every adapter to
write structured token-usage records, doubles disk I/O, and cannot enforce the
per-lesson cap mid-run.

## References

- `src/wiedunflow/use_cases/spend_meter.py` — implementation.
- `src/wiedunflow/use_cases/generate_tutorial.py` — propagation through `_stage_generation`.
- `tests/integration/test_cost_reporting_e2e.py` — end-to-end assertion that
  `RunReport.total_cost_usd > 0` after a real-LLM run.
- `tests/unit/use_cases/test_spend_meter.py` — `charge()` / `would_exceed()` invariants.
