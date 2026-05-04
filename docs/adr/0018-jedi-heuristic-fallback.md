# ADR-0018: Jedi heuristic call graph fallback (Tier 2)

- **Status**: Accepted
- **Date**: 2026-05-02
- **Deciders**: Michał Kamiński (product owner)
- **Related ADRs**: ADR-0006 (AST snapshot schema), ADR-0007 (planning prompt contract), ADR-0016 (multi-agent narration)
- **Relates to**: v0.9.0

## Context

In the 5-repo eval corpus (v0.8.0 sprint), Jedi `infer()` returned empty results for a
significant fraction of call edges — particularly across package boundaries, in repos
without a populated `.venv/` (cold install), and for dynamically constructed call
targets. An empty `infer()` result was previously treated as `UNRESOLVED`, leaving the
call graph sparse and reducing PageRank signal quality for the planning stage.

The eval baseline showed Jedi strict resolution at ~9.9% on `python-sdk-mcp` (src-layout
repo without pre-installed venv) — well below what is achievable when the call graph is
fully populated.

## Decision

Two-tier improvement in `src/wiedunflow/adapters/jedi_resolver.py`:

### Tier 1 — venv auto-detection

`_detect_python_path(repo_root, override)` searches in priority order:

1. `.venv/Scripts/python.exe` (Windows) → `.venv/bin/python` (Unix)
2. `venv/Scripts/python.exe` → `venv/bin/python`
3. `env/Scripts/python.exe` → `env/bin/python`
4. System Python (current process `sys.executable`)

Exposed via:
- `--python-path PATH` — explicit override flag on `wiedunflow generate`.
- `--bootstrap-venv` — opt-in `uv sync --no-dev` before Stage 2 to populate `.venv/`
  for repos that don't ship one.

### Tier 2 — heuristic last-component name match

When `infer()` returns empty (after Tier 1 has set the project path), `_heuristic_name_match()`
performs a lookup in `AST.symbol_by_name` using the last component of the call expression.

Outcomes:
- **Exactly one match** → `RESOLVED_HEURISTIC` tag (treated like `RESOLVED` for graph
  edges, but separately tracked in stats).
- **Multiple matches** → `UNCERTAIN` with `candidates: list[str]` (excluded from edges,
  surfaced in audit output).
- **Zero matches** → `UNRESOLVED` (status quo).

`ResolutionStats` gains:
- `resolved_heuristic_count: int` — new field.
- `resolved_pct_with_heuristic` — computed property combining strict + heuristic.

Strict `resolved_pct` is unchanged — backward compatible with v0.8.0 serialised stats.

## Consequences

### Positive
- Eval corpus recovered 27 previously-unresolved edges as `RESOLVED_HEURISTIC` on
  `python-sdk-mcp`; overall resolution including heuristic reached ~18% — close to a
  2× improvement.
- Cross-package calls in repos without pre-installed venvs now contribute to the
  PageRank graph, improving lesson selection quality.
- `--python-path` and `--bootstrap-venv` give power users explicit control without
  forcing a default behaviour change.

### Negative
- Heuristic matches are not guaranteed correct — ambiguous symbols tagged `UNCERTAIN`
  may generate cautious narration ("this dispatch happens at runtime"). False positives
  (single match that is the wrong symbol) are possible but bounded by the
  `cited_symbols ⊂ research_notes` check in the multi-agent Writer's `submit_lesson_draft`
  structured output validation (ADR-0016).
- Adds two new CLI flags and one new stats field — minor schema growth.

## Alternatives Considered

**1. Full LSP integration (pyright / pylance)** — Deferred to v2 per ADR-0001 framing.
Scope is too large for MVP and would add a subprocess dependency.

**2. Skip heuristic, document Jedi limitations in narration** — Rejected: the planning
stage relies on PageRank signal quality; sparse graph degrades lesson selection
upstream of any narration improvement.

**3. Always run `--bootstrap-venv` automatically** — Rejected: `uv sync` mutates the
target repo's filesystem, which violates the "WiedunFlow is read-only on user code"
contract. Opt-in flag preserves consent.

## References

- `src/wiedunflow/adapters/jedi_resolver.py` — implementation.
- `src/wiedunflow/entities/resolution_stats.py` — `resolved_heuristic_count` field
  and invariants.
- `tests/unit/adapters/test_jedi_resolver.py` — heuristic match cases.
- `tests/unit/entities/test_resolution_stats_invariants.py` — combined-percentage
  property tests.
