# ADR-0021: Cache, history, and timeout policy

- **Status**: Accepted
- **Date**: 2026-05-17
- **Deciders**: Michał Kamiński (product owner)
- **Related ADRs**: ADR-0014 (dynamic pricing catalog), ADR-0016 (multi-agent narration), ADR-0020 (per-token pricing)
- **Relates to**: v0.11.0

## Context

After ADR-0016 wired the multi-agent narration pipeline in v0.9.0 and ADR-0020 closed the cost-reporting accuracy gap in v0.9.5, three latent inefficiencies remained visible in production runs:

1. **Anthropic prompt caching was declared on every agent card but never wired.** Each ``run_agent`` iteration billed the system prompt and tool schemas at full input rate. For a 20-lesson tutorial running four agent roles at fifteen iterations each, that meant roughly three million tokens of static content paid at 100% of the input rate when 90% of them could have been served from Anthropic's ephemeral cache at the published 0.1× discount.
2. **BM25 corpus index rebuilt every run.** ``Stage 4 (RAG)`` rebuilt the corpus and the underlying ``BM25Okapi`` data structure on every invocation, even for incremental runs on an unchanged commit. The corpus assembly itself is fast; ``BM25Okapi(tokenized_corpus, k1=1.5, b=0.75)`` is the expensive part and scales with ``N * avg_doc_length``.
3. **Unbounded agent message history.** ``run_agent`` appended every assistant turn and tool-result message to the conversation, replaying the full history on every subsequent provider call. Input cost grew quadratically with iteration count; the Orchestrator at iteration 15 routinely shipped 30–50 KB of conversation per request.

A fourth correctness gap surfaced from local-endpoint user testing: ``OpenAIProvider`` hardcoded an ``httpx.Timeout(read=55.0)``, which is fine for cloud BYOK but cuts off Ollama/LM Studio/vLLM running a 13B+ model on CPU before the server can stream a single response.

This ADR records the seven binary decisions taken to close all four gaps together in v0.11.0.

## Decisions

### D1 — Cache scope policy

``cache_control={"type": "ephemeral"}`` is attached to the system prompt and to the **last** tool schema of every ``run_agent`` Anthropic call when ``prompt_caching=True`` is set on the compiled agent card (the default for all four shipped cards). Single-shot helpers (``_create_with_retry`` paths driving ``plan()``) stay on the plain-string system parameter — those system prompts are reliably below Anthropic's per-model 1024-token cache threshold and a marker there would be silently ignored.

### D2 — Cache TTL policy

Only standard 5-minute ephemeral TTL in v0.11.0. The extended 1-hour TTL (which costs 2× cache writes) is deferred until a workload that benefits from it materialises — multi-lesson generation already fits comfortably in the 5-minute window because each Researcher/Writer/Reviewer trip completes in well under that bound. Revisiting requires a future ADR amendment when usage data justifies the higher write cost.

### D3 — Cache cost accounting placement

Provider-specific cache pricing multipliers (Anthropic write × 1.25, Anthropic read × 0.1, OpenAI cached × 0.5) live as module-level constants in ``SpendMeter``, not in the ``PricingCatalog`` Protocol. The catalog continues to return a 2-tuple ``(input, output)`` per million tokens. Moving cache pricing into the catalog would have forced a BREAKING migration across Static / LiteLLM / Cached / Chained adapters for a feature the catalog itself does not need to know about. A 4-tuple expansion stays on the table for the day a third provider with a meaningfully different cache pricing shape ships.

### D4 — Provider detection in SpendMeter

Provider routing inside ``SpendMeter.charge`` uses model-name prefix detection: ``claude-`` → Anthropic, ``gpt-`` / ``o1`` / ``o3`` / ``o4`` / ``ft:`` → OpenAI. Unknown prefixes (OSS endpoint model names, test fixtures, custom deployments) fall back to the Anthropic-style accounting branch because at ``cache_*_input_tokens=0`` it is bit-equivalent to the legacy ``input × ip + output × op`` formula. Callers needing OpenAI-style cached-token accounting for an out-of-vocabulary model name pass ``provider="openai"`` explicitly.

### D5 — BM25 cache invalidation

Cached BM25 index rows are keyed by ``(repo_abs, commit_hash, corpus_config_fingerprint)``. The fingerprint is a 16-character SHA-256 prefix over the sorted union of ``exclude_patterns`` and ``include_patterns`` from ``tutorial.config.yaml``. Changing either pattern set invalidates the row, which closes the otherwise-silent quality regression where a filter change would load the wrong corpus on a hit. ``rank_bm25`` package version is stored alongside the BLOB; a mismatch is treated as a miss so a library upgrade never surfaces as an opaque ``UnpicklingError``. Pickle is the serialization format — the cache lives in the user-local platform cache directory (no network surface), and ``BM25Okapi`` keeps all its state in plain Python primitives plus numpy arrays.

### D6 — Sliding window history policy

