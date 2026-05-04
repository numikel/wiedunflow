# ADR-0015: Default LLM Provider Switch from Anthropic to OpenAI

- **Status**: Accepted
- **Date**: 2026-04-26
- **Deciders**: Michał Kamiński (product owner)
- **Related ADRs**: ADR-0001 (LLM stack), ADR-0013 (dynamic model catalogs), ADR-0014 (dynamic pricing catalog)
- **Relates to**: Sprint 13 v0.7.0

## Context

WiedunFlow adopted Anthropic as the default LLM provider at inception (ADR-0001, 2026-04-16). The pipeline uses `claude-haiku-4-5` for per-symbol leaf descriptions (parallel) and `claude-opus-4-7` for lesson narration (sequential, carrying `concepts_introduced`).

However, user experience with Anthropic has surfaced a critical pain point: **rate-limit friction (HTTP 429)** during high-throughput runs (concurrent symbol descriptions) and eval gate execution (5-repository smoke test). The 429 errors create frustration despite exponential backoff (ADR-0013); users perceive the tool as unreliable when hitting rate limits repeatedly.

Simultaneously, the **GPT-5.4 family** (released March 2026) has become competitive with Claude on code-narration quality metrics:
- Pricing alignment: `gpt-5.4` blended ~$7.50/MTok vs `claude-opus-4-7` ~$15/MTok (50% cheaper for planning + narration combined)
- Accuracy on narrative tasks comparable to Sonnet 4.6 in preliminary benchmarks
- Wider ecosystem distribution — more developers have OpenAI keys than Anthropic

The Bring-Your-Own-Key architecture (ADR-0001 port `LLMProvider`) remains intact; Anthropic stays fully supported as an alternative. This decision is purely a **default swap**, not a deprecation.

## Decision

We switch the default LLM provider from **Anthropic to OpenAI**, effective v0.7.0:

### 1. Model routing (new defaults)

- **Planning (Stage 4)**: `gpt-5.4` (replaced `claude-sonnet-4-6`)
- **Narration (Stage 5/6)**: `gpt-5.4` (replaced `claude-opus-4-7`)
- **Per-symbol describe (Stage 5, parallel)**: `gpt-5.4-mini` (replaced `claude-haiku-4-5`)

Rationale for gpt-5.4 + gpt-5.4-mini tier:
- Unified smaller-to-medium model family reduces provider account complexity
- gpt-5.4-mini cheaper than Haiku 4.5 in some concurrent workloads (empirical data pending eval gate validation)
- OpenAI's faster batch processing and per-token pricing transparency align with cost-gate UX

### 2. Affected configuration fields

**`WiedunflowConfig` model defaults** (in `cli/config.py`, fields `llm.*`):

```python
llm:
  provider: "openai"  # was "anthropic"
  model_plan: "gpt-5.4"  # was "claude-sonnet-4-6"
  model_narrate: "gpt-5.4"  # was "claude-opus-4-7"
```

**OpenAI provider class** (in `adapters/openai_provider.py`):

```python
class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str | None = None,
        model_plan: str = "gpt-5.4",  # was "gpt-4o"
        model_narrate: str = "gpt-5.4",  # was "gpt-4o"
        model_describe: str = "gpt-5.4-mini",  # was "gpt-4o-mini" (Stage 5 leaf descriptions, parallel)
        ...
    ):
```

### 3. Cost estimator update

Pricing in `cli/cost_estimator.MODEL_PRICES` updated from hypothetical March estimates to verified current rates:

```python
MODEL_PRICES = {
    "gpt-5.4": 7.50,  # USD/MTok blended (60% input @ $2.50 + 40% output @ $15.00)
    "gpt-5.4-mini": 2.25,  # USD/MTok blended (60% input @ $0.75 + 40% output @ $4.50)
    "gpt-5.4-pro": 90.00,  # USD/MTok blended (planning-only tier, rarely used)
    # ... Anthropic models retained for BYOK
    "claude-sonnet-4-6": 6.00,
    "claude-opus-4-7": 15.00,
    "claude-haiku-4-5": 0.80,
}
```

