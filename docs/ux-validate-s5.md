# T-005.UX-VALIDATE — Sprint 5 CLI manual sign-off

Side-by-side comparison of the 5 canonical CLI scenarios against
`.ai/ux-spec.md §CLI` (exact copy) and the hi-fi prototype in
`.claude/skills/wiedunflow-ux-skill/reference/cli/design/cli-session-data.js`.

Each scenario is reproducible via the integration suite
`tests/integration/test_cli_5_scenarios.py` (see Sprint 5 plan T-005.B16).
Check the boxes below once the rendered output has been visually inspected in
a real terminal.

**Binary gate**: 5/5 scenarios ✓ before tagging `v0.0.5` to `main`.

## Legend

- ✅ matches spec exactly (rendering + copy + color roles)
- ⚠️ matches semantically but drifts from exact spec copy
- ❌ regression or missing surface

## 1. Happy path — `wiedunflow ./my-repo --yes`

- [ ] Version banner on startup (`wiedunflow 0.0.5`)
- [ ] Cost-gate panel (HEAVY border, "ESTIMATED COST" title, table rows, TOTAL row, runtime summary)
- [ ] Stages `[1/7]` … `[7/7]` emit the exact stage names from ux-spec §CLI.stages
- [ ] 5-space-indented detail lines beneath each stage header
- [ ] `  ✓ done · <summary>` completion line in `good` tone per stage
- [ ] Final run-report card with `✓ success` title (green border)
- [ ] OSC 8 hyperlink to `file://…/tutorial.html` appears as clickable link in modern terminals

**Reference**: ux-spec §CLI.happy-path, cli-session-data.js `SCENARIO_HAPPY`.

## 2. Degraded run (>30 % lessons skipped)

- [ ] Grounding failures logged as `! lesson N: X unresolved references in path`
- [ ] `⚠ degraded run: N of M lessons will be marked SKIPPED` warning banner
- [ ] Stage 6 `✓ done · N lessons grounded · M skipped` still rendered in `good` tone
- [ ] Final run-report with `⚠ degraded` title (amber border), skipped count + list of IDs
- [ ] Exit code `2` (not 1 or 0)

**Reference**: ux-spec §CLI.error-scenarios.degraded, cli-session-data.js `SCENARIO_DEGRADED`.

## 3. Rate-limited (HTTP 429)

- [ ] Each 429: `  ⚠ HTTP 429 rate_limit_error (tokens-per-minute)` in `warn` tone
- [ ] Each retry: `  ⟳ backoff Ns (attempt K/5)` in `warn` tone
- [ ] On success: `  ✓ resumed · rate-limit window cleared` in `good` tone
- [ ] Up to 5 attempts before abort
- [ ] Final run-report mentions `N rate-limit retries absorbed (Xs total backoff)`

**Reference**: ux-spec §CLI.error-scenarios.rate-limited, cli-session-data.js `SCENARIO_RATE_LIMITED`.

## 4. Failed run (network exhausted / unhandled exception)

- [ ] `✗ network error: ConnectionResetError (api.anthropic.com)` in `err` tone
- [ ] Retry attempts logged with `⟳ retry N/3 in Xs`
- [ ] `⚠ exhausted retries. aborting pipeline.` banner
- [ ] Final run-report card with `✗ failed` title (red border)
- [ ] Run-report card contains `failed at`, `reason`, `resume` command
- [ ] Exit code `1`
- [ ] Partial cache retained for `--resume` (verify `.wiedunflow/` has checkpoint)

**Reference**: ux-spec §CLI.error-scenarios.failed, cli-session-data.js `SCENARIO_FAILED`.

## 5. Cost-gate abort (`--max-cost 0.01`)

- [ ] Cost-gate panel displayed before prompt
- [ ] User types `n` (or presses Enter / hits Ctrl+C)
- [ ] `aborted by user. no API calls were made.`
- [ ] `total cost: $0.00 · elapsed MM:SS` in `dim` tone
- [ ] Exit code `0` (intentional early exit, not a failure)
- [ ] No `.wiedunflow/run-report.json` mutation beyond the dry entry

**Reference**: ux-spec §CLI.error-scenarios.cost-gate-abort, cli-session-data.js `SCENARIO_COST_ABORT`.

## Sign-off

| Reviewer | Date | Decision | Notes |
|---|---|---|---|
| _pending_ | _pending_ | _pending_ | Initial checklist drafted 2026-04-22; fill after merging S5 and exercising scenarios in a real terminal. |

**Test-driven harness**: `tests/integration/test_cli_5_scenarios.py` (T-005.B16,
Sprint 6 follow-up) will regenerate the stdout for each scenario so the manual
diff is mechanical — this document captures the *visual* judgement that cannot
be asserted from stdout alone (color render, OSC 8 rendering, box-drawing
consistency across the top 3 terminals).