``run_agent`` compresses the conversation when the running iteration count exceeds ``max_history_iterations`` (default 10, configurable per agent card via ``AgentCardBudgets.max_history_iterations``). The first 5 iterations stay verbatim, the next 5 collapse into a one-line synthetic ``role="user"`` summary referencing the tool names called and the first 80 characters of each tool's response, and the most recent 5 iterations stay verbatim. The system prompt and the initial user message are preserved unconditionally. Compression is **pair-aware** for both providers: an Anthropic ``tool_use_id`` referenced in an assistant turn is never separated from its matching ``tool_result`` block, and an OpenAI ``tool_call_id`` is never orphaned from its ``role="tool"`` message. The compressor is idempotent across iterations — prior synthetic summary markers are removed before recomputing the window so each call leaves at most one summary line.

### D7 — HTTP timeout config precedence

``tutorial.config.yaml`` accepts ``llm.http_read_timeout_s: int | None`` with Pydantic-validated range ``1..3600`` seconds. Precedence top-down: explicit config field > ``WIEDUNFLOW_HTTP_READ_TIMEOUT`` env var > auto-detection (55 s when ``base_url is None``, 600 s when ``base_url`` is set, i.e. local-endpoint BYOK). The interactive ``wiedunflow init`` wizard prompts for the value when the chosen provider is ``openai_compatible`` or ``custom``; hosted setups finish the wizard in the same five steps as before. ``OpenAIProvider`` reads the env override at construction time and rejects non-numeric values with a clear ``ValueError`` so a typo never silently keeps the 55 s default.

## Consequences

### Positive

- Anthropic agent loop calls drop input cost roughly in half on cache hits, with the savings concentrated on the largest per-tutorial cost driver (system + tools, repeated 15× per agent per lesson).
- BM25 incremental runs on the same commit skip the entire Stage 4 corpus build (~100 ms vs several seconds for medium repos).
- Input cost growth across the agent loop becomes linear in iteration count instead of quadratic.
- The OSS BYOK path advertised in the README (Ollama / LM Studio / vLLM) finally works for 13B+ CPU-bound models without timing out on the first Stage 5 call.
- ``SpendMeter`` cost reporting tracks real provider invoices within the ~5% accuracy band ADR-0020 demanded, including for cached input tiers.

### Negative

- ``LLMProvider.run_agent`` Protocol grew two new kwargs (``prompt_caching``, ``max_history_iterations``). Both are defaulted so existing callers keep compiling, but external BYOK implementations that mock the port wholesale need to accept the extra kwargs.
- ``SpendMeter.charge`` signature gained three keyword-only arguments (``cache_creation_input_tokens``, ``cache_read_input_tokens``, ``provider``). All defaulted — direct callers that already used keyword form are untouched. Test fixtures that mock the meter wholesale needed to add the kwargs.
- ``Cache`` Protocol grew two required methods (``get_bm25_index`` / ``save_bm25_index``). External adapters (none in-tree besides ``SQLiteCache`` and ``InMemoryCache``) must implement the pair to stay Protocol-conformant.
- Pickle is now an in-process dependency for the cache write path. The user-local cache directory means there is no untrusted-deserialization surface, but the schema-version guard + ``rank_bm25`` version guard are needed because pickle is fragile across library upgrades.
- ``_SCHEMA_VERSION`` advanced from 1 to 2 with a real migration check. Older v1 databases pick up the new ``bm25_index`` table on next open, but the migration path is now load-bearing: ``INSERT OR IGNORE INTO schema_version`` is no longer sufficient on its own.

### Neutral

- ADR-0014 §pricing remains accurate for the non-cache cost path. ADR-0020 is unchanged for the regular input/output ratio; the cache multipliers extend it rather than replace it.
- ADR-0016's per-lesson sequential invariant is unaffected — sliding-window compression operates inside a single ``run_agent`` call.
- Future work on cache scope (extending to ``_create_with_retry`` callers above the 1024-token threshold, exploring 1-hour TTL for batched workloads) requires a follow-up ADR amendment.

## Alternatives considered

- **Extend PricingCatalog to a 4-tuple ``(input, output, cache_write, cache_read)``** (rejected in D3). Future-proof for many providers, but a wide BREAKING migration for a feature only two of three advertised providers expose today.
- **Cache `_create_with_retry` system prompts as well** (rejected in D1). Most callers fall below Anthropic's 1024-token threshold; cache markers would be silently ignored, adding bug surface without savings.
- **Token-based sliding window threshold instead of iteration count** (rejected in D6). More dynamic but requires a per-message token estimator the codebase does not currently maintain, with a separate test surface. Iteration count is the right granularity for the multi-agent loop because the budget is also iteration-bounded.
- **Env var only for HTTP timeout** (rejected in D7). Smaller diff but invisible in ``wiedunflow init`` and ``--help``, and not Pydantic-validated. Pre-PyPI window is the right moment to ship a discoverable config field.
- **JSON serialization for the BM25 index** (rejected in D5). Cross-version safer but adds a separate test surface for the ad-hoc reconstruction code, plus numpy array handling. Pickle with a version guard pays the same correctness bill at a fraction of the maintenance cost.
