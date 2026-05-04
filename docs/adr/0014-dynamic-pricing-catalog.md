# ADR-0014: Dynamic pricing catalog — LiteLLM-backed

- **Status**: Accepted
- **Date**: 2026-04-26
- **Deciders**: Michał Kamiński (product owner)
- **Related ADRs**: ADR-0013 (dynamic model catalogs), ADR-0001 (direct SDK)
- **Relates to**: Sprint 9 v0.5.0, US-093 through US-097

## Context

WiedunFlow v0.4.0 introduced the cost-gate prompt (FR-81) and a cost-estimation heuristic that relies on accurate per-model pricing. The cost estimator (`cli/cost_estimator.py`) currently uses a hardcoded `MODEL_PRICES` mapping (`gpt-4.1: 9.0`, `claude-opus-4-7: 45.0` USD/MTok, etc.).

This approach has a critical flaw: **pricing is static but the LLM model ecosystem changes monthly**. New models are released (`gpt-5.4-mini`, `claude-opus-4-8`) and existing model pricing adjusts quarterly. Users who upgrade WiedunFlow without updating their config see a cost estimate frozen at release time, making the cost gate less useful as a real cost-awareness tool.

Additionally, provider SDKs (Anthropic, OpenAI) **do not expose pricing in their `models.list()` responses**. The canonical source of truth for community-maintained model pricing is **LiteLLM's `model_prices_and_context_window.json`** on GitHub (https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json), updated frequently (~3500 models, community-maintained).

## Decision

We introduce a **`PricingCatalog` port** with four implementations and a chained fallback pattern. `httpx` (already required transitively by `anthropic` and `openai`) is promoted to an **explicit hard dependency** because WiedunFlow imports it directly.

1. **`PricingCatalog` Protocol** (`interfaces/pricing_catalog.py`):
   - Single method: `blended_price_per_mtok(model_id: str) -> float | None`
   - Returns blended USD/MTok (60% input + 40% output, empirical planning+narration split)
   - Returns `None` for unknown models so fallbacks can chain
   - Never raises — pricing lookup happens on every estimate and a crash here would block the interactive menu

2. **`StaticPricingCatalog`** (`adapters/static_pricing_catalog.py`):
   - Always-available hardcoded fallback, backed by `cli/cost_estimator.MODEL_PRICES`
   - Single source of maintenance: existing `MODEL_PRICES` dict
   - Used as the leaf of every chain, ensuring cost gate never lacks a price for common models

3. **`LiteLLMPricingCatalog`** (`adapters/litellm_pricing_catalog.py`):
   - Fetches live pricing from LiteLLM's GitHub JSON via `httpx`
   - 3-second HTTP timeout
   - Per-model blending: `0.6 * input_cost_per_token + 0.4 * output_cost_per_token`, converted to USD/MTok
   - Provider-prefix stripping: both `gpt-4.1` and `openai/gpt-4.1` map to the same price
   - Plain `import httpx` at module top — no try/except guard, no `_HTTPX_AVAILABLE` flag (see "httpx as explicit dependency" below)
   - Never raises on HTTP failures (timeout, 5xx, 404, malformed JSON) — all network errors downgrade to an empty cache per process and `None` per query

4. **`CachedPricingCatalog`** (`adapters/cached_pricing_catalog.py`):
   - 24-hour disk cache decorator (mirrors `CachedModelCatalog` from v0.4.0)
   - Cache file: `~/.cache/wiedunflow/pricing-<provider>.json` (e.g. `pricing-litellm.json`)
   - TTL 86400 seconds (24h)
   - `_is_fresh()`: checks file mtime
   - `_read_cache()` / `_write_cache()`: JSON persistence with error handling
   - Works with any upstream catalog that implements `export_dump()` and `hydrate()`

