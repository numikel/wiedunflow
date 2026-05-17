# ADR-0023: Performance and cost tuning wave (v0.12.0)

- **Status**: Accepted
- **Date**: 2026-05-17
- **Deciders**: Michał Kamiński (product owner)
- **Related ADRs**: ADR-0008 (cache schema), ADR-0016 (multi-agent narration), ADR-0018 (jedi heuristic fallback), ADR-0020 (per-token pricing), ADR-0021 (cache, history, timeout policy)
- **Relates to**: v0.12.0

## Context

After ADR-0021 closed the prompt caching and history bounding gaps in v0.11.0, ten distinct performance and cost regressions remained visible across the seven pipeline stages. They span the static-analysis path (Stages 1–3), the LLM orchestration path (Stages 4–6), and the build path (Stage 7), and individually are too small for a dedicated ADR but together account for a significant share of cold-start wall-clock and per-run dollar spend.

This ADR records the eleven binary decisions taken to address all ten regressions together in v0.12.0, plus one validation-tooling decision. Decisions are grouped by pipeline stage.

## Decisions

### Static analysis (Stages 1–3)

#### D1 — Eliminate the second `jedi.Script` per unresolved edge

`JediResolver._classify_edge` previously constructed a second `jedi.Script` for every Tier-1 miss to distinguish *uncertain* from *unresolved* outcomes. On a cold-start medium repo with a ~60% Tier-1 miss rate this doubled the `jedi.Script` count, and Script construction dominates Stage 2 cost.

`_resolve_single_edge` now returns a `_ResolveOutcome` NamedTuple carrying the state (`resolved` / `uncertain` / `unresolved` / `empty`) and any inferred names. The classifier becomes a thin dispatch on `outcome.state`. Single Script per `(caller_path, source)` pair.

Alternatives rejected: caching `jedi.Script` instances inside `source_cache` would hold parser state for the duration of the resolve loop and inflate RAM for large repos; the enum refactor is RAM-neutral.

#### D2 — NumPy dense matrix PageRank

`_pagerank_power` was pure-Python power iteration with an O(V × E) inner loop. NetworkX 3.6+ ships `nx.pagerank()` against `scipy.sparse`, which would be ~100–1000× faster on the same problem, but adding scipy as a hard dependency would inflate the wheel by ~30 MB and broaden the attack surface unnecessarily for the size of graphs this tool handles (≤5 000 nodes capped by `max_lessons` × symbol fan-out).

The replacement builds a column-stochastic adjacency matrix `M` from the digraph and reduces each iteration to `v_new = alpha * (M @ v) + teleport`. NumPy is already a hard dependency. For 1 000-node graphs the dense matrix is ~8 MB RAM, well within budget. Determinism is preserved by stable `list(digraph.nodes())` ordering; existing golden-file tests pass at the same `1e-6` tolerance.

#### D3 — Strongly-connected-components fast-path before `simple_cycles`

`nx.simple_cycles()` is O(V + E + simple_cycles_count) and dominates Stage 3 on dense graphs. Real Python repositories overwhelmingly produce DAGs, so the cycle enumeration is wasted on the typical run. The ranker now calls `nx.number_strongly_connected_components(digraph)` first (O(V + E)) and skips `simple_cycles()` when every SCC is trivial (one node per component, no self-loops). The returned `RankedGraph` reports `has_cycles=False, cycle_groups=()` in that case.

#### D4 — Ingestion `rglob("*.py")` pre-filter

`_collect_files` walked `repo_root.rglob("*")` and applied the `.py` suffix gate after the pathspec and hard-refuse filters. On monorepos this stat'd 10 000+ non-Python files for nothing. The walk now uses `rglob("*.py")` and the redundant suffix check is removed. The `__pycache__` and dot-directory guards stay.

#### D5 — Outline edge cap with PageRank ranking