### 4. Env var convention

Default expected env var changes from `ANTHROPIC_API_KEY` to `OPENAI_API_KEY`.

Error message on missing key: `"OpenAI API key not found. Set OPENAI_API_KEY or use --provider anthropic with ANTHROPIC_API_KEY."`

### 5. BYOK Anthropic unchanged

- Setting `llm.provider: anthropic` in `tutorial.config.yaml` (or env `WIEDUNFLOW_LLM_PROVIDER=anthropic`) routes all calls through `AnthropicProvider`, using `claude-sonnet-4-6` / `claude-opus-4-7` / `claude-haiku-4-5` defaults as before.
- No adapter code removed; zero breaking changes to the provider port contract.
- All 4 providers (anthropic/openai/openai_compatible/custom) function identically post-switch.

## Rationale

### Why switch defaults (not stay on Anthropic)?

1. **Rate-limit user pain** — Heavy concurrent loads (10+ parallel symbol descriptions) hit Anthropic's per-minute token limits. Exponential backoff (ADR-0013) mitigates but does not eliminate the problem. OpenAI's rate tiers are more generous for the target concurrency (10–20).

2. **Cost reduction** — gpt-5.4 family 50% cheaper than Opus for planning+narration combined ($7.50 vs $15/MTok blended). Widened cost-gate acceptability for user budgets.

3. **Ecosystem alignment** — Broader developer familiarity with OpenAI (ChatGPT, Copilot) vs. Anthropic. BYOK tooling (LiteLLM in ADR-0014) auto-discovers OpenAI models natively.

4. **Narrative quality parity** — Preliminary benchmarks on v0.7.0 eval corpus (5 pinned repos) show gpt-5.4 within 1–2 quality points of Sonnet 4.6 on narrative coherence, grounding accuracy, and word-count compliance.

### Why not other alternatives?

- **A) Stay on Anthropic + switch to Haiku 4.5 for planning/narration** — Reduces rate limits only marginally; quality drop for narration (Haiku is single-call only, no prior-lesson context). Rejected.
- **B) Multi-provider routing (Anthropic for planning, OpenAI for narration)** — Adds complexity; consent banner twice; user confusion. Rejected.
- **C) Add new field `llm.model_describe` to config** — Allows per-symbol override in v0.7.0. Rejected for v0.7.0 (scope creep); filed as follow-up for v0.8.0+ when TUI menu redesign covers per-stage model selection.

## Consequences

### Positive

- **Rate-limit relief** — Users hitting heavy concurrent loads no longer experience repeated 429 backoff cycles.
- **Cost savings** — Typical tutorial generation drops from ~$5–8 to ~$4–6 (gpt-5.4-mini for 10% of token spend, gpt-5.4 for 90%).
- **Ecosystem clarity** — Most developers have `OPENAI_API_KEY` set (ChatGPT, GitHub Copilot, other tooling). Reduces onboarding friction for new users.
- **LiteLLM integration** — Dynamic pricing catalog (ADR-0014) natively discovers gpt-5.4 family; no manual model_prices update needed when OpenAI releases gpt-5.5, gpt-6, etc.
- **Decouples version cycle** — Model performance and pricing updates no longer blocked by WiedunFlow releases; live via LiteLLM catalog.

### Negative / costs

- **BREAKING change for users relying on implicit Anthropic default** — Existing installations with `ANTHROPIC_API_KEY` set and no explicit config will fail on first v0.7.0 run with "OpenAI API key not found" error. Mitigation: clear error message + docs.
- **Abandons existing eval baseline (v0.6.0)** — Quality rubric for v0.1.0 release gate was signed off on Anthropic models. v0.7.0 eval gate requires re-sign-off with OpenAI defaults. (Pragmatic: eval corpus is pinned; new baseline measured within same 5 repos + same grounding standards.)
- **Adds dependency on OpenAI availability** — If OpenAI experiences extended outage, default path blocked. Anthropic BYOK remains as fallback (documented in README).

### Risks mitigated

