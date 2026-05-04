# ADR-0020: Per-token pricing in `PricingCatalog`

- **Status**: Accepted
- **Date**: 2026-05-04
- **Deciders**: Michał Kamiński (product owner)
- **Related ADRs**: ADR-0014 (dynamic pricing catalog), ADR-0017 (cost reporting wire-through)
- **Relates to**: v0.9.5

## Context

ADR-0014 introduced `PricingCatalog` with a single method:

```python
def blended_price_per_mtok(self, model_id: str) -> float | None: ...
```

The blended figure was a fixed `0.6 * input + 0.4 * output` weighting — defensible for preflight estimates where the actual input/output token split is unknown, but wrong for **live spend tracking**:

- Output tokens cost **3-5× more than input tokens** at every supported provider (Anthropic 5×, OpenAI 4-6×).
- A typical generation-heavy run produces an input:output ratio closer to **1:5** than the assumed 6:4 (3:2). The Writer/Reviewer agents in particular emit much more than they consume per call.
- The combination meant `SpendMeter` systematically **under-reported actual spend by ~30-60%**. A `--budget 5.00` run could quietly hit `$8.00` of real provider invoice.

LiteLLM's source JSON already separates `input_cost_per_token` and `output_cost_per_token` — we were collapsing the two before charging, throwing away the only information that lets us bill correctly.

## Decision

Replace `blended_price_per_mtok()` with a tuple-returning method:

```python
class PricingCatalog(Protocol):
    def prices_per_mtok(self, model_id: str) -> tuple[float, float] | None:
        """Return (input_per_mtok, output_per_mtok) USD or None."""
```

`SpendMeter.charge()` applies the two rates separately:

```python
cost = (input_tokens * input_price + output_tokens * output_price) / 1_000_000
```

Source of truth for the static fallback (`cost_estimator.MODEL_PRICES`) becomes `dict[str, tuple[float, float]]`. Preflight estimates (`cost_estimator.estimate()`, the cost-gate UI) compose the conventional blended figure on demand via a small `blended_from_prices()` helper — the 0.6/0.4 weighting is preserved where the input/output split is unknown.

Disk cache for `CachedPricingCatalog` serialises tuples as JSON 2-element arrays and reconstructs tuples on read.

## Consequences

**Positive**
- Cost banner and `--budget` cost gate now match provider invoices within ~5% (down from ~30-60% under-report).
- Live spend tracking finally has the information it needs to bill correctly per token class.
- LiteLLM data is no longer collapsed before storage — the catalog preserves the upstream split.

**Negative**
- BREAKING change to the internal `PricingCatalog` Protocol. Four adapters (Static / LiteLLM / Cached / Chained) and one consumer (`SpendMeter`) updated in lockstep. No external implementations are documented; impact is contained.
- `CachedPricingCatalog` JSON cache files written under the old format (single floats) are read as empty and refetched once. TTL-driven, no migration step required.

**Neutral**
- `cost_estimator.lookup_model_price()` keeps its `float` return shape — the preflight stage still reasons in blended terms; only the live meter sees the split.
- `cost_estimator.MODEL_PRICES` keys unchanged; only the value shape changes.

## Alternatives considered

1. **Additive method on the Protocol** (keep `blended_price_per_mtok`, add `prices_per_mtok`). Rejected — leaves a permanent legacy surface in the port for no caller benefit; pre-PyPI window means we can rip the old method without an external migration.
2. **`PriceQuote` dataclass instead of tuple**. Rejected — over-engineering for a 2-element value with universally clear semantics; tuple JSON-serialises trivially via `[input, output]` arrays.
3. **Decimal arithmetic across `SpendMeter`**. Rejected — `total_cost_usd` is a display-and-budget figure, not a billing ledger; float precision over `[$0, $50]` is sufficient.

## Refines

ADR-0014 §pricing — the catalog infrastructure (chain layout, LiteLLM source, 24h cache) is unchanged; only the resolution model (single blended → tuple) is refined.