`build_outline` appended every call edge unconditionally. A medium repo (300 symbols, ~2–5 000 edges) consumed 40–60% of the planning context window on edges alone. A new config field `planning.max_outline_edges` (default 200) caps the list; edges are sorted descending by the sum of caller + callee PageRank so structurally important call paths win. Setting the field to 0 disables the cap (v0.11.x back-compat).

Alternatives rejected: filtering to the top 50% of PageRank nodes produced unpredictable list sizes (dependent on PageRank dispersion) and was harder to test; edge-weight ranking required call-frequency data the call graph does not yet carry.

### LLM orchestration (Stages 4–6)

#### D6 — Research notes truncation policy

`_run_writer` and `_run_reviewer` concatenated all researcher snapshots with no length cap. Five researcher iterations ≈ 40 KB of input vs the 4 KB Writer output ceiling — a 3:1 input/output ratio that wasted tokens and hurt prompt cache hit rates.

The orchestrator now applies a three-tier policy:

1. Concat ≤ `narration.research_notes_cap_kb` (default 20 KB) → pass through unchanged.
2. Concat ≤ `narration.research_notes_summarize_threshold_kb` (default 30 KB) → FIFO drop the oldest snapshots until under the cap.
3. Concat > threshold → route through a single mini-model summarize call with a tight system prompt ("Summarize these researcher notes for a tutorial Writer. Preserve symbol names verbatim. Target 4 KB."). On summarize failure → silently fall back to FIFO drop.

The summarize model is configurable via `narration.summarize_model`; null/empty reuses the researcher model on the same provider so BYOK (Ollama/LM Studio/vLLM) users stay on a single endpoint by default. The decision logs at INFO when summarize fires and at WARNING on fallback so cost surprises are observable.

Alternatives rejected: hard cap only would silently drop research signal when truncation triggers; summarize-only was rejected as too much surface area for a feature firing only on outlier runs.

#### D7 — Planning retry slim message

`_build_reinforcement` rebuilt the original outline + reinforcement on every retry. With a 30–50 KB outline and three attempts, retries shipped 90–150 KB of redundant context.

Attempts ≥ 1 now return a slim message: `"PREVIOUS ATTEMPT FAILED ({attempt}/3): {last_error}\nInvalid symbols cited: {invalid_symbols[:10]}\nAllowed symbols (top by PageRank): {allowed_symbols[:20]}\nRetry with valid symbols only."`. The original outline was already in the prompt cache from attempt 0; the cache hit covers re-grounding without re-sending. Attempt 0 still receives the full outline.

Alternatives rejected: a full multi-turn refactor (converting `plan_lesson_manifest` to use `LLMProvider.run_agent` with conversation history) would have required a BREAKING change to the Protocol — too much blast radius for the same effective saving.

#### D8 — `run_agent` inner-call retry coverage

`_create_with_retry` previously protected only the single-shot helpers (`plan()`, legacy `narrate()`). The agent loop body called the SDK bare. A single 429 or 5xx mid-Orchestrator killed the entire lesson.

Both adapters now route the inner agent-loop SDK call through the existing retry wrapper. Anthropic's `retry_if_exception_type` is extended from `RateLimitError` only to `(RateLimitError, InternalServerError, APIConnectionError)` — the OpenAI counterpart already covered the full set on single-shot helpers and just needed the wrap.

### Build path (Stage 7)

#### D9 — SQLite cache PRAGMA tuning

`SQLiteCache.__init__` opened WAL mode but inherited `synchronous=FULL` (fsync on every commit) and the default 2 MB page cache. For TEXT blob lesson payloads this is conservative beyond the durability needs of a regenerable cache.

Three new PRAGMAs run after `journal_mode=WAL`:

- `synchronous=NORMAL` — WAL + NORMAL is durable against process crash; only a power loss can drop the last commit, and the cache is rebuildable.
- `cache_size=-32000` — 32 MB page cache fits the typical working set of lesson payloads in RAM.
- `temp_store=MEMORY` — in-memory scratch for sort/join operations.

