# ADR-0006: AST snapshot schema — grounding contract for Stage 1-3

- Status: Accepted
- Date: 2026-04-20
- Deciders: Michał Kamiński
- Related PRD: v0.1.2-draft
- Supersedes: none

## Context

Sprint 2 introduces the first real AST snapshot produced by the pipeline:
`(IngestionResult, CallGraph, RankedGraph)`.  This triple is the single
source of truth that downstream stages (Stage 4 RAG, Stage 5 planning,
Stage 6 generation) ground every lesson against.

Without a stable schema, the Sprint 4 grounding validator has no contract to
assert against — a hallucinated symbol from the planning prompt is
indistinguishable from a resolution gap, and re-running the pipeline would
silently drift because the invariants are implicit in adapter code.

The grounding rule from `CLAUDE.md` is non-negotiable:

> Every function/class/module name referenced in an LLM-generated lesson
> must exist in the AST snapshot from Stage 1.  Post-hoc validation in the
> entities layer rejects any lesson that references a non-existent symbol.

For that rule to be enforceable, the snapshot schema itself must be:

1. Versioned (so cache invalidation can detect forward-incompatible changes).
2. JSON-serializable (so it can be cached to SQLite and replayed).
3. Invariant-checked at construction time (so inconsistent snapshots fail
   fast rather than corrupting downstream stages).

## Decision

The **AST snapshot** is defined as the triple:

```python
(IngestionResult, CallGraph, RankedGraph)
```

all three being frozen Pydantic v2 models with the following invariants
enforced via `@model_validator(mode="after")`:

### `IngestionResult`

- `commit_hash` is non-empty (fallback: `"unknown"` for non-git directories).
- `branch` is non-empty (fallback: `"unknown"`).
- `detected_subtree` (when not `None`) resolves under `repo_root`.
- `excluded_count >= 0`.
- `files` is a tuple of `Path` — order is NOT part of the contract.

### `CallGraph` (post-resolver)

- `nodes` is a tuple of `CodeSymbol` — unique by `name`.
- Every `edge = (caller, callee)` references names present in `nodes`.
  (This invariant is enforced ONLY when `resolution_stats is not None` —
  the raw graph emitted by the parser is allowed to carry textual callees
  that the resolver prunes.)
- `resolution_stats is not None` for any snapshot consumed by Stage 3+.

### `RankedGraph`

- Every name in `topological_order` appears in `ranked_symbols`.
- Every name in every community appears in `ranked_symbols`.
- `has_cycles == bool(cycle_groups)` (consistency between the two fields).
- `community_id >= 0` for every `RankedSymbol`.
- Topological order respects strongly-connected-component condensation —
  cyclic components appear together, ordered by PageRank inside the SCC.

### Uncertainty propagation

A symbol is **not groundable** (i.e. may not be referenced by downstream
grounding checks as a "known static symbol") when any of the following hold:

- `CodeSymbol.is_dynamic_import is True` — source file contains
  `importlib.import_module`, `__import__`, `globals()[...]`, `getattr(...)`,
  or equivalent dynamic dispatch.
- `CodeSymbol.is_uncertain is True` — Jedi resolved the reference but did
  not attach a `full_name`.
- The symbol name appears in a `cycle_group` — cyclic edges are surfaced
  to the narrator but must be labelled "interdependent modules", never
  presented as a strict caller→callee narrative.

### `ResolutionStats`

Always computed post-resolver; `resolved_pct` lives in `[0.0, 100.0]`.
`resolved_pct < 50.0` emits a structlog warning (informational — does not
fail the build in Sprint 2; may gate release in a later sprint).

## Consequences

### Positive

- The Sprint 4 grounding validator can assert `lesson.symbol_ref in
  {s.name for s in snapshot.symbols}` without additional plumbing.
- Cache invalidation is trivial: the snapshot's `commit_hash` + schema
  version = cache key.
- Snapshot replay is deterministic — invariants reject inconsistent
  hand-edited cache files at load time.
- Every invariant has a matching unit test in `tests/unit/entities/`.

### Negative / trade-offs

- Tight coupling between adapter outputs and entity invariants: a
  change to `Resolver.resolve` that introduces an unknown edge trips
  the validator immediately.  This is a feature, not a bug — but it
  means adapter authors must honour the contract or the pipeline
  halts at the entity boundary.
- The invariants run on every `CallGraph` / `RankedGraph` construction.
  For very large graphs this may add overhead; will revisit if profiling
  shows it.

### Neutral

- Schema version is implicit in `pyproject.toml`'s project version for
  MVP — a forward-incompatible snapshot change requires a version bump.
  A dedicated `schema_version` field on the entities may land later.

## Alternatives considered

- **Loose snapshots (validate only in the grounding validator)** —
  rejected: pushes invariant checks too far downstream; the cost of
  a malformed snapshot is measured in tokens, not just test failures.
- **Protobuf / Cap'n Proto schema** — rejected for MVP; Pydantic v2
  frozen models are sufficient, cheaper to maintain, and integrate
  directly with the existing entity layer.
- **Separate `SnapshotEnvelope` wrapper** — deferred; the triple of
  models is expressive enough for v0.0.2, and the caching layer (v0.1+)
  can introduce an envelope without breaking this ADR.