5. **`ChainedPricingCatalog`** (`adapters/cached_pricing_catalog.py`):
   - Falls back to the next catalog when the current one returns `None`
   - Factory build order: `[CachedPricingCatalog(LiteLLM), StaticPricingCatalog()]`
   - Typical flow: live price from cache (or fresh fetch if stale) → static fallback → final `None`

6. **`_build_pricing_chain()` factory** (`cli/main.py`):
   ```python
   return ChainedPricingCatalog(
       [
           CachedPricingCatalog(LiteLLMPricingCatalog(), provider_name="litellm"),
           StaticPricingCatalog(),
       ]
   )
   ```
   - Unconditional — `httpx` is a hard dependency, so `LiteLLMPricingCatalog` is always available
   - Network failures inside `LiteLLMPricingCatalog._ensure_loaded` produce an empty cache (logged as `litellm_pricing_fetch_failed`) and the chain falls through to `StaticPricingCatalog`

## httpx as explicit dependency

- **Declaration**: `httpx>=0.27` lives in `[project.dependencies]` of `pyproject.toml`
- **Why explicit (not transitive)**: `httpx` is already required by `openai` and `anthropic` SDKs (verified via `uv tree`). However, WiedunFlow **imports `httpx` directly** in `litellm_pricing_catalog.py`, so PEP-621 best practice mandates explicit declaration of what we import — relying on transitive availability is brittle (a future SDK release could swap to `aiohttp` and silently break our pricing fetch).
- **Why not optional `[pricing]` extra**: an earlier draft of this ADR proposed `[project.optional-dependencies] pricing = ["httpx>=0.27"]` plus a try/except guard. Smoke testing during integration revealed this was tautological — without `httpx`, `import anthropic` itself fails (anthropic SDK requires `httpx`), so WiedunFlow is unrunnable before the optional code path is even reached. The "graceful fallback when httpx is missing" was therefore **dead code**: the guarded branch could never execute in any supported install. Per the project rule "do not add error handling for scenarios that can't happen" (`CLAUDE.md` SUPPORT_EXPERT, "trust framework guarantees"), the guard, the optional extra, and the two tests covering the impossible state were removed.

## Three-sink rule extension

The existing "three-sink architecture" (ADR-0013) is extended:
- `rich` imports: only in `cli/output.py`
- `questionary` imports: only in `cli/menu.py`
- **NEW**: `httpx` imports: only in `adapters/litellm_pricing_catalog.py` (and `adapters/openai_provider.py`, which uses `httpx` for OSS-endpoint base_url overrides per FR-66 — pre-existing carve-out)

Enforcement: lint test `tests/unit/cli/test_no_httpx_outside_litellm_pricing.py` (clone of `test_no_questionary_outside_menu.py`). Target: 100% green on `ruff check .` and CI.

## Testing strategy

1. **Unit tests** (`tests/unit/adapters/test_litellm_pricing_catalog.py`):
   - Test `_provider_strip()`, `_entry_to_blended_price()`, `_parse_pricing_payload()` with hardcoded JSON payloads
   - Test HTTP failures (monkeypatch `httpx.get` to raise `httpx.ConnectError`, return malformed payload)
   - All should return empty dict or `None`, never raise

2. **Fixture-backed parser tests** (`tests/unit/adapters/test_litellm_pricing_catalog.py`):
   - Real-shape JSON in `tests/unit/adapters/fixtures/litellm_pricing_sample.json` (~10 representative models — Anthropic, OpenAI, Gemini, plus `whisper-1` to verify non-chat skip and `sample_spec` to verify meta-entry skip)
   - `test_fixture_sample_skips_non_chat_and_sample_spec`
   - `test_fixture_prefixed_and_bare_gpt41` — verifies bare-wins-on-collision

3. **Cache decorator tests** (`tests/unit/adapters/test_cached_pricing_catalog.py`):
   - Cold cache → dump; fresh cache → hydrate; stale cache → refetch; corrupt cache → safe fallback
   - `_no_real_network` fixture monkeypatches `httpx.get` to a sentinel that fails the test if hit

