# WiedunFlow CLI — implementation spec

This document describes the **user-facing output of `wiedun-flow init`** — exact copy, stage structure, prompt contract, error handling, and the run report. It is paired with the prototype in `design/WiedunFlow CLI.html`, which plays back the real scenarios in a browser. The prototype is the visual and copy source of truth; this README is the human-readable recap for the implementer.

## ⚠️ This is a terminal program, not a web app

The CLI runs in the user's real shell — `powershell.exe`, `bash`, `zsh`, `fish`, whatever. It is a **Python program that prints text to stdout**. The prototype in `design/` is an HTML mockup that imitates a PowerShell window so we can review the design in a browser; **the shipping CLI has no browser, no HTML, no CSS, no JavaScript.**

Do not port `cli-app.js`. Do not port `cli-styles.css`. Do not attempt to recreate the PowerShell window chrome, the tab bar, the `minimize/maximize/close` buttons, or any of the player controls (play/pause/scrubber/speed) — those are prototype scaffolding. The user's terminal already provides the window.

**What you port:** the strings from `design/cli-session-data.js` and the semantics in this README — output structure, stage copy, color roles, cost-gate contract, error handling. That is it.

## Scope

The CLI has one top-level command for MVP: `wiedun-flow init <repo-url-or-path>`. This skill spec'd that flow end-to-end. Other commands (`--help`, `--version`, `--resume`) are mentioned only where they are referenced by the init flow.

## Shipping direction

**Modern.** Boxed cost-gate, light color roles for status, unicode where it earns its place. Reference peers: Claude Code, `opencode`, `uv`, `rye`. Not heavy TUI (no full-screen takeover, no ncurses panels), not retro ASCII.

The prototype's Minimal and Retro ASCII directions are design explorations kept as Tweaks for review — **do not ship them.**

## Output structure

Every `wiedun-flow init` run produces output in this order:

1. **Invocation line** — the user's shell echoes the command.
2. **Version banner** — one dim line: `WiedunFlow 0.1.0 · claude-haiku-4-5 + claude-opus-4-5`.
3. **Preflight** — a labeled section with five checks:
   - git available (with version)
   - python version
   - `ANTHROPIC_API_KEY` present
   - target is a public Python repo
   - file count / LOC / top-level symbol count estimate
   Each check renders as `  ✓ <message>` in the success tone.
4. **Cost gate** — a boxed estimate and a blocking prompt (see below).
5. **Seven stages** — `[N/7] <Stage name>`, with indented detail lines and a final `✓ done · <summary>` per stage.
6. **Run report** — a framed summary with status (success / degraded / failed) and a clickable link to the generated tutorial.
7. **Fresh shell prompt** — a blinking caret on a new line.

## Stages

| # | Name                                    | Model  | What prints |
|---|-----------------------------------------|--------|-------------|
| 1 | Clone                                   | —      | `cloning <owner>/<repo>@<sha>…`, file/LOC count, elapsed. No cost. |
| 2 | Static analyse (Jedi)                   | —      | `[N/total] analysing <path>` lines; final `symbol resolution P% · X/Y references linked`. No cost. |
| 3 | Concept clustering · claude-haiku-4-5    | haiku  | Token in/out, cluster list (`· <label> (N lessons)`), per-stage cost, cumulative cost, elapsed. |
| 4 | Lesson outlining · claude-haiku-4-5      | haiku  | Token in/out, per-cluster `✓` ticks, cost summary. |
| 5 | Narration · claude-opus-4-5              | opus   | Token in/out, `[N/12] narrating '<lesson-title>'` lines, cost summary. |
| 6 | Grounding against AST                   | opus   | `checking all symbol references against Jedi index …`, per-lesson resolution, confidence verdict (HIGH / MEDIUM / LOW), cost summary. |
| 7 | Render + finalize                       | —      | `rendering tutorial.html with Jinja2 + Pygments`, inlining steps (CSS / JS / fonts), final size, total cost, elapsed. Trivial cost ($0.01). |

