# ADR-0001: LLM stack — direct SDK over LangChain/LangGraph

- Status: Accepted
- Date: 2026-04-16
- Deciders: Michał Kamiński
- Related PRD: v0.1.1-draft
- Supersedes: none

## Context

PRD 0.1.0-draft specified LangGraph as the orchestration framework and LangChain providers (`langchain-anthropic`, `langchain-openai`, `ChatOpenAI` with `base_url` override for OSS endpoints) for LLM calls.

Critical review of the tech stack against the PRD surfaced three concerns:

1. **Pipeline shape** — the WiedunFlow generation loop is linear: for each lesson in `lesson_manifest`, call the narration LLM, validate grounding, checkpoint, continue. There is no agentic branching, no dynamic tool selection, no multi-agent coordination. LangGraph's state-machine runtime is designed for exactly those use cases and adds overhead without payoff for a linear pipeline.
2. **Maintenance cost** — LangChain and LangGraph have a history of frequent breaking changes (module relocations, API renames, state-shape migrations) on a roughly quarterly cadence. For a single-maintainer project (MVP is author + two trusted reviewers) this cadence is a non-trivial tax. LangChain has also had multiple CVEs (prompt injection via tool descriptions, pickle deserialization in document loaders) — carrying LangChain in the dependency graph widens the attack surface even if we never use the affected loaders.
3. **Provider fidelity** — provider-specific features (Anthropic tool use semantics, OpenAI structured outputs, reasoning fields for OpenRouter/DeepSeek) lag in LangChain. Calling the official SDKs directly is more faithful to each provider's current capabilities.

## Decision

Remove LangChain and LangGraph from MVP. Replace with:

- **Port**: `LLMProvider` in `interfaces/ports.py` — minimal abstraction with `complete(messages, model, max_tokens)` and `count_tokens(...)`.
- **Adapters** in `adapters/`:
  - `AnthropicProvider` — uses the official `anthropic` Python SDK. Default models: `claude-haiku-4-5` (descriptions, parallel) and `claude-opus-4-7` (narration, sequential).
  - `OpenAIProvider` — uses the official `openai` Python SDK.
  - `OpenAICompatibleProvider` — `httpx`-based client for Ollama / LM Studio / vLLM, accepts `base_url` override.
- **Orchestration** — own `use_cases/generate_tutorial.py` implementing the 7-stage pipeline. Checkpointing is one SQLite row per completed lesson, with the same state shape (`{explored_symbols, lessons_generated, concepts_introduced}`) that LangGraph would have carried.
- **Validation** — `pydantic.BaseModel` on `lesson_manifest` and `code_refs[]`. Providers that expose a JSON-schema response format (Anthropic, OpenAI) use it; otherwise we parse + validate after the call.

## Consequences

**Positive**:

- ~30% reduction in dependency surface (LangChain pulls ~40 transitive packages).
- Fewer CVE exposures — LangChain is a large attack surface we do not benefit from.
- Easier testing — a single `FakeLLMProvider` implementing one port replaces mocking across LangChain's class hierarchy.
- Faster adoption of provider-native features without waiting for LangChain updates.
- Deterministic test runs — no dependence on LangChain's internal state handling.

**Negative**:

- We own ~200–300 lines of orchestration code that LangGraph would have provided.
- Provider-specific mapping (tool use schemas, system prompts, streaming) is manual per adapter.
- We forgo LangChain's ready-made integrations (retrievers, memory, output parsers) — acceptable because RAG in MVP is BM25 (ADR-0002) and output parsing is a single `pydantic` model.

## Alternatives Considered

1. **Keep `langchain-core` only for message types** — rejected because `langchain-core` still couples us to LangChain's versioning cadence without meaningfully simplifying our code.
2. **Use `instructor` for structured outputs** — attractive (Pydantic-first structured responses over any SDK), but we only need structured responses in 2 places (`lesson_manifest`, lesson narration). A dedicated library for two call sites is not worth the dependency.
3. **Use LangGraph but not LangChain providers** — rejected. LangGraph's value is agentic graphs; we have a linear pipeline. Carrying the runtime without the graph is pure overhead.

## Migration Criteria (reconsidering LangChain in v2+)

Revisit this decision if **any** of the following becomes true:

- We add agentic branching (e.g., a "decide whether to deep-dive on this subsystem" step).
- We add dynamic tool-calling to lesson generation (e.g., the model chooses which ASTs to fetch).
- We grow beyond 5 LLM providers and the per-adapter code starts to exceed 100 lines.
- We need memory or retrieval primitives (e.g., conversational state across sessions) that LangChain provides out of the box.

Until any of these triggers, the direct-SDK approach stays.

## References

- PRD v0.1.1-draft, §1 (Product Overview), FR-64, FR-65, FR-66
- tech-stack.md §7 (Orkiestracja LLM)
- CLAUDE.md sections STACK, LLM_ORCHESTRATION