4. **Factory wiring test**:
   - `test_build_pricing_chain_wires_litellm_then_static` — asserts the factory returns `[CachedPricingCatalog, StaticPricingCatalog]` in that order

5. **Lint test** (`tests/unit/cli/test_no_httpx_outside_litellm_pricing.py`):
   - Greps `src/wiedunflow/**/*.py` for `import httpx` / `from httpx` outside the two allowlisted files
   - Fails build if found elsewhere

6. **No real network in CI**: all HTTP tests use monkeypatch + fixture JSON. Zero external network calls during the test suite.

## Cache behavior

**24-hour TTL rationale**:
- LiteLLM updates the catalog ~weekly
- 24h window means users get fresh data within one day of a LiteLLM publish
- Balances data freshness against GitHub rate-limit pressure on heavy CI users
- Trade-off: cost estimate the day after a new model release is stale by ~1 day (acceptable)

**Manual refresh**:
- `CachedPricingCatalog.refresh()` clears the disk cache and refetches
- Not exposed on the CLI yet; available for a future menu enhancement (potential "Refresh pricing" option)

## Consequences

**Positive**:
- Cost-gate estimates stay current without WiedunFlow releases
- New models (`gpt-5.4-mini`, `claude-opus-4-8`) are priced accurately once LiteLLM adds them
- Decouples WiedunFlow release cycle from model pricing updates
- Network-failure-tolerant: timeouts, 5xx, malformed JSON all fall through to the static catalog
- Honest dependency declaration — `pyproject.toml` matches what we import

**Negative / costs**:
- One additional explicit dependency in `pyproject.toml` (httpx) — but it was already in the install closure via anthropic/openai
- Adds ~120 LOC of adapter + decorator code
- Introduces network call latency on first price lookup per 24h (mitigated by cache)
- Adds 4 test files (~150 LOC) to maintain

**Risks mitigated**:
- **Network failure**: 3-second timeout, graceful empty-cache return, chain fallback to static
- **Stale data**: 24-hour TTL balances freshness and rate limits
- **Maintenance burden**: centralized `MODEL_PRICES` still used by `StaticPricingCatalog`; when LiteLLM is down, the static catalog kicks in

## Alternatives rejected

1. **`urllib.request` instead of `httpx`**: stdlib but requires custom retry/timeout boilerplate. `httpx` is already in the install closure. Decision: `httpx` wins on code simplicity.

2. **`httpx` as `[project.optional-dependencies] pricing`**: tried in the v0.5.0 draft, removed before release. The optional pattern is meaningless because `anthropic` and `openai` (both hard deps) already require `httpx` — the "without `httpx`" code path can never trigger in any supported install. The try/except guard, the `_HTTPX_AVAILABLE` flag, the factory branch, and two associated tests were all dead code. See "httpx as explicit dependency" above.

3. **Embed a static JSON snapshot in the WiedunFlow repo**: defeats the purpose of dynamic pricing. Requires a release every time LiteLLM updates. Decision: live fetch (with cache + fallback) is better.

4. **Fetch on-demand, no cache**: puts pressure on LiteLLM's GitHub-raw quota. Heavy CI users could hit rate limits. Decision: 24-hour cache is a sweet spot.

## Migration

- **No user-facing breaking changes**. Cost gate behavior is unchanged: users see a USD estimate, and it is now more accurate.
- **No new install instructions**. `uv sync` / `uvx wiedunflow` continues to work as before; `httpx` is pulled automatically.
- **Logging**: `litellm_pricing_fetch_failed` (warn) on network errors, `litellm_pricing_unexpected_shape` (warn) on schema drift. No info-level spam on every lookup.

## Future work

- v0.5.x: optional CLI flag `--refresh-pricing` to force-bust the 24h cache before a run
- v0.6.0: consider switching the LiteLLM source to a lightweight API endpoint instead of the raw GitHub JSON file (when LiteLLM publishes one)