Use the exact wording above — it's taken verbatim from `design/cli-session-data.js::happyPath()`, which is the canonical script for stage-by-stage output.

## The cost gate

Print a box labeled `ESTIMATED COST` containing a small table:

```
Model      Stage                        Est. tokens       Est. cost
haiku      stages 1-4 (analyse/cluster)     ~410 000          $0.41
opus       stages 5-6 (narrate/ground)      ~280 000          $1.87
─────────────────────────────────────────────────────────────────
TOTAL                                       ~690 000          $2.28

Runtime est. 18-26 min · 12 lessons across 4 concept clusters
```

Then block on `Proceed? [y/N] ` (default **No**). Accept `y` / `yes` (case-insensitive) as yes; anything else — including empty, `n`, `no`, `Ctrl+C` — is a no.

- On **yes**: continue to stage 1.
- On **no**: print `aborted by user. no API calls were made.` and `total cost: $0.00 · elapsed MM:SS`. Exit 0. No cached artefacts, no `.wiedunflow-output` directory created.

## Color roles

Use these and only these status roles. Exact hex values are in the prototype CSS (`cli-styles.css` `:root`) under the Modern palette. Terminals should map them to ANSI roughly:

| Role    | Used for                                       | ANSI |
|---------|------------------------------------------------|------|
| default | regular text                                   | default FG |
| dim     | per-file progress, cost summaries, metadata    | 8 (bright black) |
| good    | `✓` ticks, success messages                    | 2 (green) |
| warn    | `⚠` grounding warnings, backoff notices         | 3 (yellow) |
| err     | `✗` failures, network errors                   | 1 (red) |
| accent  | stage headers `[N/7] <Name>`, section titles    | 4 (blue) |
| link    | final tutorial path                            | 6 (cyan), underlined |
| prompt  | user's `$` shell prompt                        | default FG, `$` green |

Do not invent new roles. Do not bold anything except links.

## Live counters

While a stage that calls an LLM is running, the status line (or a rich `Live` view, if you use `rich.live`) should continuously display:

- **elapsed** `MM:SS`
- **cumulative cost** `$X.XX`
- **tokens in / out** — update per-chunk or per-response

These appear in the prototype's bottom statusbar. In the real CLI, they can live in a `rich` Progress footer or a plain periodic redraw — the content and order are what matter.

## Scenarios (error paths)

The prototype has five scenarios. The happy path is the default; the others are what the CLI must do when things go wrong. Every scenario uses the same output format — only the middle changes.

### Happy path
12 lessons narrated, 0 grounding failures, cost $2.29, elapsed 00:45 in the demo (roughly 18–26 min in reality).
- Report status: `success`, confidence `HIGH`.

### Degraded
Grounding (stage 6) reports unresolved references in several lessons. The pipeline does **not abort** — it continues to stage 7, marks the affected lessons as `status: "skipped"` in the manifest, and sets `run_status: "degraded"`. The rendered tutorial shows a top banner and a per-lesson placeholder (see `reference/tutorial/README.md` for those components).

Print:
- `! lesson '<id>': <N> unresolved references in <path>` (warn tone) — one line per failed lesson
- `⚠ degraded run: N of M lessons will be marked SKIPPED` (warn tone) — summary
- The stage still ends with `✓ done · 8 lessons grounded · 4 skipped`

The run report uses status `degraded` and lists the skipped lesson ids.

### Rate limited (429)
Anthropic returns `rate_limit_error`. Absorb it with exponential backoff (2s, 4s, 8s, …, capped at 5 attempts). Each 429 and each backoff prints:
```
     ⚠ HTTP 429 rate_limit_error (tokens-per-minute)
     ⟳ backoff 2s (attempt 1/5)
```
On success resume: `     ✓ resumed · rate-limit window cleared`. The stage still completes normally — in the report, include `note: "N rate-limit retries absorbed (Xs total backoff)"`.

