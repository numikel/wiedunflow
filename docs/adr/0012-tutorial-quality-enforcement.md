# ADR-0012 — Tutorial quality enforcement

Status: Accepted
Date: 2026-04-25
Sprint: post-MVP (v0.2.1)

## Context

The first generated tutorial against the `json-to-markdown` evaluation repo
(commit `3527003`, CodeGuide v0.2.0) surfaced four systemic quality gaps that
the v0.1.0 / v0.2.0 release gates did not catch:

1. **Hallucinated function signatures.** The narration LLM received only
   `{symbol, file_path, line_start, line_end, role}` per code reference and had
   to deduce signatures from names alone. It produced verifiably wrong code
   (e.g. `load_json_content` → `return json.loads(content)` versus actual
   `return {"content": content, "file_path": None}`; `write_markdown_file` with
   parameter order reversed). The grounding invariant from ADR-0007 only
   validated that symbol *names* exist, not that quoted *bodies* match.
2. **No happy-path ordering.** The planning prompt instructed leaves→roots
   ordering, which is correct for layered tutorials but unintuitive when a
   developer is exploring an unfamiliar repo for themselves (the primary
   persona). They expect the entry-point overview first.
3. **Verbose narration for one-line helpers.** A hard-coded 150-word floor
   in `grounding_retry.py` forced the LLM to pad descriptions of trivial
   functions (e.g. `dict_to_bold_pairs`, a one-liner) into 800-character
   paragraphs of filler.
4. **Trivial helpers consuming lesson budget.** Tiny one-liners ate lesson
   slots that should have gone to substantial concepts; the 30-lesson cap was
   wasted on `is_simple` and `dict_to_bold_pairs`.

The v0.2.1 fixes need to be opt-in (or no-op-by-default) so the upstream
release gate and any pinned eval snapshots are not retroactively invalidated.

## Decision

Four binary decisions, all gated by config so v0.2.0 behaviour is preserved
when defaults are kept and the new keys are absent from `tutorial.config.yaml`.

### 1. Source-excerpt injection (ON by default; bounded)

Populate `code_refs[*].source_excerpt` from the AST snapshot for every primary
reference whose body span is `< 30` lines. The narration prompt mandates
verbatim signature quoting from `source_excerpt` and forbids inventing
parameter names not present in it. Token cost is bounded (≈ 600 tokens per
excerpt × ≤ 30 lessons ≈ 18k tokens extra per run, well within Opus 4.7's
context). No config gate — this is the new baseline.

### 2. Snippet validator (ON by default; gated by `narration.snippet_validation`)

Post-narration, parse ```python fenced blocks, regex-match the first
`def NAME(params)` line, and compare against the matching `code_ref`'s
`source_excerpt`. Mismatches trigger a 1-shot retry with an explicit hint
(`You quoted: 'def {bad}' — actual signature is 'def {real}'`). Lenient on
body abbreviation (`# ...`) and trailing comments; strict on function name
and parameter token list. Disable with `narration.snippet_validation: false`
to bypass.

### 3. Happy-path lesson ordering (`auto` default; no-op when no entry point)

Detect entry points via AST heuristics — bare module-level `def main`,
`def cli`, `def run_*`, functions referenced inside
`if __name__ == "__main__":` blocks, decorators
(`@click.command`, `@click.group`, `@app.command`), and `__main__.py` modules.
Reorder the manifest post-planning to place the entry-point lesson at
position 1, preserving the closing lesson at the tail. Configurable via
`planning.entry_point_first: auto|always|never`:

- `auto` (default) — apply when an entry point is detected; no-op otherwise.
- `always` — apply unconditionally; raise `LessonManifestValidationError` if
  no entry point is detected (signals pipeline misconfiguration).
- `never` — preserve raw leaves→roots ordering.

### 4. Per-tier word-count floors + skip-trivial helpers

**Floors** (always active, replaces hard-coded 150):

| Primary code_ref span | Floor (words) |
|-----------------------|---------------|
| 1 line                | `narration.min_words_trivial` (default 50) |
| 2–9 lines             | 80 |
| 10–30 lines           | 220 |
| > 30 lines            | 350 |
| no primary ref        | 150 (legacy fallback) |

**Skip-trivial** (OFF by default, opt-in via
`planning.skip_trivial_helpers: true`): drop lessons whose primary
`code_ref` body span is < 3 lines AND the symbol is not cited as `primary`
in any other lesson AND the symbol is not in the entry-point set AND the
symbol is not in the top 5 % of `RankedGraph` by PageRank. Skipped helpers
are folded into a "Helper functions you'll see along the way" appendix
attached to the closing lesson.

## Consequences

- **Positive**: closes the four documented quality gaps. Eval rubric for
  v0.2.1 expects 0 hallucinated signatures (vs 3 confirmed in v0.2.0
  json-to-markdown report). Word-count distribution becomes proportional to
  function complexity rather than uniform 150-word filler. Defaults preserve
  v0.2.0 output for users who pin a config and do not opt in.
- **Negative**: snippet validator can produce false positives on heavily
  abbreviated bodies (`# ...` ellipsis). Mitigated by signature-line-only
  comparison. Entry-point detector is heuristic and can miss bespoke launch
  patterns (custom argparse setups not wrapped in a function); `auto` mode
  degrades gracefully to no-op.
- **Cost**: source-excerpt injection adds ~ 18k tokens per run. With Opus 4.7
  input pricing this is < $0.10 of additional cost for a full 30-lesson
  tutorial — well under the $8/tutorial budget.
- **Schema impact**: `code_refs[*].source_excerpt` is additive; ADR-0007
  schema version remains `1.0.0`. Older cache JSON deserialises unchanged.
- **ADR-0009 freeze**: respected. The progress UI fix uses the existing
  frozen DOM elements `#tutorial-progress` and `#tutorial-progress-label`;
  CSS/JS additions only.

## Alternatives considered

- **Snippet validator without source-excerpt injection** — rejected. Without
  body context the model would re-emit the same wrong signature on retry.
- **Mandatory `always` mode for entry-point ordering** — rejected. Some
  evaluation repos (libraries without a CLI) genuinely have no entry point;
  forcing a "main" lesson there would distort tutorials.
- **Removing the legacy 150-word fallback entirely** — rejected. When no
  primary `code_ref` exists (synthetic closing lessons, overview lessons),
  the fallback prevents underspecified narration.
- **Drop helper appendix; just delete trivial helpers silently** — rejected.
  Readers encountering a name in another lesson's snippet need a pointer back.

## Related

- ADR-0007 (planning prompt contract) — extended additively.
- ADR-0009 (output schema v1) — frozen DOM contract respected.
- Code (new):
  - `src/codeguide/use_cases/inject_source_excerpts.py`
  - `src/codeguide/use_cases/snippet_validator.py`
  - `src/codeguide/use_cases/entry_point_detector.py`
  - `src/codeguide/use_cases/skip_trivial.py`
- Code (modified): `src/codeguide/use_cases/grounding_retry.py`,
  `src/codeguide/use_cases/plan_lesson_manifest.py`,
  `src/codeguide/use_cases/generate_tutorial.py`,
  `src/codeguide/adapters/anthropic_provider.py`,
  `src/codeguide/adapters/openai_provider.py`,
  `src/codeguide/entities/code_ref.py`,
  `src/codeguide/entities/lesson_manifest.py`.
- Config: `planning.entry_point_first`, `planning.skip_trivial_helpers`,
  `narration.min_words_trivial`, `narration.snippet_validation`
  (`src/codeguide/cli/config.py`).