- **Provider lock-in**: BYOK contract in place; users can opt-out with one-line config.
- **Cost surprises**: Dynamic pricing catalog (ADR-0014) keeps cost-gate accurate; if OpenAI raises rates, estimates auto-update within 24h.
- **Narrative quality regression**: Eval gate (v0.7.0) runs full 5-repo corpus; grounding validation unchanged; if gpt-5.4 underperforms, rollback available.

## Migration path

### For existing users

**Pre-upgrade**: v0.6.0 or earlier with `ANTHROPIC_API_KEY` set, no explicit provider config.

**On upgrade to v0.7.0**:
1. User runs `wiedunflow generate /path/to/repo` → error: `"OpenAI API key not found. Set OPENAI_API_KEY or use --provider anthropic with ANTHROPIC_API_KEY."`
2. **Option A (recommended)** — Set `OPENAI_API_KEY` and retry. Cost-effective path.
3. **Option B (preserve Anthropic)** — Run `wiedunflow init --provider anthropic` → wizard prompts for Anthropic key → config updated to explicit `llm.provider: anthropic`.
4. **Option C (direct config edit)** — Edit `~/.config/wiedunflow/config.yaml` (or `./tutorial.config.yaml`): add `llm: { provider: anthropic }`.

### For CI / scripted usage

```bash
# v0.6.0 (Anthropic implicit)
ANTHROPIC_API_KEY=sk-ant-... wiedunflow generate repo --yes

# v0.7.0 (OpenAI explicit)
OPENAI_API_KEY=sk-... wiedunflow generate repo --yes
# or
ANTHROPIC_API_KEY=sk-ant-... WIEDUNFLOW_LLM_PROVIDER=anthropic wiedunflow generate repo --yes
```

### Documentation updates required

- **README.md**: change quick-start env var from `ANTHROPIC_API_KEY=sk-ant-...` to `OPENAI_API_KEY=sk-...`. Add "Alternatively, BYOK Anthropic: ..." box.
- **CLAUDE.md (project)**: update `## LLM_ORCHESTRATION` section; add note on Anthropic BYOK with env var override.
- **tutorial.config.yaml.example**: document `llm.provider: openai` as default; show Anthropic override.
- **CHANGELOG.md**: `## [0.7.0]` section with BREAKING note + migration guidance.

## Relationship to other ADRs

- **ADR-0001**: Retains BYOK contract; provider port `LLMProvider` unchanged. Decision within ADR-0001's scope ("provider-specific fields like DeepSeek reasoning → v2" applies here; we stay within SDK v1 contracts).
- **ADR-0013**: Dynamic model catalogs inherit gpt-5.4 family as defaults; TUI menu picker (Generate sub-wizard) now shows gpt-5.4 as default option, with full list from ModelCatalog port.
- **ADR-0014**: PricingCatalog auto-discovers gpt-5.4 models from LiteLLM; cost-gate estimates improve in real time.

## Supersedes / amendments

**Partial supersede**: ADR-0001, decision point "Anthropic SDK (default)". ADR-0001 remains in force for "no LangChain + direct SDK + port-based architecture"; only the default provider enum value changes from `"anthropic"` to `"openai"`.

## Future work

- **v0.8.0+**: Add `llm.model_describe` field to `WiedunflowConfig` and TUI menu (per-stage model picker). Enables power users to swap descriptions tier (e.g., gpt-5.4-mini → gpt-5.4 for higher quality at higher cost) without code changes.
- **v0.8.0+**: Eval gate extended to compare gpt-5.4 vs gpt-4o-mini quality and cost efficiency. Decision on tier split between planning/narration/describe refined post-data.
- **v1.0.0**: If OpenAI rate limits remain an issue at scale, consider provider fallback chain (primary OpenAI → fallback Anthropic on 429) as opt-in config.

## References

- Pricing verified from OpenAI API docs (2026-03) and LiteLLM catalog snapshot
- Quality metrics: internal eval v0.7.0 release gate (5-repo corpus, 3-point rubric on coverage/accuracy/flow)
- User feedback: v0.6.0 post-release survey + support channel rate-limit complaints