### Failed (unrecoverable)
Network stays down or a non-retryable error fires after retries are exhausted. Abort the pipeline cleanly:
- Print `     ✗ network error: <ExceptionName> (<host>)` (err tone) for each failure
- `     ⟳ retry N/3 in Ns` between retries
- `     ⚠ exhausted retries. aborting pipeline.` when giving up
- Emit a `failed` report with the stage where it died, the reason, elapsed, cost spent so far, and a resume hint:
  ```
  resume    wiedun-flow init --resume <run-id>
  ```
- Keep partial artefacts in `./.wiedunflow-output/.cache/` and mention this in the report (`cleanup`).
- Exit code 1.

### Cost-gate abort
User types `n` (or anything that isn't yes). See above — exit 0, no state on disk.

## Run report

Framed card at the end of the output. Left border color encodes status (green / amber / red). Fields differ by status; the common ones are:

- `lessons`   — `12 of 12 narrated` (or `8 of 12 narrated · 4 skipped` for degraded)
- `files analysed` — `47 python files · 87% symbol coverage`
- `elapsed`
- `cost`      — `$X.XX (haiku $Y.YY · opus $Z.ZZ)`
- `tokens`    — `558 860 in · 114 222 out`
- `open`      — clickable path to the generated tutorial

Failed runs replace most of these with `failed at`, `reason`, `cleanup`, `resume`.

Exact layout: see `addReport()` in `design/cli-app.js` — it's mechanical, just a list of `label: value` rows.

## Interaction details

- **Prompt** uses the terminal's real line editor. Arrow keys, backspace, Ctrl+C all behave normally. The default is No — bare `<Enter>` aborts.
- **Ctrl+C mid-stage** should interrupt the current LLM call, print a single `✗ interrupted by user` (err), then emit a `failed` report with `reason: keyboard interrupt` and the same resume hint as a network failure. Exit code 130.
- **Clickable tutorial link** — emit it as a file URL (`file:///…/tutorial.html`) on platforms where modern terminals auto-linkify, and as a plain relative path otherwise. The prototype treats it as an `<a>`.

## Files in this bundle

- `design/WiedunFlow CLI.html` — interactive prototype. Open it and use the scenario picker to watch each flow.
- `design/cli-styles.css` — all colors and typography. The Modern palette (light + dark) is what ships.
- `design/cli-session-data.js` — **the canonical line-by-line script for every scenario.** Port its content into Python output verbatim. Each scenario is a function returning an array of `{t, kind, text, tone}` events — ignore `t` (it's for playback) and read them in order.
- `design/cli-app.js` — playback engine. Read only if you want to understand how the prototype dispatches events; do not port it.

## Implementation checklist for Claude Code

- [ ] Use `rich` (or equivalent) for color and layout. Map the 8 color roles in this doc to `rich.style.Style` constants; use them consistently.
- [ ] Build a stage runner that prints `[N/7] <Name>` headers and indents all detail lines by 5 spaces (matches prototype).
- [ ] Implement the cost gate as a real `input()` prompt; default No.
- [ ] Emit the boxed estimate using `rich.panel.Panel` or `rich.box.HEAVY`. Must contain a table with model / stage / est. tokens / est. cost.
- [ ] Emit live counters during LLM stages (elapsed + cumulative cost + tokens). A `rich.live.Live` footer is fine; a plain per-chunk redraw is fine.
- [ ] Wire the four error paths: grounding degrade, 429 backoff, network failure, keyboard interrupt. Use the exact copy from `cli-session-data.js`.
- [ ] Emit the run report as a framed card. Status-color the left border.
- [ ] After the report, print the tutorial's absolute path (file URL if terminal supports hyperlinks) on its own line.
- [ ] `--help` and `--version` are standard `click` / `argparse` output — not designed here. Keep them terse and consistent with the rest of the tool's voice.
- [ ] Drop the prototype's Minimal and Retro ASCII directions and the scenario picker — they are not part of the shipping CLI.