Combined effect: lesson-checkpoint writes commit in a fraction of the prior fsync time, with no change to the data-correctness contract.

#### D10 — Pygments per-block tokenisation

`highlight_python(code: str) -> str` was called per line in two places in `jinja_renderer`. Per-line tokenisation loses cross-line token context — multi-line strings, block comments, and triple-quoted docstrings rendered as broken fragments. Each call also instantiated a fresh `PythonLexer` and `WiedunFlowHtmlFormatter`, paying ~1 ms of regex compilation overhead per line (60 lines = 60 instantiations).

`highlight_python_lines(lines: list[str]) -> list[str]` is the replacement. It joins lines with `\n`, tokenises the whole block in one Pygments pass, strips Pygments' trailing newline, and splits the resulting HTML on `\n`. `PythonLexer` and `WiedunFlowHtmlFormatter` are module-level singletons. Empty input returns `[]` without invoking Pygments.

This is a **BREAKING** internal API change. The Jinja renderer is updated in the same release; external callers that imported `highlight_python` must switch to the new signature.

#### D11 — Validation tooling for the cost estimator

The cost estimator was rewritten in v0.10.0 to model the v0.9.0+ multi-agent pipeline with per-role token ceilings (ADR-0016 amendment). The estimator constants are conservative but never validated against real spend.

A new `scripts/validate_cost_estimator.py` parses the per-lesson transcripts written under `~/.wiedunflow/runs/<run_id>/transcript/`, aggregates token usage by role (Planning / Orchestrator / Researcher / Writer / Reviewer), and prints a five-row delta table against `cost_estimator.estimate()`. The script exits 0 when all per-role deltas are within ±50% and 1 otherwise (warning, not CI gate). The parser function `parse_run_dir()` is exposed so the synthetic-transcript unit test can import it directly.

This is research tooling; the estimator constants stay unchanged in v0.12.0. The script is meant to surface drift between preflight estimates and actual spend so future tuning is grounded in production data.

## Consequences

### Positive

- Stage 2 cold-start wall-clock drops by ~30–50% on the typical cold-start repo (jedi double Script eliminated).
- Stage 3 PageRank phase drops by >50× on 500-node graphs (NumPy matrix ops).
- Stage 1 stat syscalls drop from O(all files) to O(.py files) — typically 10–30× reduction on monorepos.
- Stage 4 planning prompt fits inside a smaller, deterministic context window.
- Stages 5/6 per-lesson input drops ~30% on the typical run (research notes truncation).
- Stages 5/6 retry path drops 80–90% of redundant context (planning reinforcement slim).
- Lesson generation survives transient cloud provider hiccups inside the agent loop.
- SQLite checkpoint writes complete several times faster on Windows/SSD; large incremental runs feel snappy again.
- Multi-line code snippets render with correct token classes for the first time.

### Negative

- `highlight_python` removal is a BREAKING internal API change. The only internal caller (Jinja renderer) is updated in the same release; documentation is the only external surface.
- New config fields (`planning.max_outline_edges`, `narration.research_notes_cap_kb`, `narration.research_notes_summarize_threshold_kb`, `narration.summarize_model`) increase the schema surface. All four have safe defaults — existing `tutorial.config.yaml` files keep working without modification.
- The optional summarize call (when concat > threshold) adds latency and a tiny cost on outlier runs. Both are observable in the structured logs.
- The validation script is not part of the CI gate; estimator drift can still ship without triggering a failure. The decision was deliberate — research tooling first, gating second.

### Neutral

- NumPy was already a hard dependency. No wheel size impact.
- The summarize model defaults to the researcher model, so single-endpoint BYOK users see no new provider configuration.
- All existing tests pass without modification (1 416 passed, 17 skipped on Windows). The W4 wave added ~50 new tests across 8 files covering the new behaviour.
